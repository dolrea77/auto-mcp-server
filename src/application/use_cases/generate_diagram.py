import logging

from src.application.ports.diagram_port import DiagramPort
from src.domain.diagram import DiagramResult

logger = logging.getLogger(__name__)


class GenerateDiagramUseCase:
    """다이어그램 코드를 이미지로 렌더링하는 유스케이스."""

    def __init__(self, diagram_port: DiagramPort):
        self._diagram = diagram_port

    async def execute(
        self,
        diagram_type: str,
        code: str,
        output_format: str = "svg",
    ) -> DiagramResult:
        """다이어그램을 렌더링한다.

        Args:
            diagram_type: "mermaid", "plantuml", "c4plantuml" 등
            code: 다이어그램 소스 코드
            output_format: "svg" (기본) 또는 "png"

        Returns:
            DiagramResult (svg_data, filename, content_type)
        """
        logger.info("다이어그램 생성: type=%s, format=%s", diagram_type, output_format)
        return await self._diagram.render(diagram_type, code, output_format)
