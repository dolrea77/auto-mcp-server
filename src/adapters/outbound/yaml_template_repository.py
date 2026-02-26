import logging
from pathlib import Path

import yaml

from src.domain.wiki_workflow import WikiTemplate, WikiTitleFormat

logger = logging.getLogger(__name__)


class YamlTemplateRepository:
    """YAML 파일 기반 Wiki 템플릿 저장소 (mtime 캐시)"""

    def __init__(self, yaml_path: str | Path):
        self._path = Path(yaml_path)
        self._cache: dict | None = None
        self._cache_mtime: float = 0.0

    def _ensure_loaded(self) -> dict:
        """파일이 변경되었으면 다시 로드합니다."""
        try:
            current_mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            raise FileNotFoundError(
                f"템플릿 YAML 파일을 찾을 수 없습니다: {self._path}"
            )

        if self._cache is None or current_mtime > self._cache_mtime:
            logger.info("YAML 템플릿 로드: %s", self._path)
            with open(self._path, "r", encoding="utf-8") as f:
                self._cache = yaml.safe_load(f)
            self._cache_mtime = current_mtime
            logger.info(
                "YAML 템플릿 로드 완료: %d 워크플로우",
                len(self._cache.get("workflows", {})),
            )

        return self._cache

    def get_title_formats(self) -> WikiTitleFormat:
        data = self._ensure_loaded()
        formats = data.get("title_formats", {})
        return WikiTitleFormat(
            year_format=formats.get("year", "{{ YEAR }}년"),
            month_format=formats.get("month", "{{ MONTH }}월"),
        )

    def get_workflow_template(self, workflow_type: str) -> WikiTemplate:
        data = self._ensure_loaded()
        workflows = data.get("workflows", {})
        if workflow_type not in workflows:
            available = list(workflows.keys())
            raise ValueError(
                f"존재하지 않는 워크플로우: '{workflow_type}'. 사용 가능: {available}"
            )
        wf = workflows[workflow_type]
        return WikiTemplate(
            workflow_type=workflow_type,
            body=wf.get("body", ""),
            description=wf.get("description", ""),
        )

    def reload(self) -> None:
        """캐시를 강제로 무효화합니다."""
        logger.info("템플릿 캐시 강제 무효화")
        self._cache = None
        self._cache_mtime = 0.0
