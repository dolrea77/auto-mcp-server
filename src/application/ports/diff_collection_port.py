from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiffResult:
    """diff 수집 결과"""
    commits_raw: str
    diff_raw: str
    diff_stat: str  # git diff --stat 결과 (파일별 변경 통계)
    branch_name: str
    source: str  # "local_git" | "gitlab_api" | "manual"


class DiffCollectionPort(Protocol):
    """코드 diff 수집 계약"""

    async def collect_by_branch(self, branch_name: str) -> DiffResult:
        """브랜치명 기반으로 커밋 목록과 diff를 수집합니다."""
        ...

    async def collect_by_commit_range(self, from_ref: str, to_ref: str) -> DiffResult:
        """커밋 범위 기반으로 diff를 수집합니다."""
        ...
