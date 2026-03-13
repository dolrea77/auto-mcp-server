import logging

from src.application.ports.jira_port import JiraPort
from src.domain.jira import JiraProjectConfig

logger = logging.getLogger(__name__)


class GetJiraIssuesUseCase:
    """현재 사용자(또는 지정 담당자)에게 할당된 Jira 이슈를 조회하는 Use Case"""

    def __init__(
        self,
        jira_port: JiraPort,
        jira_user: str,
        project_configs: list[JiraProjectConfig] | None = None,
    ):
        self.jira_port = jira_port
        self.jira_user = jira_user
        # 모든 프로젝트 config의 커스텀 필드 표시명 합집합
        self._valid_custom_field_names: set[str] = set()
        if project_configs:
            for config in project_configs:
                self._valid_custom_field_names.update(config.jira_custom_fields.keys())

    async def execute(
        self,
        statuses: list[str] | None = None,
        project_key: str | None = None,
        issuetype: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        text: str | None = None,
        assignee: str | None = None,
        custom_field_filters: dict[str, dict[str, str]] | None = None,
    ) -> list[dict]:
        """
        Jira 이슈를 조회합니다.

        Args:
            statuses: 조회할 이슈 상태 목록. None이면 모든 상태 조회 (status 필터 없음)
            project_key: 특정 프로젝트로 필터링. None이면 전체 프로젝트 조회
            issuetype: 이슈 유형 필터 (예: "버그", "스토리"). None이면 필터 없음
            created_after: 생성일 시작 범위 (예: "2024-01-01"). None이면 필터 없음
            created_before: 생성일 종료 범위 (예: "2024-12-31"). None이면 필터 없음
            text: 전문 검색 키워드. None이면 필터 없음
            assignee: 담당자 지정. None이면 현재 사용자(jira_user)로 조회
            custom_field_filters: 커스텀 필드 범위 필터.
                형식: {"표시명": {"after": "2024-01-01", "before": "2024-12-31"}}
                표시명은 JiraProjectConfig.jira_custom_fields의 키여야 함

        Returns:
            이슈 목록 (dict 형식)

        Raises:
            ValueError: custom_field_filters에 알 수 없는 표시명이 포함된 경우
        """
        logger.info("GetJiraIssuesUseCase 실행 시작")

        # assignee 조건: 지정 시 해당 사용자, 미지정 시 현재 사용자
        if assignee:
            conditions = [f'assignee="{assignee}"']
            logger.info("담당자 필터: %s", assignee)
        else:
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

        if issuetype:
            conditions.append(f'issuetype="{issuetype}"')
            logger.info("이슈 유형 필터: %s", issuetype)

        if created_after:
            conditions.append(f'created >= "{created_after}"')
            logger.info("생성일 시작 필터: %s", created_after)

        if created_before:
            conditions.append(f'created <= "{created_before}"')
            logger.info("생성일 종료 필터: %s", created_before)

        if text:
            conditions.append(f'text ~ "{text}"')
            logger.info("전문 검색 필터: %s", text)

        if custom_field_filters:
            for display_name, range_filter in custom_field_filters.items():
                if display_name not in self._valid_custom_field_names:
                    raise ValueError(
                        f"알 수 없는 커스텀 필드 표시명: '{display_name}'. "
                        f"사용 가능한 필드: {sorted(self._valid_custom_field_names)}"
                    )
                after = range_filter.get("after")
                before = range_filter.get("before")
                if after:
                    conditions.append(f'"{display_name}" >= "{after}"')
                    logger.info("커스텀 필드 시작 필터: %s >= %s", display_name, after)
                if before:
                    conditions.append(f'"{display_name}" <= "{before}"')
                    logger.info("커스텀 필드 종료 필터: %s <= %s", display_name, before)

        jql = " AND ".join(conditions)

        logger.info("생성된 JQL 쿼리: %s", jql)

        issues = await self.jira_port.search_issues(jql)

        logger.info("Use Case 실행 완료: %d개 이슈 변환", len(issues))

        return [
            {
                "key": issue.key,
                "summary": issue.summary,
                "status": issue.status,
                "assignee": issue.assignee,
                "description": issue.description,
                "issuetype": issue.issuetype,
                "url": issue.url,
                "custom_fields": dict(issue.custom_fields),
            }
            for issue in issues
        ]
