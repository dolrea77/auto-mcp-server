import json
import logging
import os
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent

from src.adapters.outbound.git_local_adapter import GitLocalAdapter
from src.configuration.container import build_container
from src.domain.wiki_workflow import extract_jira_issue_keys, get_wiki_date_for_issue

logger = logging.getLogger(__name__)


# 영어 상태값 → 한글 상태값 매핑
STATUS_MAPPING = {
    # 영어 → 관련된 모든 한글 상태값 리스트
    "done": ["완료", "완료(개발)", "완료(설계)", "DONE(BNF)", "개발완료(BNF)", "배포완료(BNF)", "검수완료(BNF)", "답변완료(BNF)", "기획/설계 완료(BNF)"],
    "completed": ["완료", "완료(개발)", "완료(설계)", "DONE(BNF)", "개발완료(BNF)", "배포완료(BNF)", "검수완료(BNF)"],
    "in progress": ["진행중(개발)", "진행중(설계)", "처리중(BNF)", "개발(BNF)"],
    "to do": ["할일", "할일(개발)", "할일(설계)", "할일(BNF)"],
    "todo": ["할일", "할일(개발)", "할일(설계)", "할일(BNF)"],
    "open": ["할일", "할일(개발)", "할일(설계)", "개발접수(BNF)"],
    "pending": ["보류(BNF)", "패치대기(BNF)"],
    "in review": ["설계검수(BNF)", "운영검수(BNF)"],
}


def normalize_statuses(statuses: list[str] | None) -> list[str] | None:
    """영어 상태값을 한글 상태값으로 변환합니다."""
    if statuses is None:
        return None

    normalized = []
    for status in statuses:
        status_lower = status.lower().strip()

        # 영어 상태값이면 매핑된 한글 상태값들로 확장
        if status_lower in STATUS_MAPPING:
            mapped_statuses = STATUS_MAPPING[status_lower]
            normalized.extend(mapped_statuses)
            logger.info(f"'{status}' → {mapped_statuses} (자동 매핑)")
        else:
            # 한글 상태값은 그대로 사용
            normalized.append(status)

    # 중복 제거
    return list(dict.fromkeys(normalized))


def _check_wiki_settings(settings) -> list[TextContent] | None:
    """Wiki 설정 검증. 미설정 시 안내 TextContent 반환, 정상이면 None."""
    if not settings.wiki_base_url or not settings.wiki_issue_root_page_id:
        return [TextContent(
            type="text",
            text="# ⚠️ Wiki 설정이 필요합니다\n\n"
                 "환경 변수 `WIKI_BASE_URL`, `WIKI_ISSUE_SPACE_KEY`, "
                 "`WIKI_ISSUE_ROOT_PAGE_ID`를 설정해주세요."
        )]
    return None


def _check_wiki_base_url(settings) -> list[TextContent] | None:
    """Wiki 기본 URL 검증. 조회/수정은 root_page_id 불필요."""
    if not settings.wiki_base_url:
        return [TextContent(
            type="text",
            text="# ⚠️ Wiki 설정이 필요합니다\n\n"
                 "환경 변수 `WIKI_BASE_URL`을 설정해주세요."
        )]
    return None


async def _detect_repository(
    branch_name: str, git_repos: dict[str, str],
) -> list[tuple[str, str]]:
    """등록된 저장소들에서 브랜치를 찾아 [(경로, 프로젝트명), ...] 목록을 반환합니다.

    탐지 우선순위:
    1. 머지 커밋이 있는 저장소 (이미 머지 완료된 브랜치)
    2. 활성 브랜치가 있는 저장소 (아직 머지 안 된 브랜치)

    같은 단계에서 여러 저장소가 매칭되면 모두 반환합니다.
    """
    # 1차: 머지 커밋 검색
    merge_matches: list[tuple[str, str]] = []
    for name, path in git_repos.items():
        adapter = GitLocalAdapter(working_dir=path)
        extraction = await adapter._extract_from_merge_commit(branch_name)
        if extraction is not None:
            logger.info("머지 커밋 탐지: %s (%s)", name, path)
            merge_matches.append((path, name))

    if merge_matches:
        return merge_matches

    # 2차: 활성 브랜치 검색
    branch_matches: list[tuple[str, str]] = []
    for name, path in git_repos.items():
        adapter = GitLocalAdapter(working_dir=path)
        check = await adapter._run_git("rev-parse", "--verify", branch_name)
        if check.returncode == 0:
            logger.info("활성 브랜치 탐지: %s (%s)", name, path)
            branch_matches.append((path, name))

    return branch_matches


def _format_ambiguity_message(
    branch_name: str, matches: list[tuple[str, str]],
) -> str:
    """여러 저장소에서 브랜치가 발견되었을 때 안내 메시지를 생성합니다."""
    lines = [
        "# ⚠️ 브랜치가 여러 저장소에서 발견됨\n",
        f"**브랜치:** `{branch_name}`\n",
        "다음 저장소들에서 해당 브랜치가 발견되었습니다:\n",
        "| # | 프로젝트 | 경로 |",
        "|---|---------|------|",
    ]
    for i, (path, name) in enumerate(matches, 1):
        lines.append(f"| {i} | {name} | `{path}` |")
    lines.append("\n`repository_path` 파라미터를 지정하여 저장소를 선택하세요.")
    return "\n".join(lines)


def _validate_repository_path(
    repository_path: str, git_repos: dict[str, str],
) -> str | None:
    """명시적으로 지정된 repository_path가 GIT_REPOSITORIES allowlist에 포함되는지 검증합니다.

    Returns:
        None이면 유효, 문자열이면 에러 메시지
    """
    if not git_repos:
        # allowlist가 비어있으면 검증 스킵 (환경변수 미설정)
        return None

    resolved = str(Path(repository_path).resolve())
    for _, allowed_path in git_repos.items():
        allowed_resolved = str(Path(allowed_path).resolve())
        if resolved == allowed_resolved or resolved.startswith(allowed_resolved + os.sep):
            return None

    repos_list = ", ".join(git_repos.values())
    return (
        f"# ⛔ repository_path 접근 거부\n\n"
        f"**지정 경로:** `{repository_path}`\n\n"
        f"보안 정책에 따라 `GIT_REPOSITORIES`에 등록된 경로만 허용됩니다.\n\n"
        f"**등록된 경로:** {repos_list}\n"
    )


# ── 스마트 Diff 필터링 ──

_LOW_PRIORITY_PATTERNS = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    ".generated.", "OpenApi/",
    ".min.js", ".min.css",
)
_MEDIUM_PRIORITY_EXTENSIONS = frozenset({
    ".json", ".yaml", ".yml", ".css", ".scss", ".md", ".svg",
})


@dataclass
class _DiffTruncateResult:
    diff_text: str
    included_files: list[str]
    excluded_files: list[str]
    original_size: int
    truncated_size: int


def _split_diff_by_file(diff_raw: str) -> list[tuple[str, str]]:
    """unified diff를 파일 단위로 분리합니다. [(filename, chunk), ...]"""
    chunks: list[tuple[str, str]] = []
    current_file = ""
    current_lines: list[str] = []

    for line in diff_raw.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if current_lines:
                chunks.append((current_file, "".join(current_lines)))
            parts = line.split(" b/", 1)
            current_file = parts[1].strip() if len(parts) == 2 else line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append((current_file, "".join(current_lines)))

    return chunks


def _smart_truncate_diff(diff_raw: str, *, max_chars: int = 30000) -> _DiffTruncateResult:
    """파일 우선순위 기반으로 중요한 변경사항을 우선 포함합니다.

    우선순위: 소스코드(high) > 설정/스타일(medium) > lock/생성파일(low)
    """
    chunks = _split_diff_by_file(diff_raw)

    high: list[tuple[str, str]] = []
    medium: list[tuple[str, str]] = []
    low: list[tuple[str, str]] = []

    for filename, chunk in chunks:
        if any(p in filename for p in _LOW_PRIORITY_PATTERNS):
            low.append((filename, chunk))
        elif any(filename.endswith(ext) for ext in _MEDIUM_PRIORITY_EXTENSIONS):
            medium.append((filename, chunk))
        else:
            high.append((filename, chunk))

    result_parts: list[str] = []
    total = 0
    included: list[str] = []
    excluded: list[str] = []

    for filename, chunk in high + medium + low:
        if total + len(chunk) <= max_chars:
            result_parts.append(chunk)
            total += len(chunk)
            included.append(filename)
        else:
            excluded.append(filename)

    diff_text = _mask_sensitive_in_diff("\n".join(result_parts))
    return _DiffTruncateResult(
        diff_text=diff_text,
        included_files=included,
        excluded_files=excluded,
        original_size=len(diff_raw),
        truncated_size=total,
    )


