from dataclasses import dataclass, field


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
    created: str | None = None           # 생성일 (BNFMT 경로 기준)
    custom_end_date: str | None = None   # customfield_10833 종료일 (BNFDEV 경로 기준)


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
