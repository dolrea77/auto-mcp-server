from typing import Protocol

from src.domain.wiki_workflow import WikiTemplate, WikiTitleFormat


class TemplateRepositoryPort(Protocol):
    """Wiki 템플릿 저장소 계약"""

    def get_title_formats(self) -> WikiTitleFormat:
        """년도/월 페이지 제목 형식을 반환합니다."""
        ...

    def get_workflow_template(self, workflow_type: str) -> WikiTemplate:
        """워크플로우 유형에 해당하는 본문 템플릿을 반환합니다."""
        ...

    def reload(self) -> None:
        """캐시를 무효화하고 설정 파일을 다시 로드합니다."""
        ...