# 민감 정보 패턴 (diff 출력에서 마스킹)
_SENSITIVE_PATTERNS = [
    # API 키 / 토큰 (일반적인 형태)
    (re.compile(r"""(?i)(api[_-]?key|api[_-]?secret|auth[_-]?token|access[_-]?token|secret[_-]?key|private[_-]?key)\s*[:=]\s*['"]?([^\s'"]{8,})"""), r"\1=***MASKED***"),
    # 비밀번호
    (re.compile(r"""(?i)(password|passwd|pwd)\s*[:=]\s*['"]?([^\s'"]{4,})"""), r"\1=***MASKED***"),
    # Bearer 토큰
    (re.compile(r"(?i)(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)"), r"\1***MASKED***"),
]


def _mask_sensitive_in_diff(diff_text: str) -> str:
    """diff 텍스트에서 민감 정보 패턴을 마스킹합니다."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        diff_text = pattern.sub(replacement, diff_text)
    return diff_text


_PREVIEW_WARNING = (
    "⚠️ **중요: 이것은 프리뷰입니다. 실제 Wiki 페이지는 아직 생성되지 않았습니다!**\n\n"
    "🛑 **에이전트 주의사항:**\n"
    "- **절대로 자동으로 승인하지 마세요**\n"
    "- 반드시 사용자에게 프리뷰를 보여주고 승인 여부를 확인받으세요\n"
    "- 사용자가 명시적으로 승인한 경우에만 approve_wiki_generation을 호출하세요\n\n"
    "---\n\n"
)


def _format_approval_instructions(session) -> str:
    """승인 안내 + approve 호출 예시를 포맷팅합니다."""
    text = "\n---\n\n"
    text += "## ❓ 다음 단계\n\n"
    text += "**사용자에게 물어보세요:**\n"
    text += '> "위 내용으로 Wiki 페이지를 생성할까요? (yes/no)"\n\n'
    text += "**사용자가 승인한 경우에만:**\n"
    text += f"```\napprove_wiki_generation(\n"
    text += f"  session_id=\"{session.session_id}\",\n"
    text += f"  approval_token=\"{session.approval_token}\"\n"
    text += ")\n```\n"
    return text


def register_tools(app: Server) -> None:
    """MCP Tool 핸들러를 서버에 등록합니다."""

    # 로그에서 마스킹할 민감 필드 (값이 긴 텍스트이거나 토큰/비밀정보)
    _SENSITIVE_FIELDS = {"approval_token", "commit_list", "change_summary", "content", "jql", "body"}
    _TRUNCATE_FIELDS = {"repository_path"}  # 경로는 축약 표시

    def _mask_arguments(arguments: dict) -> dict:
        """로깅용으로 민감 필드를 마스킹합니다."""
        masked = {}
        for key, value in arguments.items():
            if key in _SENSITIVE_FIELDS:
                if isinstance(value, str) and len(value) > 20:
                    masked[key] = f"{value[:20]}... ({len(value)}자)"
                else:
                    masked[key] = "***"
            elif key in _TRUNCATE_FIELDS:
                masked[key] = value
            else:
                masked[key] = value
        return masked

    @app.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            container = build_container()
            logger.info("=" * 60)
            logger.info("🔧 Tool 호출: %s", name)
            logger.info("인자: %s", _mask_arguments(arguments))
            logger.info("환경: %s", container.settings.app_env)
            logger.info("=" * 60)

            if name == "get_jira_issue":
                # 특정 이슈 조회 (key로)
                key = arguments.get("key")
                if not key:
                    raise ValueError("key 파라미터가 필요합니다")

                result = await container.get_jira_issue_by_key_use_case.execute(key=key)

                if not result:
                    return [TextContent(
                        type="text",
                        text=f"# ⚠️ 이슈를 찾을 수 없습니다\n\n**이슈 키:** {key}\n\n해당 키의 이슈가 존재하지 않거나 접근 권한이 없습니다."
                    )]

                # 단일 이슈 상세 정보 포맷팅
                formatted_text = f"# 📋 Jira 이슈 상세\n\n"
                formatted_text += f"## [{result['key']}]({result['url']}) {result['summary']}\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **이슈 키** | {result['key']} |\n"
                formatted_text += f"| **상태** | {result['status']} |\n"
                formatted_text += f"| **담당자** | {result['assignee']} |\n"
                formatted_text += f"| **유형** | {result['issuetype']} |\n"
                formatted_text += f"| **링크** | {result['url']} |\n"

                if result.get('description'):
                    desc = result['description'].strip()
                    # 전체 설명 표시
                    formatted_text += f"\n### 📝 설명\n\n{desc}\n"

                logger.info("✅ Tool 실행 완료: 이슈 %s 조회됨", key)

                return [TextContent(
                    type="text",
                    text=formatted_text
                )]

            if name == "get_jira_issues":
                # 영어 상태값을 한글로 자동 변환
                statuses = arguments.get("statuses")
                normalized_statuses = normalize_statuses(statuses)
                project_key = arguments.get("project_key", "").strip().upper() or None

                if statuses != normalized_statuses:
                    logger.info("상태값 자동 변환: %s → %s", statuses, normalized_statuses)

                # 변환된 상태값으로 실행
                result = await container.get_jira_issues_use_case.execute(
                    statuses=normalized_statuses,
                    project_key=project_key,
                )
                logger.info("✅ Tool 실행 완료: %d개 이슈 조회됨", len(result))

                # MCP 표준 형식으로 응답 반환
                if not result:
                    return [TextContent(
                        type="text",
                        text="조회된 이슈가 없습니다."
                    )]

                # 이슈 목록을 보기 좋게 포맷팅
                formatted_text = f"# 📋 Jira 이슈 조회 결과\n\n"
                if project_key:
                    formatted_text += f"**프로젝트:** `{project_key}`\n\n"
                formatted_text += f"**총 {len(result)}건**\n\n"
                formatted_text += "---\n\n"

                for i, issue in enumerate(result, 1):
                    # 이슈 헤더
                    formatted_text += f"### {i}. [{issue['key']}]({issue['url']}) {issue['summary']}\n\n"

                    # 이슈 정보 테이블
                    formatted_text += "| 항목 | 내용 |\n"
                    formatted_text += "|------|------|\n"
                    formatted_text += f"| **상태** | {issue['status']} |\n"
                    formatted_text += f"| **담당자** | {issue['assignee']} |\n"
                    formatted_text += f"| **유형** | {issue['issuetype']} |\n"
                    formatted_text += f"| **링크** | {issue['url']} |\n"

                    # 설명 (있는 경우)
                    if issue.get('description'):
                        desc = issue['description'].strip()
                        # 설명이 너무 길면 요약
                        if len(desc) > 300:
                            desc = desc[:300] + "..."
                        # 줄바꿈을 <br>로 변경 (마크다운 테이블 내에서)
                        desc = desc.replace('\n', ' ')
                        formatted_text += f"| **설명** | {desc} |\n"

                    formatted_text += "\n---\n\n"

                return [TextContent(
                    type="text",
                    text=formatted_text
                )]

            if name == "get_jira_project_meta":
                project_key = arguments.get("project_key", "").strip().upper()
                if not project_key:
                    raise ValueError("project_key 파라미터가 필요합니다")

                result = await container.get_project_meta_use_case.execute(project_key=project_key)
                issuetype_statuses: dict = result["issuetype_statuses"]

                formatted_text = f"# 📊 Jira 프로젝트 메타 정보\n\n"
                formatted_text += f"**프로젝트 키:** `{result['project_key']}`\n\n"
                formatted_text += f"**이슈 유형 수:** {len(issuetype_statuses)}개\n\n"
                formatted_text += "---\n\n"

                for issuetype, statuses in issuetype_statuses.items():
                    formatted_text += f"## 📌 {issuetype}\n\n"
                    formatted_text += "| 번호 | 상태값 |\n"
                    formatted_text += "|------|--------|\n"
                    for i, status in enumerate(statuses, 1):
                        formatted_text += f"| {i} | {status} |\n"
                    formatted_text += "\n"

                logger.info("✅ Tool 실행 완료: 프로젝트 %s 메타 조회됨 (%d개 유형)", project_key, len(issuetype_statuses))

                return [TextContent(
                    type="text",
                    text=formatted_text
                )]

            if name == "complete_jira_issue":
                key = arguments.get("key", "").strip().upper()
                due_date = arguments.get("due_date", "").strip() or None

                if not key:
                    raise ValueError("key 파라미터가 필요합니다")

                result = await container.complete_jira_issue_use_case.execute(
                    key=key,
                    due_date=due_date,
                )
                logger.info(
                    "✅ Tool 실행 완료: %s 완료 처리 (%s → %s)",
                    result["key"], result["previous_status"], result["new_status"],
                )

                formatted_text = "# ✅ Jira 이슈 완료 처리 완료\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **이슈 키** | [{result['key']}]({result['url']}) |\n"
                formatted_text += f"| **제목** | {result['summary']} |\n"
                formatted_text += f"| **이전 상태** | {result['previous_status']} |\n"
                formatted_text += f"| **현재 상태** | {result['new_status']} |\n"
                formatted_text += f"| **종료일** | {result['due_date']} |\n"

                # Wiki 생성 여부를 사용자에게 확인 (Wiki 설정이 있는 경우만)
                if container.settings.wiki_base_url and container.settings.wiki_issue_root_page_id:
                    formatted_text += (
                        f"\n---\n\n"
                        f"Jira 이슈 **{result['key']}**가 완료 처리되었습니다. "
                        f"Wiki 이슈 정리 페이지를 생성할까요? (yes/no)"
                    )

                return [TextContent(type="text", text=formatted_text)]

            if name == "create_wiki_issue_page":
                issue_key = arguments.get("issue_key", "").strip().upper()
                issue_title = arguments.get("issue_title", "").strip()
                assignee = arguments.get("assignee", "").strip() or "미지정"
                resolution_date = arguments.get("resolution_date", "").strip() or ""
                priority = arguments.get("priority", "").strip() or "보통"
                commit_list = arguments.get("commit_list", "").strip()
                change_summary = arguments.get("change_summary", "").strip()
                project_name = arguments.get("project_name", "").strip()

                if not issue_key:
                    raise ValueError("issue_key 파라미터가 필요합니다")
                if not issue_title:
                    raise ValueError("issue_title 파라미터가 필요합니다")

                # Wiki 설정 확인
                wiki_error = _check_wiki_settings(container.settings)
                if wiki_error:
                    return wiki_error

                # 오케스트레이터로 워크플로우 A 시작 (승인 대기 상태로)
                session = await container.wiki_orchestrator.start_workflow_a(
                    issue_key=issue_key,
                    issue_title=issue_title,
                    assignee=assignee,
                    resolution_date=resolution_date,
                    priority=priority,
                    commit_list=commit_list,
                    change_summary=change_summary,
                    project_name=project_name,
                )
                logger.info(
                    "✅ Tool 실행 완료: Wiki 생성 세션 시작 (session=%s, state=%s)",
                    session.session_id, session.state.value,
                )

                # 프리뷰와 승인 정보 반환
                page_title = f"[{issue_key}] {issue_title}"
                preview_text = session.rendered_preview[:1000] if session.rendered_preview else ""

                formatted_text = "# 📄 Wiki 이슈 정리 페이지 프리뷰\n\n"
                formatted_text += _PREVIEW_WARNING
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **이슈 키** | {issue_key} |\n"
                formatted_text += f"| **페이지 제목** | {page_title} |\n"
                formatted_text += f"| **세션 ID** | {session.session_id} |\n"
                formatted_text += f"| **현재 상태** | {session.state.value} (승인 대기 중) |\n"

                # Jira 이슈 상세 정보 표시 (Workflow A)
                if session.jira_issues:
                    ji = session.jira_issues[0]
                    formatted_text += f"\n### 📌 Jira 이슈 상세 정보\n\n"
                    formatted_text += "| 항목 | 내용 |\n"
                    formatted_text += "|------|------|\n"
                    formatted_text += f"| **이슈키** | [{ji['key']}]({ji['url']}) |\n"
                    formatted_text += f"| **제목** | {ji['summary']} |\n"
                    formatted_text += f"| **상태** | {ji['status']} |\n"
                    formatted_text += f"| **유형** | {ji['issuetype']} |\n"
                    formatted_text += f"| **담당자** | {ji['assignee']} |\n"
                    wiki_date = get_wiki_date_for_issue(ji)
                    if wiki_date:
                        formatted_text += f"| **기준일** | {wiki_date} |\n"
                    if ji.get('description'):
                        desc_preview = ji['description'][:200]
                        formatted_text += f"\n**이슈 설명 (일부):**\n> {desc_preview}{'...' if len(ji['description']) > 200 else ''}\n"

                formatted_text += f"\n### 📋 변경 내용 요약\n\n{session.change_summary}\n"
                formatted_text += f"\n### 👁️ 프리뷰 (일부)\n\n```html\n{preview_text}\n...\n```\n"
                formatted_text += _format_approval_instructions(session)

                return [TextContent(type="text", text=formatted_text)]

            if name == "collect_branch_commits":
                branch_name = arguments.get("branch_name", "").strip()
                repository_path = arguments.get("repository_path", "").strip()

                if not branch_name:
                    raise ValueError("branch_name 파라미터가 필요합니다")

                # repository_path 결정 우선순위:
                # 1. 명시적 지정 → allowlist 검증 후 사용
                # 2. 미지정 → GIT_REPOSITORIES에서 브랜치 자동 탐지
                # 3. 등록된 저장소 없거나 못 찾으면 → 에러
                if repository_path:
                    path_error = _validate_repository_path(
                        repository_path, container.settings.git_repositories,
                    )
                    if path_error:
                        return [TextContent(type="text", text=path_error)]

                if not repository_path:
                    container = build_container()
                    git_repos = container.settings.git_repositories

                    if not git_repos:
                        error_text = "# ❌ repository_path 필요\n\n"
                        error_text += f"**브랜치:** {branch_name}\n\n"
                        error_text += "`repository_path`가 지정되지 않았고, `.env.local`에 `GIT_REPOSITORIES`도 설정되어 있지 않습니다.\n\n"
                        error_text += "**해결 방법:**\n"
                        error_text += "1. `repository_path` 파라미터에 git 저장소 경로를 직접 지정\n"
                        error_text += "2. `.env.local`에 `GIT_REPOSITORIES` 환경변수 설정\n"
                        return [TextContent(type="text", text=error_text)]

                    detected = await _detect_repository(branch_name, git_repos)
                    if len(detected) == 1:
                        repository_path, detected_name = detected[0]
                        logger.info("🔍 자동 탐지: '%s' → %s (%s)", branch_name, detected_name, repository_path)
                    elif len(detected) > 1:
                        return [TextContent(type="text", text=_format_ambiguity_message(branch_name, detected))]
                    else:
                        repos_list = "\n".join(f"  - {name}: {path}" for name, path in git_repos.items())
                        error_text = f"# ❌ 브랜치 자동 탐지 실패\n\n"
                        error_text += f"**브랜치:** {branch_name}\n\n"
                        error_text += f"등록된 저장소 {len(git_repos)}개에서 브랜치를 찾을 수 없습니다:\n\n"
                        error_text += f"```\n{repos_list}\n```\n\n"
                        error_text += "💡 `repository_path`를 직접 지정하거나, `.env.local`의 `GIT_REPOSITORIES`에 저장소를 추가하세요.\n"
                        return [TextContent(type="text", text=error_text)]

                logger.info("🔍 Git 작업 디렉토리: %s", repository_path)

                try:
                    # 지정된 디렉토리에서 작동하는 GitLocalAdapter 생성
                    diff_collector = GitLocalAdapter(working_dir=repository_path)
                    diff_result = await diff_collector.collect_by_branch(branch_name)

                    commits_lines = diff_result.commits_raw.splitlines() if diff_result.commits_raw else []
                    commit_count = len(commits_lines)
                    diff_size = len(diff_result.diff_raw)
                    estimated_tokens = diff_size // 4
                    include_diff = arguments.get("include_diff", False)

                    formatted_text = f"# 🔍 브랜치 커밋 수집 결과\n\n"
                    formatted_text += "| 항목 | 값 |\n"
                    formatted_text += "|------|-----|\n"
                    formatted_text += f"| **브랜치** | `{branch_name}` |\n"
                    formatted_text += f"| **작업 디렉토리** | `{repository_path}` |\n"
                    formatted_text += f"| **소스** | {diff_result.source} |\n"
                    formatted_text += f"| **커밋 수** | {commit_count}개 |\n"
                    formatted_text += f"| **Diff 크기** | {diff_size:,}자 (예상 ~{estimated_tokens:,} 토큰) |\n"
                    formatted_text += "\n---\n\n"

                    if commit_count > 0:
                        formatted_text += "## 📝 커밋 목록\n\n"
                        formatted_text += "```\n"
                        formatted_text += diff_result.commits_raw
                        formatted_text += "\n```\n\n"
                    else:
                        formatted_text += "⚠️ **고유 커밋 없음**\n\n"
                        formatted_text += "이 브랜치는 베이스 브랜치와 동일하거나 이미 머지되었습니다.\n\n"

                    # 변경 파일 통계 (항상 포함)
                    if diff_result.diff_stat:
                        formatted_text += "## 📊 변경 파일 통계\n\n"
                        formatted_text += f"```\n{diff_result.diff_stat}\n```\n\n"

                    # include_diff에 따른 분기
                    if include_diff and diff_result.diff_raw:
                        truncate_result = _smart_truncate_diff(diff_result.diff_raw, max_chars=container.settings.max_diff_chars)
                        formatted_text += "## 🔀 코드 변경사항 (Diff)\n\n"
                        formatted_text += f"```diff\n{truncate_result.diff_text}\n```\n\n"

                        # 스마트 필터링 리포트
                        formatted_text += "## 📊 스마트 필터링 결과\n\n"
                        formatted_text += "| 항목 | 값 |\n"
                        formatted_text += "|------|-----|\n"
                        formatted_text += f"| **전체 Diff 크기** | {truncate_result.original_size:,}자 |\n"
                        formatted_text += f"| **포함된 크기** | {truncate_result.truncated_size:,}자 |\n"
                        formatted_text += f"| **포함 파일 수** | {len(truncate_result.included_files)}개 |\n"
                        formatted_text += f"| **제외 파일 수** | {len(truncate_result.excluded_files)}개 |\n"

                        if truncate_result.excluded_files:
                            formatted_text += f"\n### ⚠️ 스마트 필터로 제외된 파일 ({len(truncate_result.excluded_files)}개)\n\n"
                            formatted_text += "우선순위가 낮아 제외된 파일 목록 (lock, 생성파일, 설정파일 등):\n\n"
                            for excluded_file in truncate_result.excluded_files:
                                formatted_text += f"- `{excluded_file}`\n"
                            formatted_text += "\n> 이 파일들은 change_summary 분석 대상에서 제외되었습니다.\n\n"
                    elif diff_size > 0:
                        formatted_text += "## 🤖 에이전트 필수 안내사항\n\n"
                        formatted_text += "**아래 내용을 반드시 사용자에게 안내하고 선택을 받으세요:**\n\n"
                        formatted_text += f"코드 변경사항이 **{diff_size:,}자** (예상 **~{estimated_tokens:,} 토큰**) 감지되었습니다.\n\n"
                        formatted_text += "| 방법 | 설명 | 토큰 소모 |\n"
                        formatted_text += "|------|------|----------|\n"
                        formatted_text += "| **방법 A** (빠름) | 커밋 메시지 기반으로 change_summary 작성 후 Wiki 생성 | 추가 토큰 없음 |\n"
                        formatted_text += f"| **방법 B** (정밀) | 코드 diff를 분석하여 고품질 change_summary 작성 후 Wiki 생성 | ~{estimated_tokens:,} 토큰 추가 |\n\n"
                        formatted_text += "> 사용자가 **방법 B**를 선택하면 `collect_branch_commits`를 `include_diff=true`로 다시 호출하세요.\n\n"

                    formatted_text += "---\n\n"
                    formatted_text += "## 📋 다음 단계\n\n"
                    formatted_text += "이 결과를 `create_wiki_page_with_content` 도구에 전달하여 Wiki 페이지를 생성할 수 있습니다.\n\n"
                    formatted_text += "**예시:**\n"
                    formatted_text += "```\n"
                    formatted_text += "create_wiki_page_with_content(\n"
                    formatted_text += f'    page_title="{branch_name}",\n'
                    if commits_lines:
                        formatted_text += f'    commit_list="{commits_lines[0][:50]}...",\n'
                    else:
                        formatted_text += '    commit_list="(커밋 없음)",\n'
                    formatted_text += '    change_summary="커밋 분석 후 작성한 변경 요약"\n'
                    formatted_text += ")\n"
                    formatted_text += "```\n"

                    # Jira 이슈키 자동 감지
                    all_text = f"{branch_name}\n{diff_result.commits_raw}"
                    detected_keys = extract_jira_issue_keys(all_text)

                    if detected_keys:
                        formatted_text += f"\n## 📌 감지된 Jira 이슈키\n\n"
                        formatted_text += f"**{', '.join(detected_keys)}**\n\n"
                        formatted_text += "Wiki 페이지 생성 시 이 Jira 이슈 내용을 포함할 수 있습니다.\n"
                        formatted_text += "`create_wiki_page_with_content` 호출 시 `jira_issue_keys` 파라미터로 전달하세요.\n\n"

                    logger.info(
                        "✅ Tool 실행 완료: 브랜치 커밋 수집 (%s) - %d개 커밋, 감지된 이슈키: %s",
                        branch_name, commit_count, detected_keys,
                    )

                    return [TextContent(type="text", text=formatted_text)]

                except Exception as e:
                    logger.exception("브랜치 커밋 수집 실패: %s", branch_name)
                    error_text = f"# ❌ 브랜치 커밋 수집 실패\n\n"
                    error_text += f"**브랜치:** {branch_name}\n\n"
                    error_text += f"**작업 디렉토리:** {repository_path}\n\n"
                    error_text += f"**에러:** {str(e)}\n\n"
                    error_text += "브랜치가 존재하지 않거나 로컬 git 저장소에 문제가 있을 수 있습니다.\n"
                    return [TextContent(type="text", text=error_text)]

            if name == "analyze_branch_changes":
                branch_name = arguments.get("branch_name", "").strip()
                repository_path = arguments.get("repository_path", "").strip()

                if not branch_name:
                    raise ValueError("branch_name 파라미터가 필요합니다")

                # repository_path allowlist 검증
                if repository_path:
                    path_error = _validate_repository_path(
                        repository_path, container.settings.git_repositories,
                    )
                    if path_error:
                        return [TextContent(type="text", text=path_error)]

                # repository_path 결정 (collect_branch_commits와 동일 로직)
                if not repository_path:
                    container = build_container()
                    git_repos = container.settings.git_repositories

                    if not git_repos:
                        error_text = "# ❌ repository_path 필요\n\n"
                        error_text += f"**브랜치:** {branch_name}\n\n"
                        error_text += "`repository_path`가 지정되지 않았고, `.env.local`에 `GIT_REPOSITORIES`도 설정되어 있지 않습니다.\n\n"
                        error_text += "**해결 방법:**\n"
                        error_text += "1. `repository_path` 파라미터에 git 저장소 경로를 직접 지정\n"
                        error_text += "2. `.env.local`에 `GIT_REPOSITORIES` 환경변수 설정\n"
                        return [TextContent(type="text", text=error_text)]

                    detected = await _detect_repository(branch_name, git_repos)
                    if len(detected) == 1:
                        repository_path, detected_name = detected[0]
                        logger.info("🔍 자동 탐지: '%s' → %s (%s)", branch_name, detected_name, repository_path)
                    elif len(detected) > 1:
                        return [TextContent(type="text", text=_format_ambiguity_message(branch_name, detected))]
                    else:
                        repos_list = "\n".join(f"  - {name}: {path}" for name, path in git_repos.items())
                        error_text = f"# ❌ 브랜치 자동 탐지 실패\n\n"
                        error_text += f"**브랜치:** {branch_name}\n\n"
                        error_text += f"등록된 저장소 {len(git_repos)}개에서 브랜치를 찾을 수 없습니다:\n\n"
                        error_text += f"```\n{repos_list}\n```\n\n"
                        error_text += "💡 `repository_path`를 직접 지정하거나, `.env.local`의 `GIT_REPOSITORIES`에 저장소를 추가하세요.\n"
                        return [TextContent(type="text", text=error_text)]

                logger.info("🔍 [분석] Git 작업 디렉토리: %s", repository_path)

                try:
                    diff_collector = GitLocalAdapter(working_dir=repository_path)
                    diff_result = await diff_collector.collect_by_branch(branch_name)

                    commits_lines = diff_result.commits_raw.splitlines() if diff_result.commits_raw else []
                    commit_count = len(commits_lines)
                    diff_size = len(diff_result.diff_raw)

                    formatted_text = "# 🔍 브랜치 변경사항 분석\n\n"
                    formatted_text += "| 항목 | 값 |\n"
                    formatted_text += "|------|-----|\n"
                    formatted_text += f"| **브랜치** | `{branch_name}` |\n"
                    formatted_text += f"| **작업 디렉토리** | `{repository_path}` |\n"
                    formatted_text += f"| **소스** | {diff_result.source} |\n"
                    formatted_text += f"| **커밋 수** | {commit_count}개 |\n"
                    formatted_text += f"| **Diff 크기** | {diff_size:,}자 |\n"
                    formatted_text += "\n---\n\n"

                    if commit_count > 0:
                        formatted_text += "## 📝 커밋 목록\n\n"
                        formatted_text += "```\n"
                        formatted_text += diff_result.commits_raw
                        formatted_text += "\n```\n\n"
                    else:
                        formatted_text += "⚠️ **고유 커밋 없음** — 베이스 브랜치와 동일하거나 이미 머지되었습니다.\n\n"

                    if diff_result.diff_stat:
                        formatted_text += "## 📊 변경 파일 통계\n\n"
                        formatted_text += f"```\n{diff_result.diff_stat}\n```\n\n"

                    # 스마트 필터링된 diff (항상 포함)
                    if diff_result.diff_raw:
                        truncate_result = _smart_truncate_diff(diff_result.diff_raw, max_chars=container.settings.max_diff_chars)
                        formatted_text += "## 🔀 코드 변경사항 (Diff)\n\n"
                        formatted_text += f"```diff\n{truncate_result.diff_text}\n```\n\n"

                        if truncate_result.excluded_files:
                            formatted_text += f"### 📊 스마트 필터링 결과\n\n"
                            formatted_text += f"전체 {truncate_result.original_size:,}자 중 {truncate_result.truncated_size:,}자 포함 "
                            formatted_text += f"({len(truncate_result.included_files)}개 파일 포함, {len(truncate_result.excluded_files)}개 제외)\n\n"
                            formatted_text += "**제외된 파일:**\n"
                            for excluded_file in truncate_result.excluded_files:
                                formatted_text += f"- `{excluded_file}`\n"
                            formatted_text += "\n"

                    # Jira 이슈키 자동 감지
                    all_text = f"{branch_name}\n{diff_result.commits_raw}"
                    detected_keys = extract_jira_issue_keys(all_text)
                    if detected_keys:
                        formatted_text += f"## 📌 감지된 Jira 이슈키\n\n**{', '.join(detected_keys)}**\n\n"

                    formatted_text += "---\n\n"
                    formatted_text += "위 데이터를 바탕으로 사용자의 질문에 답변하세요.\n"

                    logger.info(
                        "✅ Tool 실행 완료: 브랜치 분석 (%s) - %d개 커밋, diff %d자",
                        branch_name, commit_count, diff_size,
                    )

                    return [TextContent(type="text", text=formatted_text)]

                except Exception as e:
                    logger.exception("브랜치 분석 실패: %s", branch_name)
                    error_text = f"# ❌ 브랜치 분석 실패\n\n"
                    error_text += f"**브랜치:** {branch_name}\n\n"
                    error_text += f"**작업 디렉토리:** {repository_path}\n\n"
                    error_text += f"**에러:** {str(e)}\n\n"
                    error_text += "브랜치가 존재하지 않거나 로컬 git 저장소에 문제가 있을 수 있습니다.\n"
                    return [TextContent(type="text", text=error_text)]

            if name == "create_wiki_page_with_content":
                page_title = arguments.get("page_title", "").strip()
                commit_list = arguments.get("commit_list", "").strip()
                input_type = arguments.get("input_type", "브랜치명").strip()
                input_value = arguments.get("input_value", "").strip()
                base_date = arguments.get("base_date", "").strip()
                change_summary = arguments.get("change_summary", "").strip()
                jira_issue_keys = arguments.get("jira_issue_keys", "").strip()
                diff_stat = arguments.get("diff_stat", "").strip()
                project_name = arguments.get("project_name", "").strip()

                if not page_title:
                    raise ValueError("page_title 파라미터가 필요합니다")
                if not commit_list:
                    raise ValueError("commit_list 파라미터가 필요합니다")

                # Wiki 설정 확인
                wiki_error = _check_wiki_settings(container.settings)
                if wiki_error:
                    return wiki_error

                # 오케스트레이터로 워크플로우 B 시작 (승인 대기 상태로)
                session = await container.wiki_orchestrator.start_workflow_b(
                    page_title=page_title,
                    commit_list=commit_list,
                    input_type=input_type,
                    input_value=input_value,
                    base_date=base_date,
                    change_summary=change_summary,
                    jira_issue_keys=jira_issue_keys,
                    diff_stat=diff_stat,
                    project_name=project_name,
                )
                logger.info(
                    "✅ Tool 실행 완료: Wiki 생성 세션 시작 (session=%s, state=%s)",
                    session.session_id, session.state.value,
                )

                # 프리뷰와 승인 정보 반환
                preview_text = session.rendered_preview[:1000] if session.rendered_preview else ""

                formatted_text = "# 📄 Wiki 페이지 프리뷰\n\n"
                formatted_text += _PREVIEW_WARNING
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **페이지 제목** | {page_title} |\n"
                formatted_text += f"| **입력 유형** | {input_type} |\n"
                formatted_text += f"| **세션 ID** | {session.session_id} |\n"
                formatted_text += f"| **현재 상태** | {session.state.value} (승인 대기 중) |\n"

                # Jira 이슈 정보 표시 (Workflow B)
                if session.jira_issues:
                    formatted_text += f"\n### 📌 포함된 Jira 이슈 ({len(session.jira_issues)}건)\n\n"
                    formatted_text += "| 이슈키 | 제목 | 상태 | 담당자 | 기준일 |\n"
                    formatted_text += "|--------|------|------|--------|--------|\n"
                    for ji in session.jira_issues:
                        wiki_date = get_wiki_date_for_issue(ji)
                        formatted_text += f"| [{ji['key']}]({ji['url']}) | {ji['summary']} | {ji['status']} | {ji['assignee']} | {wiki_date or '-'} |\n"
                    formatted_text += f"\n> BNFDEV: 종료일(customfield_10833) 기준, BNFMT: 생성일(created) 기준\n"

                formatted_text += f"\n### 📋 변경 내용 요약\n\n{session.change_summary}\n"
                formatted_text += f"\n### 👁️ 프리뷰 (일부)\n\n```html\n{preview_text}\n...\n```\n"
                formatted_text += _format_approval_instructions(session)

                return [TextContent(type="text", text=formatted_text)]

            if name == "get_wiki_page":
                page_id = arguments.get("page_id", "").strip()
                page_title = arguments.get("page_title", "").strip()
                space_key = arguments.get("space_key", "").strip()

                if not page_id and not page_title:
                    raise ValueError("page_id 또는 page_title 중 하나를 지정해야 합니다")

                wiki_error = _check_wiki_base_url(container.settings)
                if wiki_error:
                    return wiki_error

                adapter = container.wiki_adapter

                if page_id:
                    page = await adapter.get_page_with_content(page_id)
                else:
                    resolved_space = space_key or container.settings.wiki_issue_space_key
                    found = await adapter.search_page_by_title(
                        title=page_title,
                        space_key=resolved_space,
                    )
                    if found is None:
                        return [TextContent(
                            type="text",
                            text=f"# ⚠️ 페이지를 찾을 수 없습니다\n\n"
                                 f"**검색 제목:** {page_title}\n"
                                 f"**Space:** {resolved_space}\n\n"
                                 f"해당 제목의 페이지가 존재하지 않거나 접근 권한이 없습니다."
                        )]
                    page = await adapter.get_page_with_content(found.id)

                logger.info("✅ Tool 실행 완료: Wiki 페이지 조회 (id=%s, title=%s)", page.id, page.title)

                formatted_text = "# Wiki 페이지 조회 결과\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **페이지 ID** | {page.id} |\n"
                formatted_text += f"| **제목** | {page.title} |\n"
                formatted_text += f"| **Space** | {page.space_key} |\n"
                formatted_text += f"| **URL** | {page.url} |\n"
                formatted_text += f"| **버전** | {page.version} |\n"
                formatted_text += f"\n### 페이지 내용 (Confluence Storage Format)\n\n{page.body}\n"

                return [TextContent(type="text", text=formatted_text)]

            if name == "update_wiki_page":
                page_id = arguments.get("page_id", "").strip()
                page_title = arguments.get("page_title", "").strip()
                body = arguments.get("body", "").strip()
                space_key = arguments.get("space_key", "").strip()

                if not page_id and not page_title:
                    raise ValueError("page_id 또는 page_title 중 하나를 지정해야 합니다")
                if not body:
                    raise ValueError("body 파라미터가 필요합니다")

                wiki_error = _check_wiki_base_url(container.settings)
                if wiki_error:
                    return wiki_error

                session = await container.wiki_orchestrator.start_update_workflow(
                    body=body,
                    page_id=page_id,
                    page_title=page_title,
                    space_key=space_key,
                )
                logger.info(
                    "Tool 실행 완료: Wiki 페이지 수정 세션 시작 (session=%s, page=%s)",
                    session.session_id, session.update_target_page_id,
                )

                formatted_text = "# Wiki 페이지 수정 프리뷰\n\n"
                formatted_text += _PREVIEW_WARNING
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **페이지 ID** | {session.update_target_page_id} |\n"
                formatted_text += f"| **제목** | {session.page_title} |\n"
                formatted_text += f"| **현재 버전** | {session.update_target_version} |\n"
                formatted_text += f"| **세션 ID** | {session.session_id} |\n"
                formatted_text += f"| **현재 상태** | {session.state.value} (승인 대기 중) |\n"

                content_preview = session.content_raw[:2000] if session.content_raw else ""
                truncated = "..." if len(session.content_raw) > 2000 else ""
                formatted_text += f"\n### 수정될 내용 프리뷰\n\n{content_preview}{truncated}\n\n---\n"
                formatted_text += _format_approval_instructions(session)

                return [TextContent(type="text", text=formatted_text)]

            if name == "create_wiki_custom_page":
                parent_page_id = arguments.get("parent_page_id", "").strip()
                parent_page_title = arguments.get("parent_page_title", "").strip()
                page_title = arguments.get("page_title", "").strip()
                content = arguments.get("content", "").strip()
                space_key = arguments.get("space_key", "").strip()

                if not parent_page_id and not parent_page_title:
                    raise ValueError("parent_page_id 또는 parent_page_title 중 하나를 지정해야 합니다")
                if not page_title:
                    raise ValueError("page_title 파라미터가 필요합니다")
                if not content:
                    raise ValueError("content 파라미터가 필요합니다")

                # Wiki 설정 확인
                wiki_error = _check_wiki_settings(container.settings)
                if wiki_error:
                    return wiki_error

                # 오케스트레이터로 워크플로우 C 시작 (승인 대기 상태로)
                session = await container.wiki_orchestrator.start_workflow_c(
                    page_title=page_title,
                    content=content,
                    parent_page_id=parent_page_id,
                    parent_page_title=parent_page_title,
                    space_key=space_key,
                )
                logger.info(
                    "Tool 실행 완료: Wiki 커스텀 페이지 세션 시작 (session=%s, state=%s)",
                    session.session_id, session.state.value,
                )

                # 프리뷰와 승인 정보 반환
                parent_info = parent_page_title or session.parent_page_id

                formatted_text = "# Wiki 커스텀 페이지 프리뷰\n\n"
                formatted_text += _PREVIEW_WARNING
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **페이지 제목** | {page_title} |\n"
                formatted_text += f"| **부모 페이지** | {parent_info} (ID: {session.parent_page_id}) |\n"
                if space_key:
                    formatted_text += f"| **Space Key** | {space_key} |\n"
                formatted_text += f"| **세션 ID** | {session.session_id} |\n"
                formatted_text += f"| **현재 상태** | {session.state.value} (승인 대기 중) |\n"
                # 원본 마크다운 콘텐츠를 프리뷰로 표시 (Claude가 렌더링 가능)
                content_preview = session.content_raw[:2000] if session.content_raw else ""
                truncated = "..." if len(session.content_raw) > 2000 else ""
                formatted_text += f"\n### 콘텐츠 프리뷰\n\n{content_preview}{truncated}\n\n---\n"
                formatted_text += _format_approval_instructions(session)

                return [TextContent(type="text", text=formatted_text)]

            if name == "transition_jira_issue":
                key = arguments.get("key", "").strip().upper()
                target_status = arguments.get("target_status", "").strip()

                if not key:
                    raise ValueError("key 파라미터가 필요합니다")
                if not target_status:
                    raise ValueError("target_status 파라미터가 필요합니다")

                result = await container.transition_jira_issue_use_case.execute(
                    key=key,
                    target_status=target_status,
                )
                logger.info(
                    "✅ Tool 실행 완료: %s 상태 전환 (%s → %s)",
                    result["key"], result["previous_status"], result["new_status"],
                )

                formatted_text = "# 🔄 Jira 이슈 상태 전환 완료\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **이슈 키** | [{result['key']}]({result['url']}) |\n"
                formatted_text += f"| **제목** | {result['summary']} |\n"
                formatted_text += f"| **이전 상태** | {result['previous_status']} |\n"
                formatted_text += f"| **현재 상태** | {result['new_status']} |\n"

                return [TextContent(type="text", text=formatted_text)]

            if name == "reload_wiki_templates":
                result = await container.reload_templates_use_case.execute()
                logger.info("Tool 실행 완료: 템플릿 리로드 (%d개 워크플로우)", result["workflow_count"])

                formatted_text = "# Wiki 템플릿 리로드 완료\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **워크플로우 수** | {result['workflow_count']}개 |\n"
                formatted_text += f"| **워크플로우** | {', '.join(result['workflow_names'])} |\n"
                formatted_text += f"| **파일 경로** | {container.settings.template_yaml_path} |\n"

                return [TextContent(type="text", text=formatted_text)]

            if name == "get_wiki_generation_status":
                session_id = arguments.get("session_id", "").strip()
                if not session_id:
                    raise ValueError("session_id 파라미터가 필요합니다")

                status = container.wiki_orchestrator.get_status(session_id)
                if status is None:
                    return [TextContent(
                        type="text",
                        text=f"# 세션을 찾을 수 없습니다\n\n**세션 ID:** {session_id}\n\n만료되었거나 존재하지 않는 세션입니다."
                    )]

                formatted_text = "# Wiki 생성 세션 상태\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **세션 ID** | {status['session_id']} |\n"
                formatted_text += f"| **워크플로우** | {status['workflow_type']} |\n"
                formatted_text += f"| **상태** | {status['state']} |\n"
                formatted_text += f"| **페이지 제목** | {status['page_title']} |\n"
                formatted_text += f"| **생성 시각** | {status['created_at']} |\n"
                formatted_text += f"| **갱신 시각** | {status['updated_at']} |\n"

                if status.get("issue_key"):
                    formatted_text += f"| **이슈 키** | {status['issue_key']} |\n"
                if status.get("approval_token"):
                    formatted_text += f"| **승인 토큰** | {status['approval_token']} |\n"
                if status.get("preview"):
                    formatted_text += f"\n### 프리뷰 (일부)\n\n```html\n{status['preview']}\n```\n"

                return [TextContent(type="text", text=formatted_text)]

            if name == "approve_wiki_generation":
                session_id = arguments.get("session_id", "").strip()
                approval_token = arguments.get("approval_token", "").strip()

                if not session_id:
                    raise ValueError("session_id 파라미터가 필요합니다")
                if not approval_token:
                    raise ValueError("approval_token 파라미터가 필요합니다")

                # 세션 워크플로우 유형에 따라 Wiki 설정 검증 수준 결정
                status = container.wiki_orchestrator.get_status(session_id)
                is_update = status and status["workflow_type"] == "update_page"

                if is_update:
                    wiki_error = _check_wiki_base_url(container.settings)
                else:
                    wiki_error = _check_wiki_settings(container.settings)
                if wiki_error:
                    return wiki_error

                result = await container.wiki_orchestrator.approve(
                    session_id=session_id,
                    approval_token=approval_token,
                )
                logger.info("Tool 실행 완료: Wiki 페이지 승인 완료 (%s)", result.url)

                if is_update:
                    formatted_text = "# Wiki 페이지 수정 완료\n\n"
                elif result.was_updated:
                    formatted_text = "# Wiki 페이지 업데이트 완료 (기존 페이지에 프로젝트 섹션 추가)\n\n"
                else:
                    formatted_text = "# Wiki 페이지 생성 완료 (승인)\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **페이지 제목** | {result.title} |\n"
                formatted_text += f"| **페이지 ID** | {result.page_id} |\n"
                formatted_text += f"| **페이지 URL** | {result.url} |\n"
                if is_update:
                    formatted_text += f"| **동작** | 페이지 내용 수정 |\n"
                elif result.was_updated:
                    formatted_text += f"| **동작** | 기존 페이지에 프로젝트 섹션 추가 (업데이트) |\n"

                return [TextContent(type="text", text=formatted_text)]

            if name == "create_jira_filter":
                name_param = arguments.get("name", "").strip()
                jql_param = arguments.get("jql", "").strip()

                missing = []
                if not name_param:
                    missing.append("필터 이름(name)")
                if not jql_param:
                    missing.append("JQL 쿼리(jql)")

                if missing:
                    missing_str = ", ".join(missing)
                    return [TextContent(
                        type="text",
                        text=f"# ⚠️ 입력값이 필요합니다\n\n다음 항목을 입력해 주세요:\n\n" +
                             "".join(f"- **{m}**\n" for m in missing) +
                             "\n**예시:**\n```\n필터 이름: 내 진행중 이슈\nJQL: assignee = currentUser() AND status = \"진행중(개발)\"\n```"
                    )]

                result = await container.create_jira_filter_use_case.execute(
                    name=name_param,
                    jql=jql_param,
                )
                logger.info("✅ Tool 실행 완료: 필터 '%s' 생성됨 (id=%s)", result["name"], result["id"])

                formatted_text = "# ✅ Jira 필터 생성 완료\n\n"
                formatted_text += "| 항목 | 내용 |\n"
                formatted_text += "|------|------|\n"
                formatted_text += f"| **필터 ID** | {result['id']} |\n"
                formatted_text += f"| **필터 이름** | {result['name']} |\n"
                formatted_text += f"| **JQL** | `{result['jql']}` |\n"
                formatted_text += f"| **링크** | {result['url']} |\n"

                return [TextContent(
                    type="text",
                    text=formatted_text
                )]

            raise ValueError(f"알 수 없는 tool: {name}")

        except Exception as e:
            logger.error("=" * 60)
            logger.error("❌ Tool 실행 실패!")
            logger.error("Tool: %s", name)
            logger.error("오류 타입: %s", type(e).__name__)
            logger.error("오류 메시지: %s", str(e))
            logger.error("=" * 60)
            traceback.print_exc(file=sys.stderr)

            # MCP 표준 형식으로 에러 메시지 반환
            error_message = f"""# ❌ 오류 발생

