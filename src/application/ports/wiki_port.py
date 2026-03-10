from typing import Protocol

from src.domain.wiki import WikiPage, WikiPageCreationResult, WikiPageWithContent


class WikiPort(Protocol):
    """Confluence Wiki 서비스 계약 (Port)"""

    async def get_child_pages(self, page_id: str) -> list[WikiPage]:
        """특정 페이지의 하위 페이지 목록을 조회합니다."""
        ...

    async def create_page(
        self,
        parent_page_id: str,
        title: str,
        body: str,
        space_key: str,
    ) -> WikiPage:
        """새 페이지를 생성합니다."""
        ...

    async def get_or_create_year_month_page(
        self,
        root_page_id: str,
        year: int,
        month: int,
        space_key: str,
        year_title: str | None = None,
        month_title: str | None = None,
    ) -> tuple[str, str]:
        """
        년/월 페이지를 조회하거나 없으면 생성합니다.

        Returns:
            (year_page_id, month_page_id) 튜플
        """
        ...

    async def find_page_by_title(
        self,
        parent_page_id: str,
        title: str,
    ) -> WikiPage | None:
        """부모 페이지 하위에서 제목으로 페이지를 검색합니다."""
        ...

    async def search_page_by_title(
        self,
        title: str,
        space_key: str,
    ) -> WikiPage | None:
        """Space 내에서 정확한 제목으로 페이지를 검색합니다."""
        ...

    async def get_page_with_content(self, page_id: str) -> WikiPageWithContent:
        """페이지의 본문과 버전 정보를 포함하여 조회합니다."""
        ...

    async def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        version: int,
        space_key: str,
    ) -> WikiPage:
        """기존 페이지를 업데이트합니다. version은 현재 버전 + 1이어야 합니다."""
        ...
