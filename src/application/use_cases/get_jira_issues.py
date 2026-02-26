import logging

from src.application.ports.jira_port import JiraPort

logger = logging.getLogger(__name__)


class GetJiraIssuesUseCase:
    """현재 사용자에게 할당된 Jira 이슈를 조회하는 Use Case"""

    def __init__(self, jira_port: JiraPort, jira_user: str):
        self.jira_port = jira_port
        self.jira_user = jira_user

    async def execute(self, statuses: list[str] | None = None, project_key: str | None = None) -> list[dict]:
        """
        Jira 이슈를 조회합니다.

        Args:
            statuses: 조회할 이슈 상태 목록. None이면 모든 상태 조회 (status 필터 없음)
            project_key: 특정 프로젝트로 필터링. None이면 전체 프로젝트 조회

        Returns:
            이슈 목록 (dict 형식)
        """
        logger.info("📋 GetJiraIssuesUseCase 실행 시작")

        conditions = [f'assignee="{self.jira_user}"']

        if project_key:
            conditions.append(f'project="{project_key}"')
            logger.info("프로젝트 필터: %s", project_key)

        if statuses is None:
            logger.info("모든 상태의 이슈 조회 (status 필터 없음)")
        else:
            logger.info("사용자 지정 상태 필터: %s", statuses)
            status_filter = ", ".join(f'"{s}"' for s in statuses)
            conditions.append(f'status in ({status_filter})')

        jql = " AND ".join(conditions)

        logger.info("생성된 JQL 쿼리: %s", jql)

        issues = await self.jira_port.search_issues(jql)

        logger.info("✅ Use Case 실행 완료: %d개 이슈 변환", len(issues))

        return [
            {
                "key": issue.key,
                "summary": issue.summary,
                "status": issue.status,
                "assignee": issue.assignee,
                "description": issue.description,
                "issuetype": issue.issuetype,
                "url": issue.url,
            }
            for issue in issues
        ]
