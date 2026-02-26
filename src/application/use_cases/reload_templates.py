import logging

from src.application.ports.template_repository_port import TemplateRepositoryPort

logger = logging.getLogger(__name__)


class ReloadTemplatesUseCase:
    """Wiki 템플릿 캐시를 무효화하고 다시 로드하는 Use Case"""

    def __init__(self, template_repo: TemplateRepositoryPort):
        self._repo = template_repo

    def execute(self) -> dict:
        logger.info("템플릿 리로드 실행")
        self._repo.reload()

        # 검증: 로드 가능한지 확인
        title_fmts = self._repo.get_title_formats()
        wf_a = self._repo.get_workflow_template("workflow_a")
        wf_b = self._repo.get_workflow_template("workflow_b")

        return {
            "status": "success",
            "year_format": title_fmts.year_format,
            "month_format": title_fmts.month_format,
            "workflow_a_body_length": len(wf_a.body),
            "workflow_b_body_length": len(wf_b.body),
        }
