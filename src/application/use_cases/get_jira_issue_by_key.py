import logging

from src.application.ports.jira_port import JiraPort

logger = logging.getLogger(__name__)


class GetJiraIssueByKeyUseCase:
    """특정 Jira 이슈를 key(ID)로 조회하는 Use Case"""

    def __init__(self, jira_port: JiraPort):
        self.jira_port = jira_port

    async def execute(self, key: str) -> dict | None:
        """
        Jira 이슈를 key로 조회합니다.

        Args:
            key: Jira 이슈 키 (예: "BNFDEV-2365")

        Returns:
            이슈 정보 (dict 형식) 또는 None (이슈가 없을 경우)
        """
        logger.info("🔍 GetJiraIssueByKeyUseCase 실행 시작")
        logger.info("조회할 이슈 키: %s", key)

        # JQL 쿼리 생성
        jql = f'key="{key}"'
        logger.info("생성된 JQL 쿼리: %s", jql)

        issues = await self.jira_port.search_issues(jql)

        if not issues:
            logger.info("이슈를 찾을 수 없음: %s", key)
            return None

        issue = issues[0]
        logger.info("✅ 이슈 조회 완료: %s - %s", issue.key, issue.summary)

        return {
            "key": issue.key,
            "summary": issue.summary,
            "status": issue.status,
            "assignee": issue.assignee,
            "description": issue.description,
            "issuetype": issue.issuetype,
            "url": issue.url,
        }