**Tool:** {name}
**오류 타입:** {type(e).__name__}
**오류 메시지:** {str(e)}

자세한 내용은 서버 로그를 확인하세요.
"""
            return [TextContent(
                type="text",
                text=error_message
            )]

    @app.list_tools()
    async def list_tools():
        from mcp.types import Tool

        return [
            Tool(
                name="get_jira_issue",
                description="""특정 Jira 이슈를 key(ID)로 조회합니다.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Jira 이슈 키 (예: 'BNFDEV-2365', 'BNFMT-343')",
                        }
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="get_jira_issues",
                description="""Jira에서 현재 사용자에게 할당된 이슈를 조회합니다.

**기본 동작**: 파라미터 없이 호출하면 모든 프로젝트의 모든 상태 이슈를 조회합니다.

**영어 상태값 자동 변환** (편리 기능):
- "Done" → 완료 관련 모든 상태 (완료, 완료(개발), 완료(설계), DONE(BNF), 개발완료(BNF), 배포완료(BNF), 검수완료(BNF), 답변완료(BNF), 기획/설계 완료(BNF))
- "In Progress" → 진행중 관련 모든 상태 (진행중(개발), 진행중(설계), 처리중(BNF), 개발(BNF))
- "To Do" / "Open" → 할일 관련 모든 상태 (할일, 할일(개발), 할일(설계), 할일(BNF), 개발접수(BNF))
- "Pending" → 보류 관련 상태 (보류(BNF), 패치대기(BNF))
- "In Review" → 검수 관련 상태 (설계검수(BNF), 운영검수(BNF))

**사용 가능한 한글 상태값**:
- 일반: 할일, 완료, 기획진행
- 개발: 할일(개발), 진행중(개발), 완료(개발)
- 설계: 할일(설계), 진행중(설계), 완료(설계)
- BNF: 기획/설계(BNF), 개발(BNF), 보류(BNF), 기획/설계 완료(BNF), 설계검수(BNF), 개발완료(BNF), 패치대기(BNF), 운영검수(BNF), 검수완료(BNF), DONE(BNF), 배포완료(BNF), 할일(BNF), 개발접수(BNF), 처리중(BNF), 답변완료(BNF)""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "statuses": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "조회할 이슈 상태 목록 (한글). 예: ['완료', '진행중(개발)', 'DONE(BNF)']. **이 파라미터를 생략하면 모든 상태 조회**",
                        },
                        "project_key": {
                            "type": "string",
                            "description": "특정 프로젝트로 필터링 (예: 'BNFDEV', 'BNFMT'). **이 파라미터를 생략하면 전체 프로젝트 조회**",
                        },
                    },
                },
            ),
            Tool(
                name="get_jira_project_meta",
                description="""Jira 프로젝트의 이슈 유형과 각 유형별 상태값을 조회합니다.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_key": {
                            "type": "string",
                            "description": "Jira 프로젝트 키 (예: 'BNFDEV', 'BNFMT')",
                        }
                    },
                    "required": ["project_key"],
                },
            ),
            Tool(
                name="complete_jira_issue",
                description="""Jira 이슈를 완료 처리합니다.

이슈 프로젝트와 유형을 자동으로 확인하여 적절한 완료 상태로 전환하고,
이슈 키 프리픽스에 따라 종료일을 설정합니다.

**종료일 처리 규칙 (이슈 키 프리픽스별):**
- **BNFDEV-***: customfield_10833 필드에 종료일 설정
- **BNFMT-***: 종료일 설정 안 함
- **기타**: duedate 필드에 종료일 설정

**완료 상태 우선순위 (이슈에서 전환 가능한 상태 기준):**
- 배포완료(BNF) → DONE(BNF) → 검수완료(BNF) → 개발완료(BNF) → 답변완료(BNF) → 완료(개발) → 완료""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "완료 처리할 Jira 이슈 키 (예: 'BNFDEV-1234', 'BNFMT-567')",
                        },
                        "due_date": {
                            "type": "string",
                            "description": "종료일 (YYYY-MM-DD 형식). 생략하면 오늘 날짜가 기본값으로 사용됩니다",
                        },
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="transition_jira_issue",
                description="""Jira 이슈 상태를 원하는 값으로 전환합니다.

해당 이슈에서 실제로 전환 가능한 상태 목록 안에서만 동작합니다.

**BNFDEV 프로젝트 주요 상태값:**
할일 / 기획/설계(BNF) / 개발(BNF) / 기획/설계 완료(BNF) / 설계검수(BNF) /
개발완료(BNF) / 패치대기(BNF) / 운영검수(BNF) / 검수완료(BNF) / DONE(BNF) /
배포완료(BNF) / 보류(BNF) / 할일(개발) / 진행중(개발) / 완료(개발)

**BNFMT 프로젝트 주요 상태값:**
할일(BNF) / 개발접수(BNF) / 처리중(BNF) / 답변완료(BNF) /
개발(BNF) / 기획/설계(BNF) / 운영검수(BNF) / 배포완료(BNF)""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "상태를 변경할 Jira 이슈 키 (예: 'BNFDEV-1234', 'BNFMT-567')",
                        },
                        "target_status": {
                            "type": "string",
                            "description": "전환할 목표 상태명 (예: '진행중(개발)', '개발(BNF)', '운영검수(BNF)', '보류(BNF)')",
                        },
                    },
                    "required": ["key", "target_status"],
                },
            ),
            Tool(
                name="create_jira_filter",
                description="""Jira에 새 필터를 이름과 JQL로 생성합니다.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "생성할 Jira 필터 이름 (예: '내 진행중 이슈')",
                        },
                        "jql": {
                            "type": "string",
                            "description": "필터에 사용할 JQL 쿼리 (예: 'assignee = currentUser() AND status = \"진행중(개발)\"')",
                        },
                    },
                    "required": ["name", "jql"],
                },
            ),
            Tool(
                name="create_wiki_issue_page",
                description="""Confluence Wiki에 Jira 이슈 정리 페이지 생성을 준비합니다.

⚠️ 즉시 생성하지 않음. 프리뷰 반환 후 approve_wiki_generation으로 승인 필요.

commit_list 미제공 시 자동 수집됨. 직접 수집 시 collect_branch_commits 사용 권장.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "issue_key": {
                            "type": "string",
                            "description": "Jira 이슈키 (예: 'BNFDEV-1234')",
                        },
                        "issue_title": {
                            "type": "string",
                            "description": "Jira 이슈 제목",
                        },
                        "commit_list": {
                            "type": "string",
                            "description": "커밋 목록 (줄바꿈 구분 문자열, GitLab MCP 또는 git log 결과. 예: 'abc1234 fix: 버그 수정\\ndef5678 feat: 기능 추가'). 미제공 시 로컬 git에서 자동 조회 시도",
                        },
                        "change_summary": {
                            "type": "string",
                            "description": "변경 내용 요약 (코드 diff 분석 결과). 생략 시 커밋 메시지에서 자동 생성",
                        },
                        "assignee": {
                            "type": "string",
                            "description": "담당자 이름 (생략 시 '미지정')",
                        },
                        "resolution_date": {
                            "type": "string",
                            "description": "이슈 완료일 (YYYY-MM-DD 형식, 생략 시 오늘 날짜)",
                        },
                        "priority": {
                            "type": "string",
                            "description": "우선순위 (생략 시 '보통')",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "프로젝트명 (예: 'oper-back-office', 'supplier-back-office'). "
                                           "동일 이슈가 여러 프로젝트에 걸칠 때 기존 페이지에 프로젝트별 섹션으로 추가됩니다. "
                                           "생략 시 기존처럼 동작 (중복 페이지 에러)",
                        },
                    },
                    "required": ["issue_key", "issue_title"],
                },
            ),
            Tool(
                name="collect_branch_commits",
                description="""브랜치의 고유 커밋 목록과 변경사항(diff)을 수집합니다. **Wiki 페이지 생성 전 커밋 수집용.**

git 명령 대신 이 도구를 사용하세요. 올바른 베이스 브랜치를 자동 탐지합니다.
(우선순위: dev → origin/dev → develop → origin/develop → main → master)

repository_path 미지정 시 GIT_REPOSITORIES에 등록된 저장소에서 자동 탐지.
include_diff 기본값 false. 응답의 안내를 따라 필요시 true로 재호출.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "branch_name": {
                            "type": "string",
                            "description": "조회할 브랜치명 (예: 'dev_rf', 'dev_BNFDEV-1234')",
                        },
                        "repository_path": {
                            "type": "string",
                            "description": "git 저장소 절대 경로 (선택, 생략 시 GIT_REPOSITORIES 환경변수에 등록된 저장소에서 브랜치를 자동 탐지)",
                        },
                        "include_diff": {
                            "type": "boolean",
                            "description": "true: 스마트 필터링된 diff 원본 포함 (토큰 소모 증가, change_summary 작성용). "
                                           "기본값 false: diff 통계와 크기/토큰 안내만 표시",
                        },
                    },
                    "required": ["branch_name"],
                },
            ),
            Tool(
                name="analyze_branch_changes",
                description="""브랜치의 변경사항을 분석하여 보고합니다. **범용 변경사항 분석/질문 답변용.**

collect_branch_commits는 Wiki 생성 전용, 이 도구는 "뭐 바뀌었어?", "변경사항 요약해줘" 등 범용 분석용.

repository_path 미지정 시 GIT_REPOSITORIES에서 자동 탐지.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "branch_name": {
                            "type": "string",
                            "description": "분석할 브랜치명 (예: 'dev_rf', 'dev_BNFDEV-1234')",
                        },
                        "repository_path": {
                            "type": "string",
                            "description": "git 저장소 절대 경로 (선택, 생략 시 GIT_REPOSITORIES에서 자동 탐지)",
                        },
                    },
                    "required": ["branch_name"],
                },
            ),
            Tool(
                name="create_wiki_page_with_content",
                description="""외부에서 수집한 커밋 내용으로 Confluence Wiki 페이지 생성을 준비합니다.

⚠️ 즉시 생성하지 않음. 프리뷰 반환 후 approve_wiki_generation으로 승인 필요.

커밋 수집은 collect_branch_commits 도구 사용 권장 (베이스 브랜치 자동 탐지).""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_title": {
                            "type": "string",
                            "description": "Wiki 페이지 제목 (예: 'dev_rf', 'dev_BNFDEV-1234')",
                        },
                        "commit_list": {
                            "type": "string",
                            "description": "커밋 목록 (줄바꿈으로 구분된 문자열, 예: 'abc1234 fix: 버그 수정\\ndef5678 feat: 기능 추가')",
                        },
                        "input_type": {
                            "type": "string",
                            "description": "입력 유형 설명 (기본값: '브랜치명', 예: 'GitLab MR', '커밋 범위')",
                        },
                        "input_value": {
                            "type": "string",
                            "description": "브랜치명, MR 번호 등 원본 식별값",
                        },
                        "base_date": {
                            "type": "string",
                            "description": "기준 날짜 (YYYY-MM-DD 형식, 생략 시 오늘 날짜)",
                        },
                        "change_summary": {
                            "type": "string",
                            "description": "변경 내용 요약 (생략 시 커밋 메시지에서 자동 생성)",
                        },
                        "jira_issue_keys": {
                            "type": "string",
                            "description": "관련 Jira 이슈 키 목록 (콤마 구분, 예: 'BNFDEV-1234,BNFDEV-1235'). "
                                           "포함 시 Jira 이슈 내용이 Wiki에 추가되고, 프로젝트별 날짜(BNFDEV:종료일, BNFMT:생성일)가 Wiki 경로(년/월)에 반영됩니다. "
                                           "생략 시 Jira 이슈 내용 없이 진행",
                        },
                        "diff_stat": {
                            "type": "string",
                            "description": "git diff --stat 결과 (변경 파일 통계). collect_branch_commits에서 받은 값을 전달하면 Wiki '변경 파일 목록' 섹션에 포함",
                        },
                        "project_name": {
                            "type": "string",
                            "description": "프로젝트명 (예: 'oper-back-office', 'supplier-back-office'). "
                                           "동일 페이지 제목이 이미 존재하면 프로젝트별 섹션으로 추가됩니다. "
                                           "생략 시 기존처럼 동작 (중복 페이지 에러)",
                        },
                    },
                    "required": ["page_title", "commit_list"],
                },
            ),
            Tool(
                name="create_wiki_custom_page",
                description="""특정 부모 페이지 아래에 자유 형식 콘텐츠로 Confluence Wiki 페이지를 생성합니다.

⚠️ 즉시 생성하지 않음. 프리뷰 반환 후 approve_wiki_generation으로 승인 필요.

연/월 계층 구조 없이 지정한 부모 페이지 바로 아래에 생성.
마크다운 및 일반 텍스트를 자동으로 Confluence HTML로 변환.
parent_page_id 또는 parent_page_title 중 하나 필수 (둘 다 지정 시 ID 우선).""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "parent_page_id": {
                            "type": "string",
                            "description": "부모 페이지 ID (예: '339090255'). parent_page_title과 둘 중 하나만 지정하면 됩니다. 둘 다 지정 시 ID가 우선",
                        },
                        "parent_page_title": {
                            "type": "string",
                            "description": "부모 페이지 제목 (예: 'AI'). Space 내에서 제목으로 페이지를 검색합니다. parent_page_id와 둘 중 하나만 지정하면 됩니다",
                        },
                        "page_title": {
                            "type": "string",
                            "description": "생성할 Wiki 페이지 제목",
                        },
                        "content": {
                            "type": "string",
                            "description": "페이지 내용 (마크다운 또는 텍스트). 마크다운 형식이 자동으로 Confluence HTML로 변환됩니다",
                        },
                        "space_key": {
                            "type": "string",
                            "description": "Confluence Space 키 (생략 시 WIKI_ISSUE_SPACE_KEY 환경변수 기본값 사용)",
                        },
                    },
                    "required": ["page_title", "content"],
                },
            ),
            Tool(
                name="get_wiki_page",
                description="""Confluence Wiki 페이지를 조회하여 내용을 반환합니다.

page_id 또는 page_title 중 하나 필수 (둘 다 지정 시 page_id 우선).
페이지 본문은 Confluence Storage Format (HTML)으로 반환됩니다.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_id": {
                            "type": "string",
                            "description": "Confluence 페이지 ID (예: '339090255'). page_title과 둘 중 하나만 지정하면 됩니다",
                        },
                        "page_title": {
                            "type": "string",
                            "description": "페이지 제목 (예: '회의록'). Space 내에서 정확한 제목으로 검색합니다. page_id와 둘 중 하나만 지정하면 됩니다",
                        },
                        "space_key": {
                            "type": "string",
                            "description": "Confluence Space 키 (page_title 검색 시 사용, 생략 시 WIKI_ISSUE_SPACE_KEY 기본값)",
                        },
                    },
                },
            ),
            Tool(
                name="update_wiki_page",
                description="""기존 Confluence Wiki 페이지의 내용을 수정합니다.

⚠️ 즉시 수정하지 않음. 프리뷰 반환 후 approve_wiki_generation으로 승인 필요.

수정 전 반드시 get_wiki_page로 현재 내용을 확인하세요.
body에는 수정된 전체 페이지 본문 (Confluence Storage Format HTML)을 전달합니다.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page_id": {
                            "type": "string",
                            "description": "수정할 페이지 ID (예: '339090255'). page_title과 둘 중 하나만 지정하면 됩니다",
                        },
                        "page_title": {
                            "type": "string",
                            "description": "수정할 페이지 제목. Space 내에서 정확한 제목으로 검색합니다. page_id와 둘 중 하나만 지정하면 됩니다",
                        },
                        "body": {
                            "type": "string",
                            "description": "수정된 전체 페이지 본문 (Confluence Storage Format HTML). get_wiki_page로 조회한 내용을 수정한 결과",
                        },
                        "space_key": {
                            "type": "string",
                            "description": "Confluence Space 키 (page_title 검색 시 사용, 생략 시 WIKI_ISSUE_SPACE_KEY 기본값)",
                        },
                    },
                    "required": ["body"],
                },
            ),
            Tool(
                name="reload_wiki_templates",
                description="""Wiki 템플릿 YAML 파일을 핫 리로드합니다. 서버 재시작 없이 config/wiki_templates.yaml 변경 반영.""",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="get_wiki_generation_status",
                description="""Wiki 생성 세션의 현재 상태, 프리뷰, 승인 토큰을 조회합니다.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Wiki 생성 세션 ID",
                        },
                    },
                    "required": ["session_id"],
                },
            ),
            Tool(
                name="approve_wiki_generation",
                description="""Wiki 생성을 승인하여 실제 Confluence 페이지를 생성/수정합니다. WAIT_APPROVAL 상태일 때만 동작.""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Wiki 생성 세션 ID",
                        },
                        "approval_token": {
                            "type": "string",
                            "description": "승인 토큰 (get_wiki_generation_status 응답에서 확인)",
                        },
                    },
                    "required": ["session_id", "approval_token"],
                },
            ),
        ]
