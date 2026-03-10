import logging

import mistune
from jinja2 import BaseLoader, Environment, Undefined
from markupsafe import Markup

from src.application.ports.template_repository_port import TemplateRepositoryPort

logger = logging.getLogger(__name__)


class LoggingUndefined(Undefined):
    """미치환 변수 접근 시 경고 로그를 출력합니다."""
    def __str__(self) -> str:
        logger.warning("템플릿 미치환 변수: %s", self._undefined_name)
        return ""


class _ConfluenceRenderer(mistune.HTMLRenderer):
    """Confluence Storage Format 호환 마크다운 렌더러.

    변경 내용 요약은 <h2> 아래에 위치하므로,
    마크다운 heading을 최소 h3부터 시작하도록 오프셋합니다.
    """
    _MIN_HEADING = 3
    _MAX_HEADING = 6

    def heading(self, text: str, level: int, **attrs) -> str:
        target = min(max(level + 1, self._MIN_HEADING), self._MAX_HEADING)
        return f"<h{target}>{text}</h{target}>\n"

    def block_code(self, code: str, info=None, **attrs) -> str:
        language = info.strip() if info else "text"
        safe_code = code.replace("]]>", "]]]]><![CDATA[>")
        return (
            f'<ac:structured-macro ac:name="code">\n'
            f'  <ac:parameter ac:name="language">{language}</ac:parameter>\n'
            f'  <ac:plain-text-body><![CDATA[{safe_code}]]></ac:plain-text-body>\n'
            f'</ac:structured-macro>\n'
        )


class TemplateRenderer:
    """Jinja2 기반 템플릿 렌더러"""

    def __init__(self, template_repo: TemplateRepositoryPort, author_name: str = ""):
        self._repo = template_repo
        self._author_name = author_name
        self._env = Environment(
            loader=BaseLoader(),
            undefined=LoggingUndefined,
            autoescape=True,
            keep_trailing_newline=True,
        )
        self._md = mistune.create_markdown(
            renderer=_ConfluenceRenderer(escape=True),
            plugins=['table', 'strikethrough'],
        )

    def render_workflow_body(self, workflow_type: str, variables: dict[str, str]) -> str:
        """워크플로우 템플릿을 렌더링합니다."""
        wiki_template = self._repo.get_workflow_template(workflow_type)
        template = self._env.from_string(wiki_template.body)
        rendered = template.render(**variables)
        logger.info("템플릿 렌더링 완료: workflow=%s, 길이=%d", workflow_type, len(rendered))
        return rendered

    def render_title(self, format_str: str, variables: dict[str, str]) -> str:
        """제목 형식 문자열을 렌더링합니다."""
        template = self._env.from_string(format_str)
        return template.render(**variables)

    def build_year_month_titles(self, year: int, month: int) -> tuple[str, str]:
        """년도/월 페이지 제목을 생성합니다."""
        title_formats = self._repo.get_title_formats()
        vars_ = {"YEAR": str(year), "MONTH": str(month), "MONTH_PADDED": f"{month:02d}", "AUTHOR_NAME": self._author_name}
        year_title = self.render_title(title_formats.year_format, vars_)
        month_title = self.render_title(title_formats.month_format, vars_)
        return year_title, month_title

    def render_change_summary_html(self, summary: str) -> str:
        """change_summary를 Confluence Storage Format HTML로 변환합니다.

        마크다운 형식의 텍스트를 적절한 HTML로 변환하며,
        heading 레벨은 h3부터 시작하도록 오프셋됩니다.
        이미 HTML인 콘텐츠는 그대로 통과시킵니다.
        """
        if not summary or not summary.strip():
            return Markup("<p>(변경 내용 없음)</p>")

        stripped = summary.strip()

        # 이미 HTML 태그로 시작하는 콘텐츠는 그대로 반환 (Markup으로 마킹)
        if stripped.startswith("<") and not stripped.startswith("< "):
            return Markup(stripped)

        # 마크다운 → Confluence HTML 변환 (결과는 안전한 HTML)
        return Markup(self._md(stripped).strip())
