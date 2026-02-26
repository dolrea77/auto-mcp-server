import html
import logging
import uuid
from datetime import datetime, timedelta

from markupsafe import Markup

from src.application.ports.diff_collection_port import DiffCollectionPort
from src.application.ports.jira_port import JiraPort
from src.application.ports.wiki_port import WikiPort
from src.application.ports.wiki_session_store_port import WikiSessionStorePort
from src.application.services.template_renderer import TemplateRenderer
from src.domain.wiki import WikiPageCreationResult
from src.domain.wiki_workflow import (
    APPROVAL_TOKEN_TTL_MINUTES,
    WikiSession,
    WorkflowState,
    WorkflowType,
    get_wiki_date_for_issue,
)

logger = logging.getLogger(__name__)

# 유효한 상태 전이 맵
_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.INIT:            {WorkflowState.COLLECT_COMMITS, WorkflowState.RENDER_PREVIEW},
    WorkflowState.COLLECT_COMMITS: {WorkflowState.COLLECT_DIFF, WorkflowState.RENDER_PREVIEW},
    WorkflowState.COLLECT_DIFF:    {WorkflowState.ANALYZE_DIFF, WorkflowState.RENDER_PREVIEW},
    WorkflowState.ANALYZE_DIFF:    {WorkflowState.RENDER_PREVIEW},
    WorkflowState.RENDER_PREVIEW:  {WorkflowState.WAIT_APPROVAL},
    WorkflowState.WAIT_APPROVAL:   {WorkflowState.CREATE_WIKI, WorkflowState.FAILED},
    WorkflowState.CREATE_WIKI:     {WorkflowState.DONE, WorkflowState.FAILED},
    WorkflowState.DONE:            set(),
    WorkflowState.FAILED:          set(),
}


