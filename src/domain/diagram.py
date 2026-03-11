from dataclasses import dataclass


@dataclass(frozen=True)
class DiagramResult:
    """다이어그램 렌더링 결과"""

    svg_data: bytes  # SVG/PNG 바이너리 데이터
    diagram_type: str  # "mermaid", "plantuml" 등
    filename: str  # 첨부파일명 (예: "architecture-diagram.svg")
    content_type: str = "image/svg+xml"
