import logging
import subprocess
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server

from src.adapters.inbound.mcp.tools import register_tools
from src.configuration.container import build_container, clear_container


def setup_logging():
    """로깅 설정: stderr와 파일 두 곳에 로그 출력"""
    # 로그 디렉토리 생성
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # 로그 파일 경로
    log_file = log_dir / "mcp-server.log"

    # 로그 포맷
    formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 1. stderr 핸들러 (Claude Desktop 로그에 표시)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    # 2. 파일 핸들러 (로그 파일에 저장, 최대 10MB, 5개 백업)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return logging.getLogger(__name__)


logger = setup_logging()


def _start_kroki(container_name: str) -> bool:
    """Kroki Docker 컨테이너를 시작한다. 성공 여부를 반환."""
    try:
        result = subprocess.run(
            ["docker", "start", container_name],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Kroki 컨테이너 시작 중 오류: %s", e)
        return False


def _stop_kroki(container_name: str) -> None:
    """Kroki Docker 컨테이너를 정지한다."""
    try:
        subprocess.run(
            ["docker", "stop", container_name],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Kroki 컨테이너 정지 중 오류: %s", e)


async def main() -> None:
    try:
        logger.info("=" * 60)
        logger.info("MCP 서버 초기화 시작")

        container = build_container()
        logger.info("✅ Container 빌드 완료")
        logger.info("서버 이름: %s", container.settings.server_name)
        logger.info("환경: %s", container.settings.app_env)
        logger.info("Jira URL: %s", container.settings.jira_base_url)
        logger.info("Jira User: %s", container.settings.user_id)
        logger.info("Template YAML: %s", container.settings.template_yaml_path)

        # Kroki Docker 컨테이너 시작 (활성화된 경우만)
        kroki_started = False
        if container.settings.kroki_enabled:
            kroki_started = _start_kroki(container.settings.kroki_container_name)
            if kroki_started:
                logger.info("✅ Kroki 컨테이너 시작: %s", container.settings.kroki_container_name)
            else:
                logger.warning(
                    "⚠️ Kroki 컨테이너 시작 실패: %s - 다이어그램 기능이 제한될 수 있습니다",
                    container.settings.kroki_container_name,
                )

        app = Server(container.settings.server_name)
        register_tools(app)
        logger.info("✅ MCP Tools 등록 완료")

        logger.info("MCP 서버 시작 중...")
        logger.info("=" * 60)

        try:
            async with stdio_server() as (read_stream, write_stream):
                await app.run(read_stream, write_stream, app.create_initialization_options())
        finally:
            if kroki_started:
                _stop_kroki(container.settings.kroki_container_name)
                logger.info("Kroki 컨테이너 정지: %s", container.settings.kroki_container_name)
            if container.settings.app_env == "local":
                clear_container()
            logger.info("MCP 서버 종료")

    except Exception as e:
        logger.error("=" * 60)
        logger.error("MCP 서버 시작 실패!")
        logger.error("오류 타입: %s", type(e).__name__)
        logger.error("오류 메시지: %s", str(e))
        logger.error("=" * 60)
        traceback.print_exc(file=sys.stderr)
        raise
