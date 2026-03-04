import logging

import httpx

from src.domain.jira import JiraIssue, JiraFilter, JiraProjectConfig, JiraProjectMeta

logger = logging.getLogger(__name__)


def _collect_custom_field_ids(configs: list[JiraProjectConfig]) -> set[str]:
    """설정에서 참조하는 모든 customfield_* 필드 ID를 수집"""
    field_ids: set[str] = set()
    for config in configs:
        if config.due_date_field and config.due_date_field.startswith("customfield_"):
            field_ids.add(config.due_date_field)
        if config.wiki_date_field and config.wiki_date_field.startswith("customfield_"):
            field_ids.add(config.wiki_date_field)
        for field_id in config.jira_custom_fields.values():
            if field_id.startswith("customfield_"):
                field_ids.add(field_id)
    return field_ids


def _build_field_display_names(configs: list[JiraProjectConfig]) -> dict[str, str]:
    """필드 ID → 표시명 역방향 매핑 (모든 프로젝트 통합)"""
    display_names: dict[str, str] = {}
    for config in configs:
        for display_name, field_id in config.jira_custom_fields.items():
            display_names[field_id] = display_name
    return display_names

# 이슈 유형별 완료 상태값 우선순위 맵
# 각 리스트는 우선순위 순으로 나열 (앞쪽이 더 우선)
_DONE_STATUS_PRIORITY: list[str] = [
    "배포완료(BNF)",
    "DONE(BNF)",
    "검수완료(BNF)",
    "개발완료(BNF)",
    "답변완료(BNF)",
    "기획/설계 완료(BNF)",
    "완료(개발)",
    "완료(설계)",
    "완료",
]