class WikiGenerationOrchestrator:
    """
    상태머신 기반 Wiki 생성 오케스트레이터.

    WAIT_APPROVAL 이전에는 Wiki create 절대 호출 금지.
    승인 토큰이 일치해야만 CREATE_WIKI 단계 진행 가능.
    """

    def __init__(
        self,
        wiki_port: WikiPort,
        session_store: WikiSessionStorePort,
        template_renderer: TemplateRenderer,
        diff_collector: DiffCollectionPort,
        root_page_id: str,
        space_key: str,
        jira_port: JiraPort | None = None,
    ):
        self._wiki = wiki_port
        self._sessions = session_store
        self._renderer = template_renderer
        self._diff = diff_collector
        self._root_page_id = root_page_id
        self._space_key = space_key
        self._jira = jira_port

    def _transition(self, session: WikiSession, target: WorkflowState) -> None:
        allowed = _TRANSITIONS.get(session.state, set())
        if target not in allowed:
            raise RuntimeError(
                f"잘못된 상태 전이: {session.state.value} → {target.value}. "
                f"허용: {[s.value for s in allowed]}"
            )
        logger.info(
            "상태 전이: %s → %s (session=%s)",
            session.state.value, target.value, session.session_id,
        )
        session.state = target
        session.touch()

    # ── Workflow A entry point ──

    async def start_workflow_a(
        self,
        issue_key: str,
        issue_title: str,
        assignee: str = "미지정",
        resolution_date: str = "",
        priority: str = "보통",
        commit_list: str = "",
        change_summary: str = "",
        project_name: str = "",
    ) -> WikiSession:
        """워크플로우 A 시작: Jira 이슈 기반 Wiki 생성"""
        session = WikiSession(
            workflow_type=WorkflowType.WORKFLOW_A,
            issue_key=issue_key,
            issue_title=issue_title,
            assignee=assignee,
            resolution_date=resolution_date or datetime.now().strftime("%Y-%m-%d"),
            priority=priority,
            project_name=project_name,
            branch_name=f"dev_{issue_key}",
            commit_list_raw=commit_list,
            change_summary=change_summary,
        )

        # Jira API로 이슈 상세 조회 (description, status, issuetype 등)
        await self._enrich_with_jira(session, [issue_key])

        # 프로젝트별 날짜 기준으로 resolution_date 결정 (명시되지 않은 경우)
        if not resolution_date and session.jira_issues:
            wiki_date = get_wiki_date_for_issue(session.jira_issues[0])
            if wiki_date:
                session.resolution_date = wiki_date

        if commit_list.strip():
            session.commit_list_html = _build_commit_list_html(commit_list)
            if not change_summary.strip():
                session.change_summary = _auto_summarize(commit_list)
            self._transition(session, WorkflowState.RENDER_PREVIEW)
            self._render_preview(session)
        else:
            self._transition(session, WorkflowState.COLLECT_COMMITS)
            await self._collect_commits(session)

        self._sessions.save(session)
        return session

    # ── Workflow B entry point ──

    async def start_workflow_b(
        self,
        page_title: str,
        commit_list: str,
        input_type: str = "브랜치명",
        input_value: str = "",
        base_date: str = "",
        change_summary: str = "",
        jira_issue_keys: str = "",
        diff_stat: str = "",
        project_name: str = "",
    ) -> WikiSession:
        """워크플로우 B 시작: 외부 수집 커밋 기반 Wiki 생성"""
        session = WikiSession(
            workflow_type=WorkflowType.WORKFLOW_B,
            page_title=page_title,
            input_type=input_type,
            input_value=input_value or page_title,
            base_date=base_date or datetime.now().strftime("%Y-%m-%d"),
            project_name=project_name,
            commit_list_raw=commit_list,
            change_summary=change_summary,
            diff_stat=diff_stat,
        )

        session.commit_list_html = _build_commit_list_html(commit_list)
        if not change_summary.strip():
            session.change_summary = _auto_summarize(commit_list)

        # Jira 이슈 enrichment (사용자가 명시적으로 키를 전달한 경우만)
        if jira_issue_keys.strip():
            keys = [k.strip().upper() for k in jira_issue_keys.split(",") if k.strip()]
            await self._enrich_with_jira(session, keys)

            # 프로젝트별 날짜 기준으로 base_date 업데이트 (년/월 경로 결정용)
            if session.jira_issues:
                wiki_date = get_wiki_date_for_issue(session.jira_issues[0])
                if wiki_date:
                    session.base_date = wiki_date

        self._transition(session, WorkflowState.RENDER_PREVIEW)
        self._render_preview(session)
        self._sessions.save(session)
        return session

    # ── Workflow C entry point ──

    async def start_workflow_c(
        self,
        page_title: str,
        content: str,
        parent_page_id: str = "",
        parent_page_title: str = "",
        space_key: str = "",
    ) -> WikiSession:
        """워크플로우 C 시작: 특정 부모 페이지 아래 자유 형식 Wiki 생성

        parent_page_id 또는 parent_page_title 중 하나는 반드시 제공해야 합니다.
        space_key 미지정 시 기본 space_key를 사용합니다.
        """
        resolved_space_key = space_key or self._space_key

        # 부모 페이지 ID 결정
        if not parent_page_id and parent_page_title:
            found = await self._wiki.search_page_by_title(
                title=parent_page_title,
                space_key=resolved_space_key,
            )
            if found is None:
                raise RuntimeError(
                    f"부모 페이지를 찾을 수 없습니다: '{parent_page_title}' "
                    f"(space: {resolved_space_key})"
                )
            parent_page_id = found.id
            logger.info("부모 페이지 검색 완료: '%s' → id=%s", parent_page_title, parent_page_id)

        if not parent_page_id:
            raise RuntimeError("parent_page_id 또는 parent_page_title 중 하나를 지정해야 합니다")

        session = WikiSession(
            workflow_type=WorkflowType.WORKFLOW_C,
            parent_page_id=parent_page_id,
            page_title=page_title,
            content_raw=content,
            custom_space_key=resolved_space_key,
        )

        self._transition(session, WorkflowState.RENDER_PREVIEW)
        self._render_preview(session)
        self._sessions.save(session)
        return session

    # ── Approval ──

    async def approve(self, session_id: str, approval_token: str) -> WikiPageCreationResult:
        """사용자 승인 후 Wiki 페이지를 실제로 생성합니다."""
        session = self._sessions.get(session_id)
        if session is None:
            raise RuntimeError(f"세션을 찾을 수 없습니다: {session_id}")

        if session.state != WorkflowState.WAIT_APPROVAL:
            raise RuntimeError(
                f"승인 가능한 상태가 아닙니다. 현재: {session.state.value}"
            )

        if session.approval_token != approval_token:
            raise RuntimeError("승인 토큰이 일치하지 않습니다.")

        if session.is_approval_expired():
            raise RuntimeError(
                f"승인 토큰이 만료되었습니다 (유효 시간: {APPROVAL_TOKEN_TTL_MINUTES}분). "
                f"워크플로우를 다시 시작해주세요."
            )

        self._transition(session, WorkflowState.CREATE_WIKI)
        try:
            result = await self._create_wiki_page(session)
            self._transition(session, WorkflowState.DONE)
            self._sessions.save(session)
            return result
        except Exception:
            session.state = WorkflowState.FAILED
            self._sessions.save(session)
            raise

    def get_status(self, session_id: str) -> dict | None:
        """세션 상태 조회"""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        page_title = session.page_title or f"[{session.issue_key}] {session.issue_title}"
        return {
            "session_id": session.session_id,
            "workflow_type": session.workflow_type.value,
            "state": session.state.value,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "issue_key": session.issue_key,
            "page_title": page_title,
            "approval_token": session.approval_token if session.state == WorkflowState.WAIT_APPROVAL else "",
            "preview": session.rendered_preview[:500] if session.rendered_preview else "",
        }

    # ── Internal steps ──

    async def _collect_commits(self, session: WikiSession) -> None:
        try:
            diff_result = await self._diff.collect_by_branch(session.branch_name)
            session.commit_list_raw = diff_result.commits_raw
            session.diff_raw = diff_result.diff_raw
            session.diff_stat = diff_result.diff_stat
            session.commit_list_html = _build_commit_list_html(diff_result.commits_raw)

            if not session.change_summary:
                session.change_summary = _auto_summarize(diff_result.commits_raw)
        except RuntimeError:
            logger.warning("Git 커밋 수집 실패: %s - 빈 데이터로 프리뷰 생성", session.branch_name)
            session.commit_list_html = "<li>(커밋 수집 실패)</li>"
            if not session.change_summary:
                session.change_summary = "(Git 정보 없음)"

        self._transition(session, WorkflowState.RENDER_PREVIEW)
        self._render_preview(session)

    def _render_preview(self, session: WikiSession) -> None:
        change_summary_html = self._renderer.render_change_summary_html(session.change_summary)
        jira_issues_html = self._build_jira_issues_html(session.jira_issues)
        jira_description_html = self._build_jira_description_html(session.jira_issues)
        has_jira_issues = len(session.jira_issues) > 0

        if session.workflow_type == WorkflowType.WORKFLOW_A:
            variables = {
                "ISSUE_KEY": session.issue_key,
                "ISSUE_TITLE": session.issue_title,
                "ASSIGNEE": session.assignee,
                "RESOLUTION_DATE": session.resolution_date,
                "PRIORITY": session.priority,
                "BRANCH_NAME": session.branch_name,
                "COMMIT_LIST": Markup(session.commit_list_html),
                "CHANGE_SUMMARY_HTML": change_summary_html,
                "DIFF_STAT": session.diff_stat,
                "JIRA_STATUS": session.jira_issues[0]["status"] if has_jira_issues else "",
                "JIRA_ISSUETYPE": session.jira_issues[0]["issuetype"] if has_jira_issues else "",
                "JIRA_URL": session.jira_issues[0]["url"] if has_jira_issues else "",
                "JIRA_WIKI_DATE": get_wiki_date_for_issue(session.jira_issues[0]) if has_jira_issues else "",
                "JIRA_DESCRIPTION_HTML": Markup(jira_description_html),
                "HAS_JIRA_DETAIL": has_jira_issues,
            }
            session.rendered_preview = self._renderer.render_workflow_body("workflow_a", variables)
        elif session.workflow_type == WorkflowType.WORKFLOW_C:
            content_html = self._renderer.render_change_summary_html(session.content_raw)
            variables = {"CONTENT_HTML": content_html}
            session.rendered_preview = self._renderer.render_workflow_body("workflow_c", variables)
        else:
            variables = {
                "INPUT_TYPE": session.input_type,
                "INPUT_VALUE": session.input_value,
                "BASE_DATE": session.base_date,
                "COMMIT_LIST": Markup(session.commit_list_html),
                "CHANGE_SUMMARY_HTML": change_summary_html,
                "DIFF_STAT": session.diff_stat,
                "JIRA_ISSUES_HTML": Markup(jira_issues_html),
                "JIRA_DESCRIPTION_HTML": Markup(jira_description_html),
                "HAS_JIRA_ISSUES": has_jira_issues,
            }
            session.rendered_preview = self._renderer.render_workflow_body("workflow_b", variables)

        session.approval_token = str(uuid.uuid4())
        session.approval_expires_at = datetime.now() + timedelta(minutes=APPROVAL_TOKEN_TTL_MINUTES)
        self._transition(session, WorkflowState.WAIT_APPROVAL)

    async def _enrich_with_jira(self, session: WikiSession, issue_keys: list[str]) -> None:
        """Jira 이슈 키 목록으로 이슈 상세 조회 후 session에 저장."""
        if self._jira is None or not issue_keys:
            return
        for key in issue_keys[:5]:
            try:
                issues = await self._jira.search_issues(f'key="{key}"')
                if issues:
                    issue = issues[0]
                    session.jira_issues.append({
                        "key": issue.key,
                        "summary": issue.summary,
                        "status": issue.status,
                        "assignee": issue.assignee,
                        "issuetype": issue.issuetype,
                        "url": issue.url,
                        "description": issue.description or "",
                        "created": issue.created or "",
                        "custom_end_date": issue.custom_end_date or "",
                    })
            except Exception as e:
                logger.warning("Jira 이슈 조회 실패 (%s): %s", key, e)

    @staticmethod
    def _build_jira_issues_html(jira_issues: list[dict]) -> str:
        """Jira 이슈 목록을 HTML 테이블 행으로 변환 (Workflow B용)."""
        if not jira_issues:
            return ""
        rows = []
        for issue in jira_issues:
            wiki_date = get_wiki_date_for_issue(issue)
            rows.append(
                f"<tr>"
                f'<td><a href="{html.escape(issue["url"], quote=True)}">'
                f'{html.escape(issue["key"])}</a></td>'
                f'<td>{html.escape(issue["summary"])}</td>'
                f'<td>{html.escape(issue["status"])}</td>'
                f'<td>{html.escape(issue["assignee"])}</td>'
                f'<td>{html.escape(issue["issuetype"])}</td>'
                f'<td>{html.escape(wiki_date)}</td>'
                f"</tr>"
            )
        return "\n".join(rows)

    @staticmethod
    def _build_jira_description_html(jira_issues: list[dict]) -> str:
        """Jira 이슈 description을 HTML로 변환 (Workflow A/B 공용)."""
        if not jira_issues:
            return ""
        parts = []
        for issue in jira_issues:
            desc = issue.get("description", "").strip()
            if desc:
                if len(jira_issues) > 1:
                    parts.append(
                        f"<h4>{html.escape(issue['key'])}: "
                        f"{html.escape(issue['summary'])}</h4>"
                    )
                desc_html = html.escape(desc).replace("\n", "<br/>")
                parts.append(f"<p>{desc_html}</p>")
        return "\n".join(parts) if parts else ""

    _MAX_UPDATE_RETRIES = 3

    async def _create_wiki_page(self, session: WikiSession) -> WikiPageCreationResult:
        # Workflow C: 사용자 지정 부모 페이지 아래에 직접 생성
        if session.workflow_type == WorkflowType.WORKFLOW_C:
            page_title = session.page_title
            parent_id = session.parent_page_id
            space = session.custom_space_key or self._space_key

            existing = await self._wiki.find_page_by_title(parent_id, page_title)
            if existing:
                raise RuntimeError(
                    f"동일한 제목의 페이지가 이미 존재합니다: '{page_title}'\n"
                    f"페이지 URL: {existing.url}"
                )

            page = await self._wiki.create_page(
                parent_page_id=parent_id,
                title=page_title,
                body=session.rendered_preview,
                space_key=space,
            )

            return WikiPageCreationResult(
                page_id=page.id,
                title=page.title,
                url=page.url,
                parent_page_id=parent_id,
            )

        # Workflow A/B: 연/월 계층 구조 아래에 생성
        if session.workflow_type == WorkflowType.WORKFLOW_A:
            date_str = session.resolution_date
            page_title = f"[{session.issue_key}] {session.issue_title}"
        else:
            date_str = session.base_date
            page_title = session.page_title

        date_obj = datetime.strptime(date_str[:10], "%Y-%m-%d")
        year, month = date_obj.year, date_obj.month

        year_title, month_title = self._renderer.build_year_month_titles(year, month)
        year_page_id, month_page_id = await self._wiki.get_or_create_year_month_page(
            root_page_id=self._root_page_id,
            year=year,
            month=month,
            space_key=self._space_key,
            year_title=year_title,
            month_title=month_title,
        )

        existing = await self._wiki.find_page_by_title(month_page_id, page_title)
        if existing and session.project_name:
            # Upsert: 기존 페이지에 프로젝트 섹션 append
            return await self._append_to_existing_page(
                session, existing, month_page_id, year_page_id,
            )
        elif existing:
            # 하위호환: project_name 없으면 기존처럼 에러
            raise RuntimeError(
                f"동일한 제목의 페이지가 이미 존재합니다: '{page_title}'\n"
                f"페이지 URL: {existing.url}"
            )

        page = await self._wiki.create_page(
            parent_page_id=month_page_id,
            title=page_title,
            body=session.rendered_preview,
            space_key=self._space_key,
        )

        return WikiPageCreationResult(
            page_id=page.id,
            title=page.title,
            url=page.url,
            parent_page_id=month_page_id,
            year_page_id=year_page_id,
            month_page_id=month_page_id,
        )

    async def _append_to_existing_page(
        self,
        session: WikiSession,
        existing: WikiPage,
        month_page_id: str,
        year_page_id: str,
    ) -> WikiPageCreationResult:
        """기존 페이지에 프로젝트 섹션을 추가합니다 (Optimistic locking retry)."""
        project_name = session.project_name
        today = datetime.now().strftime("%Y-%m-%d")

        append_section = _build_append_section(
            project_name=project_name,
            date_str=today,
            body_html=session.rendered_preview,
        )

        for attempt in range(1, self._MAX_UPDATE_RETRIES + 1):
            try:
                page_with_content = await self._wiki.get_page_with_content(existing.id)
                merged_body = page_with_content.body + append_section
                new_version = page_with_content.version + 1

                page = await self._wiki.update_page(
                    page_id=existing.id,
                    title=page_with_content.title,
                    body=merged_body,
                    version=new_version,
                    space_key=page_with_content.space_key or self._space_key,
                )

                logger.info(
                    "기존 페이지에 프로젝트 섹션 추가 완료: page_id=%s, project=%s, version=%d",
                    page.id, project_name, new_version,
                )

                return WikiPageCreationResult(
                    page_id=page.id,
                    title=page.title,
                    url=page.url,
                    parent_page_id=month_page_id,
                    year_page_id=year_page_id,
                    month_page_id=month_page_id,
                    was_updated=True,
                )
            except RuntimeError as e:
                if "버전 충돌" in str(e) and attempt < self._MAX_UPDATE_RETRIES:
                    logger.warning(
                        "페이지 업데이트 버전 충돌 (시도 %d/%d), 재시도...",
                        attempt, self._MAX_UPDATE_RETRIES,
                    )
                    continue
                raise


