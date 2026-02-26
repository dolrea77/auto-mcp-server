import logging

from src.application.ports.jira_port import JiraPort

logger = logging.getLogger(__name__)


class TransitionJiraIssueUseCase:
    """Jira 이슈 상태를 지정한 값으로 전환하는 Use Case"""

    def __init__(self, jira_port: JiraPort):
        self.jira_port = jira_port

    async def execute(self, key: str, target_status: str) -> dict:
        """
        이슈 상태를 target_status 로 전환합니다.

        Args:
            key: Jira 이슈 키 (예: BNFDEV-1234)
            target_status: 전환할 목표 상태명 (예: '진행중(개발)', '개발(BNF)', '운영검수(BNF)')

        Returns:
            전환 결과 dict
        """
        logger.info("TransitionJiraIssueUseCase 실행: key=%s, target_status=%s", key, target_status)

        result = await self.jira_port.transition_issue(key=key, target_status=target_status)

        logger.info("✅ Use Case 실행 완료: %s → %s", result["previous_status"], result["new_status"])

        return result
