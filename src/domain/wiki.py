from dataclasses import dataclass


@dataclass(frozen=True)
class WikiPage:
    """Confluence Wiki 페이지 엔티티"""
    id: str
    title: str
    url: str
    space_key: str


@dataclass(frozen=True)
class WikiPageWithContent:
    """Confluence Wiki 페이지 (본문 + 버전 포함)"""
    id: str
    title: str
    url: str
    space_key: str
    body: str        # storage format HTML
    version: int     # 현재 버전 번호


@dataclass(frozen=True)
class WikiPageCreationResult:
    """Wiki 페이지 생성 결과"""
    page_id: str
    title: str
    url: str
    parent_page_id: str
    year_page_id: str = ""
    month_page_id: str = ""
    was_updated: bool = False  # True이면 기존 페이지에 프로젝트 섹션 append
