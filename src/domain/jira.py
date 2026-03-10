from dataclasses import dataclass, field


@dataclass(frozen=True)
class JiraProjectConfig:
    """프로젝트별 Jira 설정"""
    key: str                              # 프로젝트 키 (예: "MYPROJECT")
    due_date_field: str | None            # 종료일 필드 (None=미설정)
    wiki_date_field: str                  # Wiki 기준일 Jira 필드명 (빈 문자열=날짜 없음)
    jira_custom_fields: dict[str, str] = field(default_factory=dict)    # 표시명→필드ID 매핑
    statuses: list[str] = field(default_factory=list)                   # 주요 상태값 목록
    status_mapping: dict[str, list[str]] = field(default_factory=dict)  # 영어→한글 상태 매핑


@dataclass(frozen=True)
class JiraIssue:
    """Jira 이슈 엔티티"""
    key: str
    summary: str
    status: str
    assignee: str
    description: str | None
    issuetype: str
    url: str
    created: str | None = None
    custom_fields: dict[str, str | None] = field(default_factory=dict)  # Jira 커스텀 필드 동적 저장


@dataclass(frozen=True)
class JiraFilter:
    """Jira 필터 엔티티"""
    id: str
    name: str
    jql: str
    url: str


@dataclass(frozen=True)
class JiraProjectMeta:
    """Jira 프로젝트 메타 엔티티 (이슈 유형별 상태 목록)"""
    project_key: str
    issuetype_statuses: dict[str, list[str]]
