import logging
from datetime import datetime

from src.application.services.template_renderer import TemplateRenderer
from src.adapters.outbound.wiki_adapter import WikiAdapter
from src.application.use_cases.wiki_generation_orchestrator import _auto_summarize, _build_commit_list_html
from src.domain.wiki import WikiPageCreationResult

logger = logging.getLogger(__name__)


class CreateWikiPageWithContentUseCase:
    """
    워크플로우 B: 외부에서 수집한 커밋 내용으로 Wiki 페이지 생성

    Claude Code가 Bash 또는 GitLab MCP로 커밋 정보를 직접 수집한 후
    해당 내용을 파라미터로 받아 Wiki 페이지를 생성합니다.
    로컬 git 저장소에 의존하지 않습니다.
    """

    def __init__(
        self,
        wiki_adapter: WikiAdapter,
        root_page_id: str,
        space_key: str,
        template_renderer: TemplateRenderer,
    ):
        self.wiki_adapter = wiki_adapter
        self.root_page_id = root_page_id
        self.space_key = space_key
        self._renderer = template_renderer

    async def execute(
        self,
        page_title: str,
        commit_list: str,
        input_type: str = "브랜치명",
        input_value: str = "",
        base_date: str = "",
        change_summary: str = "",
    ) -> WikiPageCreationResult:
        """
        외부에서 수집한 커밋 정보로 Wiki 페이지를 생성합니다.

        Args:
            page_title: Wiki 페이지 제목
            commit_list: 커밋 목록 (줄바꿈 구분 문자열)
            input_type: 입력 유형 설명 (예: "브랜치명", "커밋 범위", "GitLab MR")
            input_value: 브랜치명, 커밋 범위, MR 번호 등 원본 값
            base_date: 기준 날짜 (YYYY-MM-DD). 비어있으면 오늘 날짜 사용
            change_summary: 변경 내용 요약. 비어있으면 커밋 메시지에서 자동 생성

        Returns:
            WikiPageCreationResult
        """
        # 기준 날짜 결정
        if base_date:
            try:
                parsed_date = datetime.strptime(base_date, "%Y-%m-%d")
            except ValueError:
                logger.warning("날짜 형식 오류, 오늘 날짜 사용: %s", base_date)
                parsed_date = datetime.now()
        else:
            parsed_date = datetime.now()

        year = parsed_date.year
        month = parsed_date.month
        date_str = parsed_date.strftime("%Y-%m-%d")

        logger.info(
            "워크플로우 B Wiki 페이지 생성: title=%s, date=%d/%d",
            page_title, year, month,
        )

        # 커밋 목록을 HTML 형식으로 변환
        commit_list_html = _build_commit_list_html(commit_list)

        # 변경 요약 자동 생성 (제공되지 않은 경우)
        if not change_summary:
            change_summary = _auto_summarize(commit_list)

        # 년/월 페이지 제목 생성
        year_title, month_title = self._renderer.build_year_month_titles(year, month)

        # 년/월 페이지 조회 or 생성
        year_page_id, month_page_id = await self.wiki_adapter.get_or_create_year_month_page(
            root_page_id=self.root_page_id,
            year=year,
            month=month,
            space_key=self.space_key,
            year_title=year_title,
            month_title=month_title,
        )

        # 중복 페이지 확인
        existing = await self.wiki_adapter.find_page_by_title(month_page_id, page_title)
        if existing:
            raise RuntimeError(
                f"동일한 제목의 페이지가 이미 존재합니다: '{page_title}'\n"
                f"페이지 URL: {existing.url}"
            )

        # 템플릿 렌더링
        change_summary_html = self._renderer.render_change_summary_html(change_summary)
        body = self._renderer.render_workflow_body("workflow_b", {
            "INPUT_TYPE": input_type,
            "INPUT_VALUE": input_value or page_title,
            "BASE_DATE": date_str,
            "COMMIT_LIST": commit_list_html,
            "CHANGE_SUMMARY_HTML": change_summary_html,
        })

        # 페이지 생성
        page = await self.wiki_adapter.create_page(
            parent_page_id=month_page_id,
            title=page_title,
            body=body,
            space_key=self.space_key,
        )

        logger.info("Wiki 페이지 생성 완료 (B): %s", page.url)

        return WikiPageCreationResult(
            page_id=page.id,
            title=page.title,
            url=page.url,
            parent_page_id=month_page_id,
            year_page_id=year_page_id,
            month_page_id=month_page_id,
        )
