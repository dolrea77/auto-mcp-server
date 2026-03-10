import logging
import threading
from datetime import datetime, timedelta

from src.domain.wiki_workflow import WikiSession

logger = logging.getLogger(__name__)

_DEFAULT_TTL_MINUTES = 30


class InMemorySessionStore:
    """In-memory Wiki 세션 저장소 (TTL 기반 자동 만료)"""

    def __init__(self, ttl_minutes: int = _DEFAULT_TTL_MINUTES):
        self._sessions: dict[str, WikiSession] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = threading.Lock()

    def save(self, session: WikiSession) -> None:
        session.touch()
        with self._lock:
            self._sessions[session.session_id] = session
        logger.info("세션 저장: id=%s, state=%s", session.session_id, session.state.value)

    def get(self, session_id: str) -> WikiSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                del self._sessions[session_id]
                logger.info("만료된 세션 삭제: id=%s", session_id)
                return None
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> int:
        now = datetime.now()
        with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.updated_at > self._ttl
            ]
            for sid in expired:
                del self._sessions[sid]
        if expired:
            logger.info("만료 세션 정리: %d건 삭제", len(expired))
        return len(expired)

    def _is_expired(self, session: WikiSession) -> bool:
        return datetime.now() - session.updated_at > self._ttl
