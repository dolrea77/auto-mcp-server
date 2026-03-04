import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.domain.jira import JiraProjectConfig

logger = logging.getLogger(__name__)


def _load_env() -> None:
    app_env = os.getenv("APP_ENV", "local")
    # 프로젝트 루트 디렉토리 찾기 (src/configuration/settings.py -> ../../)
    project_root = Path(__file__).parent.parent.parent
    env_file = project_root / f".env.{app_env}"
    load_dotenv(env_file)


def _parse_project_configs(raw: str) -> list[JiraProjectConfig]:
    """JIRA_PROJECT_CONFIGS JSON을 파싱하여 JiraProjectConfig 리스트로 변환한다.

    필수 필드: key, due_date_field, wiki_date_field
    선택 필드: jira_custom_fields (기본 {}), statuses (기본 [])
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"JIRA_PROJECT_CONFIGS JSON 파싱 실패: {e}\n"
            f"올바른 JSON 배열 형식으로 설정해주세요."
        ) from e

    if not isinstance(data, list):
        raise RuntimeError(
            "JIRA_PROJECT_CONFIGS는 JSON 배열이어야 합니다. "
            f"현재 타입: {type(data).__name__}"
        )

    configs: list[JiraProjectConfig] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"JIRA_PROJECT_CONFIGS[{i}]는 객체여야 합니다. "
                f"현재 타입: {type(item).__name__}"
            )

        # 필수 필드 검증
        required_keys = ("key", "due_date_field", "wiki_date_field")
        missing = [k for k in required_keys if k not in item]
        if missing:
            raise RuntimeError(
                f"JIRA_PROJECT_CONFIGS[{i}] 필수 필드 누락: {', '.join(missing)}\n"
                f"필수 필드: key, due_date_field, wiki_date_field"
            )

        due_date_field = item["due_date_field"]
        if due_date_field is not None and not isinstance(due_date_field, str):
            raise RuntimeError(
                f"JIRA_PROJECT_CONFIGS[{i}].due_date_field는 문자열 또는 null이어야 합니다."
            )

        jira_custom_fields = item.get("jira_custom_fields", {})
        if not isinstance(jira_custom_fields, dict):
            raise RuntimeError(
                f"JIRA_PROJECT_CONFIGS[{i}].jira_custom_fields는 객체여야 합니다."
            )

        statuses = item.get("statuses", [])
        if not isinstance(statuses, list):
            raise RuntimeError(
                f"JIRA_PROJECT_CONFIGS[{i}].statuses는 배열이어야 합니다."
            )

        configs.append(JiraProjectConfig(
            key=str(item["key"]),
            due_date_field=due_date_field,
            wiki_date_field=str(item["wiki_date_field"]),
            jira_custom_fields={str(k): str(v) for k, v in jira_custom_fields.items()},
            statuses=[str(s) for s in statuses],
        ))

    return configs


@dataclass(frozen=True)
class Settings:
    app_env: str
    server_name: str
    jira_base_url: str
    user_id: str
    user_password: str
    wiki_base_url: str
    wiki_issue_space_key: str
    wiki_issue_root_page_id: str
    template_yaml_path: str
    git_repositories: dict[str, str]  # {프로젝트명: git경로} 매핑
    wiki_author_name: str  # Wiki 페이지 제목에 사용할 작성자 이름
    max_diff_chars: int  # include_diff=true 시 diff 최대 문자수
    jira_project_configs: list[JiraProjectConfig]  # 프로젝트별 Jira 설정


def build_settings() -> Settings:
    _load_env()

    required_vars = ("APP_ENV", "SERVER_NAME", "JIRA_BASE_URL", "USER_ID", "USER_PASSWORD")
    missing = [k for k in required_vars if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"필수 환경 변수 누락: {', '.join(missing)}")

    project_root = Path(__file__).parent.parent.parent
    default_template_path = str(project_root / "config" / "wiki_templates.yaml")

    git_repos_raw = os.getenv("GIT_REPOSITORIES", "{}")
    try:
        git_repositories = json.loads(git_repos_raw)
    except json.JSONDecodeError:
        git_repositories = {}

    # JIRA_PROJECT_CONFIGS 파싱 (미설정 시 에러 로그 + 빈 리스트)
    project_configs_raw = os.getenv("JIRA_PROJECT_CONFIGS", "")
    if not project_configs_raw:
        logger.error(
            "⚠️ JIRA_PROJECT_CONFIGS 환경변수가 설정되지 않았습니다. "
            "프로젝트별 Jira 기능(종료일 설정, Wiki 날짜 경로 등)이 비활성화됩니다. "
            ".env 파일에 JIRA_PROJECT_CONFIGS를 설정해주세요."
        )
        jira_project_configs: list[JiraProjectConfig] = []
    else:
        jira_project_configs = _parse_project_configs(project_configs_raw)

    return Settings(
        app_env=os.environ["APP_ENV"],
        server_name=os.environ["SERVER_NAME"],
        jira_base_url=os.environ["JIRA_BASE_URL"],
        user_id=os.environ["USER_ID"],
        user_password=os.environ["USER_PASSWORD"],
        wiki_base_url=os.getenv("WIKI_BASE_URL", ""),
        wiki_issue_space_key=os.getenv("WIKI_ISSUE_SPACE_KEY", ""),
        wiki_issue_root_page_id=os.getenv("WIKI_ISSUE_ROOT_PAGE_ID", ""),
        template_yaml_path=os.getenv("TEMPLATE_YAML_PATH", default_template_path),
        git_repositories=git_repositories,
        wiki_author_name=os.getenv("WIKI_AUTHOR_NAME", ""),
        max_diff_chars=int(os.getenv("MAX_DIFF_CHARS", "30000")),
        jira_project_configs=jira_project_configs,
    )
