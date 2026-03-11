import logging

import httpx

from src.domain.diagram import DiagramResult

logger = logging.getLogger(__name__)

# Kroki가 지원하는 다이어그램 타입
SUPPORTED_TYPES = {
    "mermaid", "plantuml", "c4plantuml", "ditaa",
    "erd", "graphviz", "nomnoml", "svgbob",
    "vega", "vegalite", "wavedrom", "bpmn",
    "bytefield", "excalidraw", "pikchr",
}


class KrokiAdapter:
    """Kroki 다이어그램 렌더링 서비스 Outbound Adapter"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def render(
        self,
        diagram_type: str,
        code: str,
        output_format: str = "svg",
    ) -> DiagramResult:
        """다이어그램 코드를 SVG/PNG로 렌더링한다."""
        if diagram_type not in SUPPORTED_TYPES:
            raise RuntimeError(
                f"지원하지 않는 다이어그램 타입: '{diagram_type}'. "
                f"지원 목록: {', '.join(sorted(SUPPORTED_TYPES))}"
            )

        url = f"{self.base_url}/{diagram_type}/{output_format}"
        content_type = "image/svg+xml" if output_format == "svg" else f"image/{output_format}"

        logger.info("Kroki 렌더링 요청: type=%s, format=%s", diagram_type, output_format)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    content=code.encode("utf-8"),
                    headers={"Content-Type": "text/plain"},
                    timeout=30.0,
                )
                response.raise_for_status()
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Kroki 서버 연결 실패: {self.base_url}\n"
                f"Docker 컨테이너가 실행 중인지 확인하세요."
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Kroki 렌더링 실패 (HTTP {e.response.status_code}): "
                f"{e.response.text[:300]}"
            ) from e

        filename = f"diagram.{output_format}"
        logger.info("✅ Kroki 렌더링 완료: %d bytes", len(response.content))

        return DiagramResult(
            svg_data=response.content,
            diagram_type=diagram_type,
            filename=filename,
            content_type=content_type,
        )

    async def health_check(self) -> bool:
        """Kroki 서버 헬스 체크."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    timeout=5.0,
                )
                return response.status_code == 200
        except Exception:
            return False
