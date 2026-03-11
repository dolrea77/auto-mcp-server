from typing import Protocol

from src.domain.diagram import DiagramResult


class DiagramPort(Protocol):
    """다이어그램 렌더링 서비스 계약 (Port)"""

    async def render(
        self,
        diagram_type: str,
        code: str,
        output_format: str = "svg",
    ) -> DiagramResult:
        """다이어그램 코드를 이미지로 렌더링한다."""
        ...

    async def health_check(self) -> bool:
        """Kroki 서버 접근 가능 여부를 확인한다."""
        ...
