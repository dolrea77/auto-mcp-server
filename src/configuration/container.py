from dataclasses import dataclass
from functools import lru_cache

from src.adapters.outbound.git_local_adapter import GitLocalAdapter
from src.adapters.outbound.in_memory_session_store import InMemorySessionStore
from src.adapters.outbound.jira_adapter import JiraAdapter
from src.adapters.outbound.wiki_adapter import WikiAdapter
from src.adapters.outbound.yaml_template_repository import YamlTemplateRepository
from src.application.services.template_renderer import TemplateRenderer
from src.application.use_cases.create_jira_filter import CreateJiraFilterUseCase
from src.application.use_cases.create_wiki_issue_page import CreateWikiIssuePageUseCase
from src.application.use_cases.create_wiki_page_with_content import CreateWikiPageWithContentUseCase
from src.application.use_cases.complete_jira_issue import CompleteJiraIssueUseCase
from src.application.use_cases.get_jira_issue_by_key import GetJiraIssueByKeyUseCase
from src.application.use_cases.get_jira_issues import GetJiraIssuesUseCase
from src.application.use_cases.get_project_meta import GetProjectMetaUseCase
from src.application.use_cases.reload_templates import ReloadTemplatesUseCase
from src.application.use_cases.transition_jira_issue import TransitionJiraIssueUseCase
from src.application.use_cases.wiki_generation_orchestrator import WikiGenerationOrchestrator
from src.configuration.settings import Settings, build_settings


@dataclass(frozen=True)
class Container:
    settings: Settings
    get_jira_issues_use_case: GetJiraIssuesUseCase
    get_jira_issue_by_key_use_case: GetJiraIssueByKeyUseCase
    create_jira_filter_use_case: CreateJiraFilterUseCase
    get_project_meta_use_case: GetProjectMetaUseCase
    complete_jira_issue_use_case: CompleteJiraIssueUseCase
    transition_jira_issue_use_case: TransitionJiraIssueUseCase
    create_wiki_issue_page_use_case: CreateWikiIssuePageUseCase
    create_wiki_page_with_content_use_case: CreateWikiPageWithContentUseCase
    wiki_orchestrator: WikiGenerationOrchestrator
    reload_templates_use_case: ReloadTemplatesUseCase
    template_renderer: TemplateRenderer
    diff_collector: GitLocalAdapter


@lru_cache(maxsize=1)
def build_container() -> Container:
    settings = build_settings()

    jira_adapter = JiraAdapter(
        base_url=settings.jira_base_url,
        user=settings.user_id,
        password=settings.user_password,
    )

    wiki_adapter = WikiAdapter(
        base_url=settings.wiki_base_url or settings.jira_base_url,
        user=settings.user_id,
        password=settings.user_password,
    )

    # 새 컴포넌트: 템플릿 저장소 + 렌더러
    template_repo = YamlTemplateRepository(yaml_path=settings.template_yaml_path)
    template_renderer = TemplateRenderer(template_repo=template_repo)

    # 새 컴포넌트: Git diff 수집기 + 세션 저장소
    diff_collector = GitLocalAdapter()
    session_store = InMemorySessionStore(ttl_minutes=30)

    # Jira Use Cases
    get_jira_issues_use_case = GetJiraIssuesUseCase(
        jira_port=jira_adapter,
        jira_user=settings.user_id,
    )

    get_jira_issue_by_key_use_case = GetJiraIssueByKeyUseCase(
        jira_port=jira_adapter,
    )

    create_jira_filter_use_case = CreateJiraFilterUseCase(
        jira_port=jira_adapter,
    )

    get_project_meta_use_case = GetProjectMetaUseCase(
        jira_port=jira_adapter,
    )

    complete_jira_issue_use_case = CompleteJiraIssueUseCase(
        jira_port=jira_adapter,
    )

    transition_jira_issue_use_case = TransitionJiraIssueUseCase(
        jira_port=jira_adapter,
    )

    # Wiki Use Cases (기존 - claude_md_loader 제거됨)
    create_wiki_issue_page_use_case = CreateWikiIssuePageUseCase(
        wiki_adapter=wiki_adapter,
        root_page_id=settings.wiki_issue_root_page_id,
        space_key=settings.wiki_issue_space_key,
        template_renderer=template_renderer,
        diff_collector=diff_collector,
    )

    create_wiki_page_with_content_use_case = CreateWikiPageWithContentUseCase(
        wiki_adapter=wiki_adapter,
        root_page_id=settings.wiki_issue_root_page_id,
        space_key=settings.wiki_issue_space_key,
        template_renderer=template_renderer,
    )

    # Wiki 오케스트레이터 (상태머신 기반)
    wiki_orchestrator = WikiGenerationOrchestrator(
        wiki_port=wiki_adapter,
        session_store=session_store,
        template_renderer=template_renderer,
        diff_collector=diff_collector,
        root_page_id=settings.wiki_issue_root_page_id,
        space_key=settings.wiki_issue_space_key,
        jira_port=jira_adapter,
    )

    # 템플릿 핫 리로드
    reload_templates_use_case = ReloadTemplatesUseCase(
        template_repo=template_repo,
    )

    return Container(
        settings=settings,
        get_jira_issues_use_case=get_jira_issues_use_case,
        get_jira_issue_by_key_use_case=get_jira_issue_by_key_use_case,
        create_jira_filter_use_case=create_jira_filter_use_case,
        get_project_meta_use_case=get_project_meta_use_case,
        complete_jira_issue_use_case=complete_jira_issue_use_case,
        transition_jira_issue_use_case=transition_jira_issue_use_case,
        create_wiki_issue_page_use_case=create_wiki_issue_page_use_case,
        create_wiki_page_with_content_use_case=create_wiki_page_with_content_use_case,
        wiki_orchestrator=wiki_orchestrator,
        reload_templates_use_case=reload_templates_use_case,
        template_renderer=template_renderer,
        diff_collector=diff_collector,
    )


def clear_container() -> None:
    build_container.cache_clear()
