import logging
from datetime import date

from src.application.ports.jira_port import JiraPort

logger = logging.getLogger(__name__)


class CompleteJiraIssueUseCase:
    """Jira 이슈를 완료 처리하는 Use Case"""

    def __init__(self, jira_port: JiraPort):
        self.jira_port = jira_port

    async def execute(self, key: str, due_date: str | None = None) -> dict:
        """
        이슈를 완료 처리합니다.

        Args:
            key: Jira 이슈 키 (예: BNFDEV-1234)
            due_date: 종료일 (YYYY-MM-DD 형식). None이면 오늘 날짜 사용

        Returns:
            완료 처리 결과 dict
        """
        logger.info("CompleteJiraIssueUseCase 실행: key=%s, due_date=%s", key, due_date)

        if not due_date:
            due_date = date.today().isoformat()
            logger.info("종료일 미지정 → 오늘 날짜 사용: %s", due_date)

        result = await self.jira_port.complete_issue(key=key, due_date=due_date)

        logger.info("✅ Use Case 실행 완료: %s → %s", result["previous_status"], result["new_status"])

        return result
