from typing import Protocol

from src.domain.wiki_workflow import WikiSession


class WikiSessionStorePort(Protocol):
    """Wiki 생성 워크플로우 세션 저장소 계약"""

    def save(self, session: WikiSession) -> None:
        """세션을 저장합니다."""
        ...

    def get(self, session_id: str) -> WikiSession | None:
        """세션을 조회합니다. 만료된 세션은 None을 반환합니다."""
        ...

    def delete(self, session_id: str) -> None:
        """세션을 삭제합니다."""
        ...

    def cleanup_expired(self) -> int:
        """만료된 세션을 정리합니다. 삭제된 세션 수를 반환합니다."""
        ...
