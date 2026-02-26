import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    app_env = os.getenv("APP_ENV", "local")
    # 프로젝트 루트 디렉토리 찾기 (src/configuration/settings.py -> ../../)
    project_root = Path(__file__).parent.parent.parent
    env_file = project_root / f".env.{app_env}"
    load_dotenv(env_file)


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
    max_diff_chars: int  # include_diff=true 시 diff 최대 문자수


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
        max_diff_chars=int(os.getenv("MAX_DIFF_CHARS", "30000")),
    )
