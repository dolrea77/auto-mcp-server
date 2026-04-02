from typing import Protocol

from src.domain.jira import JiraIssue, JiraFilter, JiraProjectMeta


class JiraPort(Protocol):
    """Jira 서비스와의 계약을 정의하는 Port"""

    async def search_issues(self, jql: str) -> list[JiraIssue]:
        """JQL 쿼리를 사용하여 Jira 이슈를 조회합니다."""
        ...

    async def create_filter(self, name: str, jql: str) -> JiraFilter:
        """Jira 필터를 생성합니다."""
        ...

    async def get_project_meta(self, project_key: str) -> JiraProjectMeta:
        """프로젝트의 이슈 유형과 각 유형별 상태값을 조회합니다."""
        ...

    async def complete_issue(self, key: str, due_date: str) -> dict:
        """이슈를 완료 처리합니다 (상태 전환 + 종료일 설정)."""
        ...

    async def transition_issue(self, key: str, target_status: str) -> dict:
        """이슈 상태를 지정한 값으로 전환합니다."""
        ...

    async def get_issue_attachments(self, issue_key: str) -> list[dict]:
        """이슈의 첨부파일 메타정보를 조회합니다.

        Returns:
            list of dict, 각 항목:
            - id: str (첨부파일 ID)
            - filename: str
            - size: int (bytes)
            - mimeType: str
            - content_url: str (다운로드 URL)
        """
        ...

    async def download_attachment_content(self, content_url: str) -> bytes:
        """첨부파일 content URL에서 바이너리 데이터를 다운로드합니다."""
        ...
