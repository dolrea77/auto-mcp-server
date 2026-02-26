import logging
from datetime import datetime

from src.application.ports.diff_collection_port import DiffCollectionPort
from src.application.services.template_renderer import TemplateRenderer
from src.adapters.outbound.wiki_adapter import WikiAdapter
from src.application.use_cases.wiki_generation_orchestrator import _auto_summarize, _build_commit_list_html
from src.domain.wiki import WikiPageCreationResult

logger = logging.getLogger(__name__)


class CreateWikiIssuePageUseCase:
    """
    워크플로우 A: Jira 이슈 완료 처리 후 Wiki 이슈 정리 페이지 생성
    """

    def __init__(
        self,
        wiki_adapter: WikiAdapter,
        root_page_id: str,
        space_key: str,
        template_renderer: TemplateRenderer,
        diff_collector: DiffCollectionPort,
    ):
        self.wiki_adapter = wiki_adapter
        self.root_page_id = root_page_id
        self.space_key = space_key
        self._renderer = template_renderer
        self._diff_collector = diff_collector

    async def execute(
        self,
        issue_key: str,
        issue_title: str,
        assignee: str,
        resolution_date: str | None,
        priority: str,
        commit_list: str = "",
        change_summary: str = "",
    ) -> WikiPageCreationResult:
        """
        Jira 이슈 정리 Wiki 페이지를 생성합니다.
        """
        # 기준 날짜 결정
        if resolution_date:
            try:
                base_date = datetime.strptime(resolution_date[:10], "%Y-%m-%d")
            except ValueError:
                logger.warning("resolution_date 파싱 실패, 오늘 날짜 사용: %s", resolution_date)
                base_date = datetime.now()
        else:
            base_date = datetime.now()

        year = base_date.year
        month = base_date.month
        date_str = base_date.strftime("%Y-%m-%d")

        logger.info(
            "Wiki 이슈 정리 페이지 생성 시작: issue_key=%s, date=%s/%s",
            issue_key, year, month,
        )

        # 커밋 정보 획득: 외부 제공 우선, 없으면 로컬 git 시도
        branch_name = f"dev_{issue_key}"
        if commit_list.strip():
            logger.info("외부 제공 커밋 목록 사용: %d자", len(commit_list))
            commit_list_html = _build_commit_list_html(commit_list)
            if not change_summary.strip():
                change_summary = _auto_summarize(commit_list)
            else:
                logger.info("외부 제공 change_summary 사용: %d자", len(change_summary))
        else:
            logger.info("DiffCollectionPort로 커밋 조회 시도: %s", branch_name)
            commit_list_html, change_summary = await self._get_git_info(branch_name, change_summary)

        # 년/월 페이지 제목 생성
        year_title, month_title = self._renderer.build_year_month_titles(year, month)

        # 년/월 페이지 조회 or 생성
        year_page_id, month_page_id = await self.wiki_adapter.get_or_create_year_month_page(
            root_page_id=self.root_page_id,
            year=year,
            month=month,
            space_key=self.space_key,
            year_title=year_title,
            month_title=month_title,
        )

        # 페이지 제목
        page_title = f"[{issue_key}] {issue_title}"

        # 중복 페이지 확인
        existing = await self.wiki_adapter.find_page_by_title(month_page_id, page_title)
        if existing:
            raise RuntimeError(
                f"동일한 제목의 페이지가 이미 존재합니다: '{page_title}'\n"
                f"페이지 URL: {existing.url}"
            )

        # 템플릿 렌더링
        change_summary_html = self._renderer.render_change_summary_html(change_summary)
        body = self._renderer.render_workflow_body("workflow_a", {
            "ISSUE_KEY": issue_key,
            "ISSUE_TITLE": issue_title,
            "ASSIGNEE": assignee,
            "RESOLUTION_DATE": date_str,
            "PRIORITY": priority,
            "BRANCH_NAME": branch_name,
            "COMMIT_LIST": commit_list_html,
            "CHANGE_SUMMARY_HTML": change_summary_html,
        })

        # 페이지 생성
        page = await self.wiki_adapter.create_page(
            parent_page_id=month_page_id,
            title=page_title,
            body=body,
            space_key=self.space_key,
        )

        logger.info("Wiki 이슈 정리 페이지 생성 완료: %s", page.url)

        return WikiPageCreationResult(
            page_id=page.id,
            title=page.title,
            url=page.url,
            parent_page_id=month_page_id,
            year_page_id=year_page_id,
            month_page_id=month_page_id,
        )

    async def _get_git_info(self, branch_name: str, existing_summary: str) -> tuple[str, str]:
        """DiffCollectionPort를 사용하여 git 정보를 수집합니다."""
        try:
            diff_result = await self._diff_collector.collect_by_branch(branch_name)
            commit_list_html = _build_commit_list_html(diff_result.commits_raw)
            change_summary = existing_summary.strip() if existing_summary.strip() else _auto_summarize(diff_result.commits_raw)
            logger.info("Git 커밋 조회 완료: %d lines (branch=%s)", len(diff_result.commits_raw.splitlines()), branch_name)
            return commit_list_html, change_summary
        except RuntimeError as e:
            logger.warning("Git 정보 조회 실패: %s - %s", branch_name, str(e))
            return "<li>(브랜치를 찾을 수 없음)</li>", existing_summary or "(Git 정보 없음)"
