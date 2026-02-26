# auto-mcp-server

로컬 MCP(Model Context Protocol) 서버 프로젝트.

## Git 규칙
- GitHub에만 커밋 (GitLab push 금지)

## 아키텍처

Hexagonal Architecture (Ports & Adapters) 기반.

```
[MCP Inbound]  ← Claude
     ↓
[Use Cases] ↔ [Ports] ↔ [Outbound Adapters]
     ↓
 [Domain]
```

### 레이어 구조

| 레이어 | 위치 | 역할 |
|---|---|---|
| Domain | `src/domain/` | 핵심 도메인 엔티티 |
| Application | `src/application/` | Port 인터페이스, Use Case |
| Inbound | `src/adapters/inbound/mcp/` | MCP Tool 핸들러 |
| Outbound | `src/adapters/outbound/` | 외부 서비스 어댑터 |
| Config | `src/configuration/` | DI Container, Settings |

## 개발

```bash
# 설치 및 실행
pip install -r requirements.txt
export APP_ENV=local
python -m src
```

## 새 Tool 추가

1. `src/application/ports/` - Port Protocol 정의
2. `src/adapters/outbound/` - Adapter 구현
3. `src/application/use_cases/` - Use Case 작성
4. `src/configuration/container.py` - DI 등록
5. `src/adapters/inbound/mcp/tools.py` - MCP Tool 등록

## Wiki 페이지 생성

세 가지 도구로 Wiki 페이지를 생성할 수 있습니다:

| 도구 | 용도 |
|---|---|
| `collect_branch_commits` | 브랜치 커밋 수집 (베이스 브랜치 자동 탐지) |
| `create_wiki_issue_page` | Jira 이슈 완료 후 Wiki 생성 (브랜치명: `dev_{이슈키}`) |
| `create_wiki_page_with_content` | 브랜치명/MR/커밋 범위로 Wiki 생성 |

### ⚠️ 중요: 2단계 승인 프로세스

**모든 Wiki 생성은 반드시 사용자 승인이 필요합니다!**

1. **준비 단계**: `create_wiki_issue_page` 또는 `create_wiki_page_with_content` 호출
   - 즉시 생성되지 않음
   - 프리뷰 + 승인 토큰 반환
   - 상태: `WAIT_APPROVAL`

2. **승인 단계**: `approve_wiki_generation` 호출
   - 세션 ID + 승인 토큰 일치 시에만 생성
   - 실제 Confluence Wiki 페이지 생성
   - 상태: `DONE`

### 공통 프로세스

1. **커밋 수집**:
   - **권장**: `collect_branch_commits` 도구 사용 (베이스 브랜치 자동 탐지)
   - 대안: `git log`, GitLab MCP 등으로 직접 수집
2. **Diff 수집**: `git diff`, `git show`, GitLab MCP로 변경 내용 획득
3. **분석**: 커밋 메시지 + diff를 분석하여 `change_summary` 작성
   - 변경 목적 (버그 수정/기능 추가/리팩토링)
   - 주요 변경 파일 및 역할
   - 비즈니스 영향
4. **프리뷰 생성**: MCP 도구 호출 → 프리뷰 + 승인 토큰 받음
5. **승인 확인**: 사용자에게 프리뷰 보고 후 승인 여부 확인
6. **Wiki 생성**: 승인 시 `approve_wiki_generation` 호출하여 실제 페이지 생성

### Diff 수집 우선순위

1. `git diff dev...{브랜치}` (브랜치 존재 시)
2. `git show {머지커밋SHA}` (브랜치 삭제 시)
3. GitLab MCP `get_merge_request_changes()`
4. `git log dev --merges --oneline` (수동 식별)

### 베이스 브랜치 자동 탐지

GitLocalAdapter는 다음 순서로 베이스 브랜치를 자동 탐지합니다:
1. `dev` → 2. `origin/dev` → 3. `develop` → 4. `origin/develop` → 5. `main` → 6. `master`

## 코드 컨벤션

- 설정/엔티티: `@dataclass(frozen=True)`
- 외부 계약: `typing.Protocol`
- DI Container: `@lru_cache` 싱글톤
- 비동기 I/O: `async/await`
- CPU 바운드: `asyncio.to_thread()`

## 템플릿 설정

Wiki 템플릿은 `config/wiki_templates.yaml`에서 관리.
`reload_wiki_templates` MCP 도구로 핫 리로드 가능.
