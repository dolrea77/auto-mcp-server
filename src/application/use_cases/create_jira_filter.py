import logging

from src.application.ports.jira_port import JiraPort

logger = logging.getLogger(__name__)


class CreateJiraFilterUseCase:
    """Jira 필터를 생성하는 Use Case"""

    def __init__(self, jira_port: JiraPort):
        self.jira_port = jira_port

    async def execute(self, name: str, jql: str) -> dict:
        """
        Jira 필터를 생성합니다.

        Args:
            name: 필터 이름
            jql: JQL 쿼리

        Returns:
            생성된 필터 정보 (dict 형식)
        """
        logger.info("🔍 CreateJiraFilterUseCase 실행 시작")
        logger.info("필터 이름: %s", name)
        logger.info("JQL: %s", jql)

        jira_filter = await self.jira_port.create_filter(name=name, jql=jql)

        logger.info("✅ Use Case 실행 완료: 필터 id=%s 생성됨", jira_filter.id)

        return {
            "id": jira_filter.id,
            "name": jira_filter.name,
            "jql": jira_filter.jql,
            "url": jira_filter.url,
        }