class JiraAdapter:
    """Jira REST API와 통신하는 Outbound Adapter"""

    def __init__(self, base_url: str, user: str, password: str, project_configs: list[JiraProjectConfig] | None = None):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self._project_configs = project_configs or []
        self._configs_by_key: dict[str, JiraProjectConfig] = {c.key: c for c in self._project_configs}
        self._custom_field_ids: set[str] = _collect_custom_field_ids(self._project_configs)
        self._field_display_names: dict[str, str] = _build_field_display_names(self._project_configs)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def search_issues(self, jql: str) -> list[JiraIssue]:
        """JQL 쿼리를 사용하여 Jira 이슈를 조회합니다."""
        url = f"{self.base_url}/rest/api/2/search"
        base_fields = "key,summary,status,assignee,description,issuetype,created"
        if self._custom_field_ids:
            fields_str = f"{base_fields},{','.join(sorted(self._custom_field_ids))}"
        else:
            fields_str = base_fields
        params = {
            "jql": jql,
            "fields": fields_str,
        }

        logger.info("🌐 Jira API 호출 시작")
        logger.info("URL: %s", url)
        logger.info("JQL: %s", jql)
        logger.info("User: %s", self.user)

        data = await self._request(
            "GET",
            url,
            params=params,
            context_msg="Jira 이슈 조회",
        )

        total = data.get("total", 0)
        logger.info("총 이슈 수: %d", total)

        issues = []
        for issue_data in data.get("issues", []):
            issue = self._parse_issue(issue_data)
            issues.append(issue)
            logger.info("  - %s: %s [%s]", issue.key, issue.summary, issue.status)

        logger.info("✅ Jira 이슈 조회 성공: %d건", len(issues))
        return issues

    async def create_filter(self, name: str, jql: str) -> JiraFilter:
        """Jira 필터를 생성합니다."""
        url = f"{self.base_url}/rest/api/2/filter"
        payload = {
            "name": name,
            "jql": jql,
            "favourite": True,
        }

        logger.info("🌐 Jira 필터 생성 API 호출 시작")
        logger.info("URL: %s", url)
        logger.info("필터 이름: %s", name)
        logger.info("JQL: %s", jql)

        data = await self._request(
            "POST",
            url,
            json=payload,
            custom_errors={
                400: f"잘못된 요청입니다. JQL 문법을 확인하세요: ",
            },
            context_msg="Jira 필터 생성",
        )

        filter_id = str(data.get("id", ""))
        filter_name = data.get("name", name)
        filter_jql = data.get("jql", jql)
        filter_url = f"{self.base_url}/issues/?filter={filter_id}" if filter_id else ""

        logger.info("✅ Jira 필터 생성 성공: id=%s, name=%s", filter_id, filter_name)

        return JiraFilter(
            id=filter_id,
            name=filter_name,
            jql=filter_jql,
            url=filter_url,
        )

    async def get_project_meta(self, project_key: str) -> JiraProjectMeta:
        """프로젝트의 이슈 유형과 각 유형별 상태값을 조회합니다."""
        logger.info("🌐 Jira 프로젝트 메타 조회 시작: %s", project_key)

        issuetypes_url = f"{self.base_url}/rest/api/2/project/{project_key}/statuses"
        statuses_data = await self._request(
            "GET",
            issuetypes_url,
            custom_errors={
                404: f"프로젝트를 찾을 수 없습니다: {project_key}",
            },
            context_msg="프로젝트 메타 조회",
            status_label="HTTP Status (statuses)",
        )

        # issuetype별 상태값 파싱
        issuetype_statuses: dict[str, list[str]] = {}
        for item in statuses_data:
            issuetype_name = item.get("name", "Unknown")
            statuses = [s.get("name", "") for s in item.get("statuses", [])]
            issuetype_statuses[issuetype_name] = statuses
            logger.info("  이슈 유형: %s → 상태: %s", issuetype_name, statuses)

        logger.info("✅ 프로젝트 메타 조회 성공: %d개 이슈 유형", len(issuetype_statuses))

        return JiraProjectMeta(
            project_key=project_key,
            issuetype_statuses=issuetype_statuses,
        )

    async def complete_issue(self, key: str, due_date: str) -> dict[str, str]:
        """
        이슈를 완료 처리합니다.

        완료 상태 우선순위(_DONE_STATUS_PRIORITY) 중 해당 이슈에서
        전환 가능한 첫 번째 상태로 전환하고 프로젝트 설정에 따라 종료일을 설정합니다.
        """
        logger.info("🔄 이슈 완료 처리 시작: key=%s, due_date=%s", key, due_date)

        async with self._client() as client:
            # 트랜지션 목록을 미리 조회해 완료 상태 후보 결정
            transitions_url = f"{self.base_url}/rest/api/2/issue/{key}/transitions"
            resp = await client.get(transitions_url)
            resp.raise_for_status()
            transitions_map: dict[str, str] = {
                t.get("to", {}).get("name", ""): t.get("id", "")
                for t in resp.json().get("transitions", [])
            }

            target_status = next(
                (s for s in _DONE_STATUS_PRIORITY if s in transitions_map),
                None,
            )
            if not target_status:
                available = list(transitions_map.keys())
                raise RuntimeError(
                    f"이슈 '{key}'에서 완료 상태로 전환할 수 있는 트랜지션이 없습니다. "
                    f"사용 가능한 트랜지션: {available}"
                )

            summary, current_status, resolved_status, _ = await self._do_transition(
                client=client,
                key=key,
                target_status=target_status,
            )

            # 프로젝트 설정에 따라 종료일 처리
            project_prefix = key.split("-")[0] if "-" in key else ""
            config = self._configs_by_key.get(project_prefix)
            due_date_field = config.due_date_field if config else None

            if due_date_field:
                resp = await client.put(
                    f"{self.base_url}/rest/api/2/issue/{key}",
                    json={"fields": {due_date_field: due_date}},
                )
                resp.raise_for_status()
                display_name = self._field_display_names.get(due_date_field, due_date_field)
                logger.info("✅ 종료일 설정 완료 (%s): %s", display_name, due_date)
            else:
                logger.info("ℹ️ '%s' 프로젝트는 종료일을 설정하지 않습니다.", project_prefix)

        logger.info("✅ 이슈 완료 처리 성공: %s", key)
        return {
            "key": key,
            "summary": summary,
            "previous_status": current_status,
            "new_status": resolved_status,
            "due_date": due_date,
            "url": f"{self.base_url}/browse/{key}",
        }

    async def transition_issue(self, key: str, target_status: str) -> dict:
        """
        이슈 상태를 지정한 값으로 전환합니다.

        Args:
            key: Jira 이슈 키 (예: BNFDEV-1234)
            target_status: 전환할 목표 상태명 (예: '진행중(개발)', '개발(BNF)')

        Returns:
            전환 결과 dict
        """
        logger.info("🔄 이슈 상태 전환 시작: key=%s, target_status=%s", key, target_status)

        async with self._client() as client:
            summary, current_status, resolved_status, _ = await self._do_transition(
                client=client,
                key=key,
                target_status=target_status,
            )

        logger.info("✅ 이슈 상태 전환 성공: %s", key)
        return {
            "key": key,
            "summary": summary,
            "previous_status": current_status,
            "new_status": resolved_status,
            "url": f"{self.base_url}/browse/{key}",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        """auth와 timeout이 설정된 httpx.AsyncClient를 반환합니다."""
        return httpx.AsyncClient(
            auth=(self.user, self.password),
            timeout=30.0,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        custom_errors: dict[int, str] | None = None,
        context_msg: str = "Jira API",
        status_label: str = "HTTP Status",
        **kwargs,
    ) -> dict:
        """공통 HTTP 요청. JSON dict 반환."""
        try:
            async with self._client() as client:
                response = await client.request(method, url, **kwargs)
                logger.info("%s: %d", status_label, response.status_code)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("❌ HTTP 오류 발생: %d", e.response.status_code)
            logger.error("응답 본문: %s", e.response.text[:500])
            self._raise_jira_error(e, custom_errors)
        except httpx.NetworkError as e:
            logger.error("❌ 네트워크 오류: %s", str(e))
            raise RuntimeError(f"Jira 서버 연결 실패: {self.base_url}") from e
        except Exception as e:
            logger.error("❌ 예상치 못한 오류: %s", str(e))
            raise RuntimeError(f"{context_msg} 중 오류 발생: {str(e)}") from e

    def _raise_jira_error(
        self,
        e: httpx.HTTPStatusError,
        custom_errors: dict[int, str] | None = None,
    ) -> None:
        """HTTP 상태 코드별 적절한 RuntimeError를 발생시킵니다."""
        status = e.response.status_code
        if custom_errors and status in custom_errors:
            msg = custom_errors[status]
            if status == 400 and msg.endswith(": "):
                msg = f"{msg}{e.response.text[:200]}"
            raise RuntimeError(msg) from e
        if status == 401:
            raise RuntimeError("Jira 인증 실패: 사용자명 또는 비밀번호를 확인하세요") from e
        elif status == 403:
            raise RuntimeError("Jira 접근 권한이 없습니다") from e
        else:
            raise RuntimeError(f"Jira API 오류: {status}") from e

    async def _do_transition(
        self,
        client: httpx.AsyncClient,
        key: str,
        target_status: str,
    ) -> tuple[str, str, str, str]:
        """
        공통 트랜지션 실행 헬퍼.

        1. 이슈 기본 정보 조회 (summary, current_status, issuetype)
        2. 사용 가능한 트랜지션 목록 조회
        3. target_status 와 일치하는 트랜지션 실행

        Returns:
            (summary, current_status, resolved_target_status, issuetype)
        """
        # 1. 이슈 조회
        resp = await client.get(
            f"{self.base_url}/rest/api/2/issue/{key}",
            params={"fields": "summary,status,issuetype,project"},
        )
        resp.raise_for_status()
        issue_data = resp.json()
        fields = issue_data.get("fields", {})
        current_status = fields.get("status", {}).get("name", "")
        issuetype = fields.get("issuetype", {}).get("name", "")
        summary = fields.get("summary", "")
        logger.info("이슈 정보: status=%s, issuetype=%s", current_status, issuetype)

        # 2. 트랜지션 목록 조회 → {상태명: 트랜지션 ID}
        transitions_url = f"{self.base_url}/rest/api/2/issue/{key}/transitions"
        resp = await client.get(transitions_url)
        resp.raise_for_status()
        transitions_map: dict[str, str] = {}
        for t in resp.json().get("transitions", []):
            t_name = t.get("to", {}).get("name", "")
            t_id = t.get("id", "")
            transitions_map[t_name] = t_id
            logger.info("  가능한 트랜지션: %s (id=%s)", t_name, t_id)

        # 3. 목표 상태 결정
        transition_id = transitions_map.get(target_status)
        if not transition_id:
            available = list(transitions_map.keys())
            raise RuntimeError(
                f"이슈 '{key}'({issuetype})에서 '{target_status}' 상태로 전환할 수 없습니다. "
                f"사용 가능한 트랜지션: {available}"
            )
        logger.info("선택된 상태: %s (트랜지션 id=%s)", target_status, transition_id)

        # 4. 트랜지션 실행
        resp = await client.post(
            transitions_url,
            json={"transition": {"id": transition_id}},
        )
        resp.raise_for_status()
        logger.info("✅ 트랜지션 완료: %s → %s", current_status, target_status)

        return summary, current_status, target_status, issuetype

    def _parse_issue(self, issue_data: dict[str, str | dict[str, str]]) -> JiraIssue:
        """API 응답을 JiraIssue 엔티티로 파싱합니다."""
        fields = issue_data.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}

        status_obj = fields.get("status")
        status = status_obj.get("name", "Unknown") if isinstance(status_obj, dict) else "Unknown"

        assignee_obj = fields.get("assignee")
        assignee = assignee_obj.get("displayName", "Unassigned") if isinstance(assignee_obj, dict) else "Unassigned"

        issuetype_obj = fields.get("issuetype")
        issuetype = issuetype_obj.get("name", "Unknown") if isinstance(issuetype_obj, dict) else "Unknown"

        description_raw = fields.get("description")
        description = str(description_raw) if description_raw is not None else None

        # 날짜 필드
        created_raw = fields.get("created")
        created_str = str(created_raw)[:10] if created_raw else None

        # 동적 커스텀 필드 수집
        custom_fields_data: dict[str, str | None] = {}
        for cf_id in self._custom_field_ids:
            raw_val = fields.get(cf_id)
            custom_fields_data[cf_id] = str(raw_val) if raw_val is not None else None

        # 이슈 URL (브라우저에서 열 수 있는 링크)
        key = str(issue_data.get("key", ""))
        url = f"{self.base_url}/browse/{key}" if key else ""

        return JiraIssue(
            key=key,
            summary=str(fields.get("summary", "")),
            status=status,
            assignee=assignee,
            description=description,
            issuetype=issuetype,
            url=url,
            created=created_str,
            custom_fields=custom_fields_data,
        )
