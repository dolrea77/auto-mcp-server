import logging

import httpx

from src.domain.wiki import WikiPage, WikiPageWithContent

logger = logging.getLogger(__name__)


class WikiAdapter:
    """Confluence REST API와 통신하는 Outbound Adapter"""

    def __init__(self, base_url: str, user: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password

    async def get_child_pages(self, page_id: str, limit: int = 50) -> list[WikiPage]:
        """특정 페이지의 하위 페이지 목록을 페이지네이션으로 전체 조회합니다."""
        url = f"{self.base_url}/rest/api/content/{page_id}/child/page"
        logger.info("🌐 Confluence 하위 페이지 조회: page_id=%s", page_id)

        pages = []
        start = 0
        while True:
            params = {"start": start, "limit": limit}
            data = await self._request("GET", url, params=params, error_text_limit=200)

            for result in data.get("results", []):
                page = WikiPage(
                    id=str(result.get("id", "")),
                    title=result.get("title", ""),
                    url=self._build_page_url(result),
                    space_key=result.get("space", {}).get("key", ""),
                )
                pages.append(page)
                logger.info("  - 하위 페이지: [%s] %s", page.id, page.title)

            size = data.get("size", 0)
            if size < limit:
                break
            start += limit

        logger.info("✅ 하위 페이지 조회 완료: %d건", len(pages))
        return pages

    async def create_page(
        self,
        parent_page_id: str,
        title: str,
        body: str,
        space_key: str,
    ) -> WikiPage:
        """새 Confluence 페이지를 생성합니다."""
        url = f"{self.base_url}/rest/api/content"
        payload = {
            "type": "page",
            "title": title,
            "ancestors": [{"id": parent_page_id}],
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body,
                    "representation": "storage",
                }
            },
        }

        logger.info("🌐 Confluence 페이지 생성: title=%s, parent=%s", title, parent_page_id)

        data = await self._request(
            "POST",
            url,
            json=payload,
            error_text_limit=500,
            custom_errors={409: f"동일한 제목의 페이지가 이미 존재합니다: '{title}'"},
        )

        page = WikiPage(
            id=str(data.get("id", "")),
            title=data.get("title", title),
            url=self._build_page_url(data),
            space_key=space_key,
        )
        logger.info("✅ 페이지 생성 완료: id=%s, title=%s", page.id, page.title)
        return page

    async def find_page_by_title(
        self,
        parent_page_id: str,
        title: str,
    ) -> WikiPage | None:
        """부모 페이지 하위에서 제목으로 페이지를 검색합니다."""
        child_pages = await self.get_child_pages(parent_page_id)
        for page in child_pages:
            if page.title == title:
                logger.info("✅ 페이지 발견: [%s] %s", page.id, page.title)
                return page
        logger.info("페이지 없음: title=%s (parent_id=%s)", title, parent_page_id)
        return None

    async def search_page_by_title(
        self,
        title: str,
        space_key: str,
    ) -> WikiPage | None:
        """Space 내에서 정확한 제목으로 페이지를 검색합니다."""
        url = f"{self.base_url}/rest/api/content"
        params = {
            "title": title,
            "spaceKey": space_key,
            "type": "page",
            "limit": 1,
        }
        logger.info("Confluence 페이지 검색: title=%s, space=%s", title, space_key)

        data = await self._request("GET", url, params=params, error_text_limit=200)

        results = data.get("results", [])
        if not results:
            logger.info("페이지 없음: title=%s (space=%s)", title, space_key)
            return None

        result = results[0]
        page = WikiPage(
            id=str(result.get("id", "")),
            title=result.get("title", ""),
            url=self._build_page_url(result),
            space_key=result.get("space", {}).get("key", space_key),
        )
        logger.info("페이지 발견: [%s] %s", page.id, page.title)
        return page

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

        Args:
            year_title: 년도 페이지 제목. None이면 "{year}년" 사용
            month_title: 월 페이지 제목. None이면 "{month}월" 사용

        Returns:
            (year_page_id, month_page_id) 튜플
        """
        if year_title is None:
            year_title = f"{year}년"
        if month_title is None:
            month_title = f"{month}월"

        # 년도 페이지 조회 or 생성
        year_page = await self.find_page_by_title(root_page_id, year_title)
        if year_page is None:
            logger.info("년도 페이지 생성: %s", year_title)
            year_page = await self.create_page(
                parent_page_id=root_page_id,
                title=year_title,
                body=f"<p>{year_title} 이슈 정리 목록</p>",
                space_key=space_key,
            )
        else:
            logger.info("기존 년도 페이지 사용: [%s] %s", year_page.id, year_page.title)

        # 월 페이지 조회 or 생성
        month_page = await self.find_page_by_title(year_page.id, month_title)
        if month_page is None:
            logger.info("월 페이지 생성: %s", month_title)
            month_page = await self.create_page(
                parent_page_id=year_page.id,
                title=month_title,
                body=f"<p>{year_title} {month_title} 이슈 정리 목록</p>",
                space_key=space_key,
            )
        else:
            logger.info("기존 월 페이지 사용: [%s] %s", month_page.id, month_page.title)

        return year_page.id, month_page.id

    async def get_page_with_content(self, page_id: str) -> WikiPageWithContent:
        """페이지의 본문과 버전 정보를 포함하여 조회합니다."""
        url = f"{self.base_url}/rest/api/content/{page_id}"
        params = {"expand": "body.storage,version,space"}
        logger.info("Confluence 페이지 본문 조회: page_id=%s", page_id)

        data = await self._request("GET", url, params=params, error_text_limit=200)

        page = WikiPageWithContent(
            id=str(data.get("id", "")),
            title=data.get("title", ""),
            url=self._build_page_url(data),
            space_key=data.get("space", {}).get("key", ""),
            body=data.get("body", {}).get("storage", {}).get("value", ""),
            version=data.get("version", {}).get("number", 1),
        )
        logger.info(
            "페이지 본문 조회 완료: id=%s, version=%d, body_len=%d",
            page.id, page.version, len(page.body),
        )
        return page

    async def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        version: int,
        space_key: str,
    ) -> WikiPage:
        """기존 페이지를 업데이트합니다. version은 현재 버전 + 1이어야 합니다."""
        url = f"{self.base_url}/rest/api/content/{page_id}"
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body,
                    "representation": "storage",
                }
            },
            "version": {"number": version},
        }

        logger.info(
            "Confluence 페이지 업데이트: page_id=%s, title=%s, version=%d",
            page_id, title, version,
        )

        data = await self._request(
            "PUT",
            url,
            json=payload,
            error_text_limit=500,
            custom_errors={
                409: f"페이지 버전 충돌: 다른 사용자가 먼저 수정했습니다 (page_id={page_id})",
            },
        )

        page = WikiPage(
            id=str(data.get("id", "")),
            title=data.get("title", title),
            url=self._build_page_url(data),
            space_key=space_key,
        )
        logger.info("페이지 업데이트 완료: id=%s, version=%d", page.id, version)
        return page

    async def upload_attachment(
        self,
        page_id: str,
        filename: str,
        data: bytes,
        content_type: str,
        comment: str = "",
    ) -> str:
        """페이지에 첨부파일을 업로드한다.

        Confluence REST API: POST /rest/api/content/{id}/child/attachment
        동일 파일명이 존재하면 기존 첨부파일을 찾아 새 버전으로 업데이트한다.

        Returns:
            업로드된 첨부파일명
        """
        url = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"

        logger.info(
            "Confluence 첨부파일 업로드: page_id=%s, filename=%s, size=%d",
            page_id, filename, len(data),
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    auth=(self.user, self.password),
                    headers={"X-Atlassian-Token": "nocheck"},
                    files={"file": (filename, data, content_type)},
                    data={"comment": comment} if comment else {},
                    timeout=30.0,
                )
                response.raise_for_status()

            logger.info("✅ 첨부파일 업로드 완료: %s", filename)
            return filename

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "same file name" in e.response.text:
                return await self._update_existing_attachment(
                    page_id, filename, data, content_type, comment,
                )
            logger.error("❌ 첨부파일 업로드 실패: %d", e.response.status_code)
            self._raise_http_error(e)
        except httpx.NetworkError as e:
            raise RuntimeError(f"Confluence 서버 연결 실패: {self.base_url}") from e

    async def _update_existing_attachment(
        self,
        page_id: str,
        filename: str,
        data: bytes,
        content_type: str,
        comment: str,
    ) -> str:
        """기존 첨부파일을 새 버전으로 업데이트한다."""
        base = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"

        async with httpx.AsyncClient() as client:
            # 기존 첨부파일 ID 조회
            resp = await client.get(
                base,
                params={"filename": filename},
                auth=(self.user, self.password),
                timeout=15.0,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                raise RuntimeError(f"첨부파일 '{filename}'을 찾을 수 없습니다")

            att_id = results[0]["id"]
            update_url = f"{base}/{att_id}/data"

            response = await client.post(
                update_url,
                auth=(self.user, self.password),
                headers={"X-Atlassian-Token": "nocheck"},
                files={"file": (filename, data, content_type)},
                data={"comment": comment} if comment else {},
                timeout=30.0,
            )
            response.raise_for_status()

        logger.info("✅ 기존 첨부파일 업데이트 완료: %s (id=%s)", filename, att_id)
        return filename

    async def _request(
        self,
        method: str,
        url: str,
        *,
        error_text_limit: int = 200,
        custom_errors: dict[int, str] | None = None,
        **kwargs,
    ) -> dict:
        """공통 HTTP 요청을 수행하고 JSON 응답을 반환합니다."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method,
                    url,
                    auth=(self.user, self.password),
                    timeout=30.0,
                    **kwargs,
                )
                logger.info("HTTP Status: %d", response.status_code)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error("❌ HTTP 오류: %d - %s", e.response.status_code, e.response.text[:error_text_limit])
            if custom_errors and e.response.status_code in custom_errors:
                raise RuntimeError(custom_errors[e.response.status_code]) from e
            self._raise_http_error(e)
        except httpx.NetworkError as e:
            logger.error("❌ 네트워크 오류: %s", str(e))
            raise RuntimeError(f"Confluence 서버 연결 실패: {self.base_url}") from e

    def _build_page_url(self, data: dict) -> str:
        """응답 데이터에서 페이지 URL을 생성합니다."""
        links = data.get("_links", {})
        webui = links.get("webui", "")
        if webui:
            return f"{self.base_url}{webui}"
        page_id = data.get("id", "")
        return f"{self.base_url}/pages/viewpage.action?pageId={page_id}" if page_id else ""

    def _raise_http_error(self, e: httpx.HTTPStatusError) -> None:
        """HTTP 상태 코드별 적절한 RuntimeError를 발생시킵니다."""
        status = e.response.status_code
        if status == 401:
            raise RuntimeError("Confluence 인증 실패: USER_ID 또는 USER_PASSWORD를 확인하세요") from e
        elif status == 403:
            raise RuntimeError("Confluence 접근 권한이 없습니다") from e
        elif status == 404:
            raise RuntimeError("Confluence 페이지를 찾을 수 없습니다") from e
        elif status == 400:
            raise RuntimeError(f"잘못된 요청입니다: {e.response.text[:200]}") from e
        else:
            raise RuntimeError(f"Confluence API 오류: {status}") from e
