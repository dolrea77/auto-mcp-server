import logging

from src.application.ports.jira_port import JiraPort

logger = logging.getLogger(__name__)


class GetProjectMetaUseCase:
    """Jira 프로젝트의 이슈 유형과 각 유형별 상태값을 조회하는 Use Case"""

    def __init__(self, jira_port: JiraPort):
        self.jira_port = jira_port

    async def execute(self, project_key: str) -> dict:
        logger.info("GetProjectMetaUseCase 실행: project_key=%s", project_key)
        meta = await self.jira_port.get_project_meta(project_key=project_key)

        return {
            "project_key": meta.project_key,
            "issuetype_statuses": meta.issuetype_statuses,
        }