# ── 유틸리티 함수 (기존 create_wiki_page_with_content.py에서 이동) ──

def _build_commit_list_html(commit_list: str) -> str:
    """줄바꿈으로 구분된 커밋 목록을 HTML <li> 형식으로 변환합니다."""
    if not commit_list or not commit_list.strip():
        return "<li>(커밋 없음)</li>"
    lines = [line.strip() for line in commit_list.strip().splitlines() if line.strip()]
    if not lines:
        return "<li>(커밋 없음)</li>"
    return "\n".join(f"<li>{html.escape(line)}</li>" for line in lines[:100])


def _build_append_section(project_name: str, date_str: str, body_html: str) -> str:
    """멀티프로젝트 append용 프로젝트 섹션 HTML을 생성합니다."""
    escaped_name = html.escape(project_name)
    escaped_date = html.escape(date_str)
    return (
        '\n<hr/>\n'
        '<ac:structured-macro ac:name="info">\n'
        f'  <ac:parameter ac:name="title">{escaped_name} '
        f'추가 변경사항 ({escaped_date})</ac:parameter>\n'
        '  <ac:rich-text-body>\n'
        f'    {body_html}\n'
        '  </ac:rich-text-body>\n'
        '</ac:structured-macro>\n'
    )


def _auto_summarize(commit_list: str) -> str:
    """커밋 목록에서 변경 내용 요약을 자동 생성합니다."""
    if not commit_list or not commit_list.strip():
        return "(변경 내용 없음)"
    lines = [line.strip() for line in commit_list.strip().splitlines() if line.strip()]
    if not lines:
        return "(변경 내용 없음)"
    summary_lines = []
    for line in lines[:5]:
        parts = line.split(" ", 1)
        msg = parts[1] if len(parts) == 2 and len(parts[0]) >= 7 else line
        summary_lines.append(f"- {msg}")
    return "\n".join(summary_lines)
