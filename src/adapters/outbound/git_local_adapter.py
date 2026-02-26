import asyncio
import logging
from dataclasses import dataclass

from src.application.ports.diff_collection_port import DiffResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _GitResult:
    """git 명령 실행 결과"""
    stdout: str
    returncode: int


@dataclass(frozen=True)
class _MergeExtraction:
    """머지 커밋에서 추출한 커밋/diff 결과"""
    commits_raw: str
    diff_raw: str
    diff_stat: str


class GitLocalAdapter:
    """로컬 git 명령을 사용하여 커밋/diff를 수집하는 Adapter"""

    _BASE_BRANCH_CANDIDATES = [
        "dev", "origin/dev",
        "develop", "origin/develop",
        "main", "origin/main",
        "master", "origin/master",
    ]

    # git 명령 실행 timeout (초)
    _GIT_TIMEOUT_SECONDS = 60

    def __init__(self, working_dir: str = "."):
        """
        Args:
            working_dir: git 명령을 실행할 작업 디렉토리 (기본값: 현재 디렉토리)
        """
        self.working_dir = working_dir

    async def _run_git(self, *args: str) -> _GitResult:
        """git 명령을 실행하고 결과를 반환합니다.

        Args:
            *args: git 하위 명령과 인자들 (예: "log", "--oneline")

        Returns:
            _GitResult: stdout 문자열과 returncode

        Raises:
            RuntimeError: timeout 초과 시
        """
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=self.working_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self._GIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"git 명령 timeout ({self._GIT_TIMEOUT_SECONDS}초 초과): git {' '.join(args)}"
            )
        return _GitResult(
            stdout=stdout.decode("utf-8").strip(),
            returncode=proc.returncode,
        )

    async def _extract_from_merge_commit(
        self, branch_name: str, *, raise_on_failure: bool = False,
    ) -> _MergeExtraction | None:
        """대상 브랜치(dev, master 등)에서 머지 커밋을 찾아 커밋/diff를 추출합니다.

        _BASE_BRANCH_CANDIDATES 순서대로 대상 브랜치를 순회하며,
        해당 브랜치의 머지 커밋에서 부모 SHA를 파싱하고 브랜치 전용 커밋과 diff를 수집합니다.

        Args:
            branch_name: 머지 커밋을 검색할 브랜치명
            raise_on_failure: True이면 실패 시 RuntimeError를 발생시킵니다

        Returns:
            추출 성공 시 _MergeExtraction, 실패 시 None (raise_on_failure=False일 때)

        Raises:
            RuntimeError: raise_on_failure=True이고 머지 커밋/부모 SHA를 찾을 수 없을 때
        """
        merge_lines: list[str] = []

        for target in self._BASE_BRANCH_CANDIDATES:
            check = await self._run_git("rev-parse", "--verify", target)
            if check.returncode != 0:
                continue

            merge_result = await self._run_git(
                "log", target, "--merges", "--oneline", f"--grep={branch_name}",
            )
            merge_lines = merge_result.stdout.splitlines()
            if merge_lines:
                logger.info("머지 커밋 발견: target=%s, branch=%s", target, branch_name)
                break

        if not merge_lines:
            if raise_on_failure:
                raise RuntimeError(f"브랜치를 찾을 수 없습니다: {branch_name}")
            return None

        # 첫 번째 머지 커밋 SHA
        merge_sha = merge_lines[0].split(" ", 1)[0]
        logger.info("머지 커밋 SHA: %s", merge_sha)

        # 머지 커밋 부모 SHA 추출 (%P = space-separated parent SHAs)
        parents_result = await self._run_git(
            "show", merge_sha, "--no-patch", "--format=%P",
        )
        parents = parents_result.stdout.split()
        if len(parents) < 2:
            if raise_on_failure:
                raise RuntimeError(f"머지 커밋 부모 SHA를 파싱할 수 없습니다: {merge_sha}")
            return None

        parent1, parent2 = parents[0], parents[1]

        # 브랜치 전용 커밋 목록 (parent1..parent2)
        log_result = await self._run_git(
            "log", f"{parent1}..{parent2}", "--oneline", "--no-merges",
        )

        # 머지 diff (머지가 dev에 추가한 변경사항만)
        diff_result = await self._run_git(
            "diff", f"{merge_sha}^1", merge_sha,
        )

        # 파일별 변경 통계
        stat_result = await self._run_git(
            "diff", "--stat", f"{merge_sha}^1", merge_sha,
        )

        return _MergeExtraction(
            commits_raw=log_result.stdout,
            diff_raw=diff_result.stdout,
            diff_stat=stat_result.stdout,
        )

    async def _find_base_branch(self) -> str:
        """베이스 브랜치를 찾습니다. dev → origin/dev → develop → origin/develop → main → master 순서로 폴백"""
        for candidate in self._BASE_BRANCH_CANDIDATES:
            result = await self._run_git("rev-parse", "--verify", candidate)
            if result.returncode == 0:
                logger.info("베이스 브랜치 발견: %s", candidate)
                return candidate

        logger.warning("베이스 브랜치를 찾을 수 없습니다. HEAD 사용")
        return "HEAD"

    async def collect_by_branch(self, branch_name: str) -> DiffResult:
        """브랜치명 기반 커밋 목록 + diff 수집.

        우선순위:
        1. 머지 커밋 기반 수집 (dev/master에서 검색, 오염 없음)
        2. 활성 브랜치에서 직접 수집 (아직 머지 안 된 경우)
        """
        # 1순위: 머지 커밋에서 추출 (깨끗한 커밋/diff)
        extraction = await self._extract_from_merge_commit(branch_name)
        if extraction is not None:
            logger.info("머지 커밋 기반 수집 성공: %s", branch_name)
            commits_raw = extraction.commits_raw
            diff_raw = extraction.diff_raw
            diff_stat = extraction.diff_stat
        else:
            # 2순위: 브랜치가 존재하면 직접 수집 (아직 머지 전)
            check = await self._run_git("rev-parse", "--verify", branch_name)
            if check.returncode == 0:
                commits_raw, diff_raw, diff_stat = await self._collect_from_existing_branch(branch_name)
            else:
                raise RuntimeError(f"브랜치를 찾을 수 없습니다: {branch_name}")

        logger.info(
            "로컬 git 수집 완료: branch=%s, commits=%d lines, diff=%d chars",
            branch_name, len(commits_raw.splitlines()), len(diff_raw),
        )

        return DiffResult(
            commits_raw=commits_raw,
            diff_raw=diff_raw,
            diff_stat=diff_stat,
            branch_name=branch_name,
            source="local_git",
        )

    async def _collect_from_existing_branch(self, branch_name: str) -> tuple[str, str, str]:
        """활성 브랜치에서 커밋/diff를 직접 수집합니다 (아직 머지 전).

        Returns:
            (commits_raw, diff_raw, diff_stat) 튜플
        """
        base_branch = await self._find_base_branch()
        logger.info("활성 브랜치 커밋 범위: %s..%s", base_branch, branch_name)

        log_result = await self._run_git(
            "log", f"{base_branch}..{branch_name}", "--oneline", "--no-merges",
        )

        diff_result = await self._run_git(
            "diff", f"{base_branch}...{branch_name}",
        )

        stat_result = await self._run_git(
            "diff", "--stat", f"{base_branch}...{branch_name}",
        )

        return log_result.stdout, diff_result.stdout, stat_result.stdout

    async def collect_by_commit_range(self, from_ref: str, to_ref: str) -> DiffResult:
        """커밋 범위 기반 diff 수집"""
        log_result = await self._run_git(
            "log", f"{from_ref}..{to_ref}", "--oneline", "--no-merges",
        )

        diff_result = await self._run_git(
            "diff", f"{from_ref}..{to_ref}",
        )

        stat_result = await self._run_git(
            "diff", "--stat", f"{from_ref}..{to_ref}",
        )

        return DiffResult(
            commits_raw=log_result.stdout,
            diff_raw=diff_result.stdout,
            diff_stat=stat_result.stdout,
            branch_name=f"{from_ref}..{to_ref}",
            source="local_git",
        )
