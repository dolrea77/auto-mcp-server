import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

# 승인 토큰 유효 시간 (분)
APPROVAL_TOKEN_TTL_MINUTES = 30

# 하드코딩된 Jira 이슈키 패턴 (BNFDEV-숫자, BNFMT-숫자)
_JIRA_ISSUE_KEY_PATTERN = re.compile(r"\b(?:BNFDEV|BNFMT)-\d+\b")


def extract_jira_issue_keys(text: str) -> list[str]:
    """텍스트에서 BNFDEV/BNFMT 이슈키를 추출합니다. 중복 제거, 순서 보존."""
    if not text:
        return []
    keys = [m.group() for m in _JIRA_ISSUE_KEY_PATTERN.finditer(text)]
    return list(dict.fromkeys(keys))


def get_wiki_date_for_issue(issue_data: dict) -> str:
    """프로젝트별 Wiki 경로 날짜를 결정합니다.
    - BNFDEV: customfield_10833 (종료일) 기준
    - BNFMT: created (생성일) 기준
    - 그 외: 빈 문자열
    """
    key = issue_data.get("key", "")
    if key.startswith("BNFDEV"):
        date_val = issue_data.get("custom_end_date", "")
        if date_val:
            return date_val[:10]
    elif key.startswith("BNFMT"):
        date_val = issue_data.get("created", "")
        if date_val:
            return date_val[:10]
    # 새 프로젝트 추가 시 여기에 elif 블록 추가(위키 페이지 구조에 사용되는 일자 기준일 설정)
    return ""


class WorkflowType(Enum):
    WORKFLOW_A = "workflow_a"
    WORKFLOW_B = "workflow_b"
    WORKFLOW_C = "workflow_c"
    UPDATE_PAGE = "update_page"


class WorkflowState(Enum):
    INIT = "init"
    COLLECT_COMMITS = "collect_commits"
    COLLECT_DIFF = "collect_diff"
    ANALYZE_DIFF = "analyze_diff"
    RENDER_PREVIEW = "render_preview"
    WAIT_APPROVAL = "wait_approval"
    CREATE_WIKI = "create_wiki"
    DONE = "done"
    FAILED = "failed"


@dataclass
class WikiSession:
    """Wiki 생성 워크플로우 세션"""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_type: WorkflowType = WorkflowType.WORKFLOW_A
    state: WorkflowState = WorkflowState.INIT
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Workflow A specific
    issue_key: str = ""
    issue_title: str = ""
    assignee: str = "미지정"
    resolution_date: str = ""
    priority: str = "보통"

    # Workflow B specific
    page_title: str = ""
    input_type: str = "브랜치명"
    input_value: str = ""
    base_date: str = ""

    # Workflow C specific
    parent_page_id: str = ""  # 사용자 지정 부모 페이지 ID
    content_raw: str = ""     # 자유 형식 마크다운/텍스트 콘텐츠
    custom_space_key: str = ""  # 사용자 지정 space key (비어있으면 기본값 사용)

    # Project identification (멀티프로젝트 append용)
    project_name: str = ""

    # Update workflow specific
    update_target_page_id: str = ""    # 수정 대상 페이지 ID
    update_target_version: int = 0     # 조회 시점의 페이지 버전

    # Shared data
    branch_name: str = ""
    commit_list_raw: str = ""
    commit_list_html: str = ""
    diff_raw: str = ""
    diff_stat: str = ""  # git diff --stat 결과 (파일별 변경 통계)
    change_summary: str = ""
    rendered_preview: str = ""

    # Jira enrichment
    jira_issues: list[dict] = field(default_factory=list)

    # Approval
    approval_token: str = ""
    approval_expires_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now()

    def is_approval_expired(self) -> bool:
        """승인 토큰이 만료되었는지 확인합니다."""
        if self.approval_expires_at is None:
            return True
        return datetime.now() > self.approval_expires_at


@dataclass(frozen=True)
class WikiTemplate:
    """Wiki 본문 템플릿"""
    workflow_type: str
    body: str
    description: str = ""


@dataclass(frozen=True)
class WikiTitleFormat:
    """Wiki 페이지 제목 형식"""
    year_format: str
    month_format: str
