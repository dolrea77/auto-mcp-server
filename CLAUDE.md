# auto-mcp-server

로컬 MCP(Model Context Protocol) 서버 프로젝트. Jira/Confluence Wiki 연동 및 Git 브랜치 분석을 자동화한다.

## Git 규칙
- GitHub에만 커밋 (GitLab push 금지)

## 아키텍처

Hexagonal Architecture (Ports & Adapters) 기반. MCP 프로토콜(stdin/stdout)로 Claude와 통신한다.

```
Claude ──stdin/stdout──► [MCP Inbound: tools.py]
                              ↓
                        [Use Cases (10)]
                              ↓
                        [Ports (5 Protocol)]
                              ↓
                  [Outbound Adapters (5)]
                     ↓         ↓         ↓
                  Jira API  Confluence  Local Git
```

### 레이어 구조

| 레이어 | 위치 | 역할 | 파일 수 |
|---|---|---|---|
| Domain | `src/domain/` | 핵심 도메인 엔티티, 워크플로우 상태머신 | 3 |
| Ports | `src/application/ports/` | Protocol 인터페이스 (외부 계약) | 5 |
| Services | `src/application/services/` | 템플릿 렌더링 | 1 |
| Use Cases | `src/application/use_cases/` | 비즈니스 로직 | 10 |
| Inbound | `src/adapters/inbound/mcp/` | MCP Tool 핸들러 (16개 도구) | 1 |
| Outbound | `src/adapters/outbound/` | 외부 서비스 어댑터 | 5 |
| Config | `src/configuration/` | DI Container, Settings | 2 |
| Entry | `src/` | 서버 부트스트랩 | 2 |

총 Python 파일: **29개** (empty `__init__.py` 13개 포함)

---

## 프로젝트 파일 구조

```
auto-mcp-server/
├── config/
│   └── wiki_templates.yaml          # Jinja2 Wiki 본문 템플릿 (3종)
├── src/
│   ├── __main__.py                  # asyncio.run(main()) 진입점
│   ├── main.py                      # Server 부트스트랩, 로깅, stdio_server
│   ├── adapters/
│   │   ├── inbound/mcp/
│   │   │   └── tools.py             # MCP Tool 핸들러 (16개 도구, ~1634줄)
│   │   └── outbound/
│   │       ├── git_local_adapter.py      # Git subprocess 어댑터
│   │       ├── jira_adapter.py           # Jira REST API v2 어댑터
│   │       ├── wiki_adapter.py           # Confluence REST API 어댑터
│   │       ├── in_memory_session_store.py # Wiki 세션 저장소 (TTL 30분)
│   │       └── yaml_template_repository.py # YAML 템플릿 리포지토리
│   ├── application/
│   │   ├── ports/
│   │   │   ├── diff_collection_port.py   # DiffResult + DiffCollectionPort
│   │   │   ├── jira_port.py              # JiraPort
│   │   │   ├── wiki_port.py              # WikiPort
│   │   │   ├── wiki_session_store_port.py # WikiSessionStorePort
│   │   │   └── template_repository_port.py # TemplateRepositoryPort
│   │   ├── services/
│   │   │   └── template_renderer.py      # Jinja2 + mistune 렌더러
│   │   └── use_cases/
│   │       ├── get_jira_issue_by_key.py
│   │       ├── get_jira_issues.py
│   │       ├── get_project_meta.py
│   │       ├── complete_jira_issue.py
│   │       ├── transition_jira_issue.py
│   │       ├── create_jira_filter.py
│   │       ├── create_wiki_issue_page.py      # Legacy 직접 실행 (미사용)
│   │       ├── create_wiki_page_with_content.py # Legacy 직접 실행 (미사용)
│   │       ├── wiki_generation_orchestrator.py  # 핵심: 상태머신 오케스트레이터
│   │       └── reload_templates.py
│   ├── configuration/
│   │   ├── settings.py              # @dataclass Settings (12 필드)
│   │   └── container.py             # DI Container (@lru_cache 싱글톤)
│   └── domain/
│       ├── jira.py                  # JiraIssue, JiraFilter, JiraProjectMeta
│       ├── wiki.py                  # WikiPage, WikiPageWithContent, WikiPageCreationResult
│       └── wiki_workflow.py         # WikiSession 상태머신, WorkflowType/State enum
├── .env.local.example               # 환경변수 템플릿
├── requirements.txt                 # 7개 의존성
└── README.md
```

---

## 의존성 (requirements.txt)

| 패키지 | 버전 | 용도 |
|---|---|---|
| `mcp[cli]` | 1.9.4 | MCP 서버 프레임워크 (stdio 통신) |
| `python-dotenv` | 1.2.1 | `.env` 파일 로딩 |
| `pydantic` | 2.12.5 | 데이터 검증 |
| `httpx` | 0.28.1 | 비동기 HTTP 클라이언트 (Jira/Confluence) |
| `Jinja2` | 3.1.6 | Wiki 템플릿 렌더링 |
| `PyYAML` | 6.0.2 | `wiki_templates.yaml` 파싱 |
| `mistune` | 3.1.3 | 마크다운 → Confluence HTML 변환 |

---

## 실행

```bash
pip install -r requirements.txt
export APP_ENV=local    # .env.local 로드
python -m src           # stdin/stdout MCP 서버 시작
```

로깅: stderr + `logs/mcp-server.log` (10MB, 5백업 로테이션)

---

## MCP 도구 목록 (16개)

### Jira 도구 (6개)

| # | 도구 | 설명 | 필수 파라미터 | 선택 파라미터 |
|---|---|---|---|---|
| 1 | `get_jira_issue` | 특정 이슈 조회 | `key` | - |
| 2 | `get_jira_issues` | 내 이슈 목록 조회 | - | `statuses[]`, `project_key` |
| 3 | `get_jira_project_meta` | 프로젝트 이슈유형/상태 조회 | `project_key` | - |
| 4 | `complete_jira_issue` | 이슈 완료 처리 | `key` | `due_date` |
| 5 | `transition_jira_issue` | 이슈 상태 전환 | `key`, `target_status` | - |
| 6 | `create_jira_filter` | JQL 필터 생성 | `name`, `jql` | - |

### Git 도구 (2개)

| # | 도구 | 설명 | 필수 파라미터 | 선택 파라미터 |
|---|---|---|---|---|
| 7 | `collect_branch_commits` | 브랜치 커밋/diff 수집 (Wiki 준비) | `branch_name` | `repository_path`, `include_diff` |
| 8 | `analyze_branch_changes` | 브랜치 변경사항 분석 (범용 Q&A) | `branch_name` | `repository_path` |

### Wiki 도구 (8개)

| # | 도구 | 워크플로우 | 설명 | 필수 파라미터 |
|---|---|---|---|---|
| 9 | `create_wiki_issue_page` | A | Jira 이슈 기반 Wiki 생성 | `issue_key`, `issue_title` |
| 10 | `create_wiki_page_with_content` | B | 외부 커밋으로 Wiki 생성 | `page_title`, `commit_list` |
| 11 | `create_wiki_custom_page` | C | 자유 형식 Wiki 생성 | `page_title`, `content`, `parent_page_id`/`parent_page_title` |
| 12 | `update_wiki_page` | Update | 기존 Wiki 수정 | `body`, `page_id`/`page_title` |
| 13 | `get_wiki_page` | - | Wiki 페이지 조회 (본문 포함) | `page_id`/`page_title` |
| 14 | `get_wiki_generation_status` | - | 세션 상태 조회 | `session_id` |
| 15 | `approve_wiki_generation` | - | Wiki 생성/수정 최종 승인 | `session_id`, `approval_token` |
| 16 | `reload_wiki_templates` | - | 템플릿 YAML 핫 리로드 | - |

---

## 도메인 엔티티

### Jira 도메인 (`src/domain/jira.py`)

| 클래스 | 필드 | 비고 |
|---|---|---|
| `JiraIssue` | `key, summary, status, assignee, description, issuetype, url, created, custom_end_date` | `created`=BNFMT 기준일, `custom_end_date`=BNFDEV customfield_10833 |
| `JiraFilter` | `id, name, jql, url` | 저장된 JQL 필터 |
| `JiraProjectMeta` | `project_key, issuetype_statuses: dict[str, list[str]]` | 이슈유형별 상태 목록 |

### Wiki 도메인 (`src/domain/wiki.py`)

| 클래스 | 필드 | 비고 |
|---|---|---|
| `WikiPage` | `id, title, url, space_key` | 경량 참조 (본문 없음) |
| `WikiPageWithContent` | `id, title, url, space_key, body, version` | 조회/수정용 (Storage Format HTML) |
| `WikiPageCreationResult` | `page_id, title, url, parent_page_id, year_page_id, month_page_id, was_updated` | 생성 결과 |

### 워크플로우 상태머신 (`src/domain/wiki_workflow.py`)

**WorkflowType enum:**

| 값 | 용도 |
|---|---|
| `WORKFLOW_A` | Jira 이슈 기반 Wiki 생성 |
| `WORKFLOW_B` | 브랜치/MR/커밋 범위 Wiki 생성 |
| `WORKFLOW_C` | 자유 형식 Wiki 생성 (커스텀 부모 페이지) |
| `UPDATE_PAGE` | 기존 페이지 수정 |

**WorkflowState 전이:**

```
INIT → COLLECT_COMMITS → COLLECT_DIFF → ANALYZE_DIFF → RENDER_PREVIEW → WAIT_APPROVAL → CREATE_WIKI → DONE
                                                                              ↘ FAILED
```

**WikiSession** — 유일한 mutable dataclass. 워크플로우 전체 상태를 담는 세션 객체:
- 워크플로우별 전용 필드 (A: `issue_key` 등, B: `page_title` 등, C: `parent_page_id` 등)
- 공유 필드: `commit_list_raw/html, diff_raw, diff_stat, change_summary, rendered_preview`
- Jira 보강: `jira_issues: list[dict]`
- 승인 게이트: `approval_token` (UUID), `approval_expires_at` (30분 TTL)

**유틸리티 함수:**
- `extract_jira_issue_keys(text)` — 텍스트에서 `BNFDEV-NNN`/`BNFMT-NNN` 추출 (중복 제거)
- `get_wiki_date_for_issue(issue_data)` — BNFDEV: `custom_end_date`, BNFMT: `created`, 기타: `""`

---

## Port 인터페이스 (5개 Protocol)

### JiraPort (`src/application/ports/jira_port.py`)

| 메서드 | 반환 | 비고 |
|---|---|---|
| `search_issues(jql)` | `list[JiraIssue]` | JQL 기반 검색 |
| `create_filter(name, jql)` | `JiraFilter` | 즐겨찾기 필터 생성 |
| `get_project_meta(project_key)` | `JiraProjectMeta` | 이슈유형/상태 메타 |
| `complete_issue(key, due_date)` | `dict` | 완료 전환 + 종료일 설정 |
| `transition_issue(key, target_status)` | `dict` | 임의 상태 전환 |

### WikiPort (`src/application/ports/wiki_port.py`)

| 메서드 | 반환 | 비고 |
|---|---|---|
| `get_child_pages(page_id)` | `list[WikiPage]` | 자식 페이지 목록 |
| `create_page(parent_page_id, title, body, space_key)` | `WikiPage` | 페이지 생성 |
| `get_or_create_year_month_page(...)` | `tuple[str, str]` | 년/월 계층 보장 → `(year_id, month_id)` |
| `find_page_by_title(parent_page_id, title)` | `WikiPage \| None` | 부모 하위 제목 검색 |
| `search_page_by_title(title, space_key)` | `WikiPage \| None` | Space 전체 제목 검색 |
| `get_page_with_content(page_id)` | `WikiPageWithContent` | 본문 + 버전 조회 |
| `update_page(page_id, title, body, version, space_key)` | `WikiPage` | 페이지 수정 (version+1) |

### DiffCollectionPort (`src/application/ports/diff_collection_port.py`)

| 메서드 | 반환 | 비고 |
|---|---|---|
| `collect_by_branch(branch_name)` | `DiffResult` | 브랜치 커밋/diff 수집 |
| `collect_by_commit_range(from_ref, to_ref)` | `DiffResult` | 임의 ref 범위 diff |

`DiffResult`: `commits_raw, diff_raw, diff_stat, branch_name, source` (frozen dataclass)

### WikiSessionStorePort (`src/application/ports/wiki_session_store_port.py`)

동기 메서드: `save(session)`, `get(session_id)`, `delete(session_id)`, `cleanup_expired()`

### TemplateRepositoryPort (`src/application/ports/template_repository_port.py`)

동기 메서드: `get_title_formats()`, `get_workflow_template(workflow_type)`, `reload()`

---

## Outbound 어댑터 (5개)

### JiraAdapter (`src/adapters/outbound/jira_adapter.py`)

- **인증**: HTTP Basic Auth (`httpx.AsyncClient(auth=...)`)
- **타임아웃**: 30초
- **API**: Jira REST API v2 (`/rest/api/2/`)
- **헬퍼**: `_client()` 팩토리, `_request()` 범용 요청, `_raise_jira_error()` 상태코드별 에러
- **완료 상태 우선순위**: `배포완료(BNF) → DONE(BNF) → 검수완료(BNF) → 개발완료(BNF) → 답변완료(BNF) → 기획/설계 완료(BNF) → 완료(개발) → 완료(설계) → 완료`
- **종료일 필드 라우팅**: BNFDEV → `customfield_10833`, BNFMT → 미설정, 기타 → `duedate`

### WikiAdapter (`src/adapters/outbound/wiki_adapter.py`)

- **인증**: HTTP Basic Auth (인라인)
- **API**: Confluence REST API (`/rest/api/content/`)
- **본문 형식**: Confluence Storage Format (XML/HTML)
- **헬퍼**: `_request()`, `_build_page_url()`, `_raise_http_error()`
- **충돌 처리**: 409 → 생성 시 "동일한 제목 존재", 수정 시 "버전 충돌"

### GitLocalAdapter (`src/adapters/outbound/git_local_adapter.py`)

- **실행**: `asyncio.create_subprocess_exec("git", ...)`, 60초 타임아웃
- **헬퍼**: `_run_git(*args)` → `_GitResult(stdout, returncode)`
- **베이스 브랜치 탐지 순서**: `dev → origin/dev → develop → origin/develop → main → origin/main → master → origin/master`
- **수집 전략**:
  1. 머지 커밋 기반 (`_extract_from_merge_commit`) — 병합된 브랜치의 커밋/diff 추출
  2. 활성 브랜치 직접 비교 (`_collect_from_existing_branch`) — 3-dot diff

### InMemorySessionStore (`src/adapters/outbound/in_memory_session_store.py`)

- **저장소**: `dict[str, WikiSession]` + `threading.Lock`
- **TTL**: 30분 (lazy expiry on `get()` + eager `cleanup_expired()`)
- **동기**: `threading.Lock` 사용 (async가 아님)

### YamlTemplateRepository (`src/adapters/outbound/yaml_template_repository.py`)

- **캐시**: `mtime` 비교로 파일 변경 자동 감지 — 재시작 없이 핫 리로드
- **강제 리로드**: `reload()` → 캐시 무효화

---

## 서비스 레이어

### TemplateRenderer (`src/application/services/template_renderer.py`)

Jinja2 + mistune 기반 통합 렌더러.

| 메서드 | 설명 |
|---|---|
| `render_workflow_body(workflow_type, variables)` | YAML 워크플로우 템플릿 렌더링 |
| `render_title(format_str, variables)` | 제목 형식 문자열 렌더링 |
| `build_year_month_titles(year, month)` | 년/월 페이지 제목 생성 (AUTHOR_NAME 포함) |
| `render_change_summary_html(summary)` | 마크다운 → Confluence HTML 변환 |

**내부 클래스:**
- `LoggingUndefined` — Jinja2 미치환 변수 접근 시 경고 로그 출력 (빈 문자열 반환)
- `_ConfluenceRenderer(mistune.HTMLRenderer)` — heading h3~h6 오프셋, 코드블록을 `ac:structured-macro` 변환

---

## Use Cases (10개)

### Jira Use Cases (6개, 얇은 위임 패턴)

| Use Case | 입력 | 출력 | 핵심 로직 |
|---|---|---|---|
| `GetJiraIssueByKeyUseCase` | `key` | `dict \| None` | JQL `key="..."` 검색 → 첫 번째 결과 |
| `GetJiraIssuesUseCase` | `statuses[]`, `project_key` | `list[dict]` | 동적 JQL 조합 (assignee 고정) |
| `GetProjectMetaUseCase` | `project_key` | `dict` | 이슈유형별 상태 조회 |
| `CompleteJiraIssueUseCase` | `key`, `due_date` | `dict` | due_date 기본값=오늘, 완료 전환 |
| `TransitionJiraIssueUseCase` | `key`, `target_status` | `dict` | 직접 위임 |
| `CreateJiraFilterUseCase` | `name`, `jql` | `dict` | 직접 위임 |

### Wiki Use Cases (4개)

#### WikiGenerationOrchestrator (핵심)

**파일:** `src/application/use_cases/wiki_generation_orchestrator.py`

4가지 워크플로우를 상태머신으로 관리하는 중앙 오케스트레이터.

**주입 포트:** `WikiPort`, `WikiSessionStorePort`, `TemplateRenderer`, `DiffCollectionPort`, `JiraPort`

**워크플로우 A (`start_workflow_a`):**
```
이슈키 → Jira 보강 → 날짜 결정 → [커밋 자동 수집] → 프리뷰 렌더링 → WAIT_APPROVAL
```

**워크플로우 B (`start_workflow_b`):**
```
커밋 목록 → HTML 변환 → 자동 요약 → [Jira 보강] → 프리뷰 렌더링 → WAIT_APPROVAL
```

**워크플로우 C (`start_workflow_c`):**
```
마크다운 콘텐츠 → HTML 변환 → 프리뷰 렌더링 → WAIT_APPROVAL
```

**Update 워크플로우 (`start_update_workflow`):**
```
기존 페이지 조회 → 새 body 프리뷰 → WAIT_APPROVAL
```

**승인 (`approve`):**
```
세션 검증 → 토큰 검증 → 만료 검증 → 페이지 생성/수정 → DONE
```

**페이지 생성 라우팅 (`_create_wiki_page`):**
- A/B: 년/월 계층 → 중복 확인 → 생성 또는 `project_name` 있으면 기존 페이지에 섹션 추가
- C: 커스텀 부모 하위에 직접 생성
- Update: 낙관적 잠금 (최대 3회 재시도)

**공유 유틸리티 함수:**
- `_build_commit_list_html(commit_list)` — 줄 단위 `<li>` 변환 (최대 100개)
- `_auto_summarize(commit_list)` — 상위 5개 커밋 메시지 요약
- `_build_append_section(project_name, date_str, body_html)` — Confluence info 매크로 블록 생성

#### Legacy Use Cases (현재 오케스트레이터가 대체)

| Use Case | 비고 |
|---|---|
| `CreateWikiIssuePageUseCase` | Workflow A 직접 실행 (승인 없음) |
| `CreateWikiPageWithContentUseCase` | Workflow B 직접 실행 (승인 없음) |

#### ReloadTemplatesUseCase

동기 실행. `TemplateRepositoryPort.reload()` + 즉시 검증 (제목 형식 + 워크플로우 템플릿 확인).

---

## Wiki 2단계 승인 프로세스

**모든 Wiki 생성/수정은 반드시 사용자 승인이 필요합니다!**

### 1단계: 프리뷰 생성

`create_wiki_issue_page` / `create_wiki_page_with_content` / `create_wiki_custom_page` / `update_wiki_page` 호출
→ 프리뷰 HTML + `session_id` + `approval_token` 반환
→ 상태: `WAIT_APPROVAL`

### 2단계: 승인 후 실행

`approve_wiki_generation(session_id, approval_token)` 호출
→ 토큰 일치 + 30분 내 → 실제 Confluence API 호출
→ 상태: `DONE`

### 토큰 보안

- UUID4 기반 승인 토큰
- TTL 30분 (만료 시 워크플로우 재시작 필요)
- `_PREVIEW_WARNING` 상수로 에이전트의 자동 승인 방지

---

## tools.py 내부 유틸리티

### 상태 매핑 (`STATUS_MAPPING`)

영어 상태값을 한글 Jira 상태로 자동 변환:
- `"done"` → 완료, DONE(BNF), 개발완료(BNF) 등 9개
- `"in progress"` → 진행중(개발), 처리중(BNF) 등 4개
- `"to do"` / `"open"` → 할일, 개발접수(BNF) 등 5개
- `"pending"` → 보류(BNF), 패치대기(BNF)
- `"in review"` → 설계검수(BNF), 운영검수(BNF)

### 저장소 자동 탐지 (`_detect_repository`)

`GIT_REPOSITORIES` 환경변수에 등록된 저장소를 2단계로 탐색:
1. 머지 커밋 검색 (병합 완료된 브랜치)
2. 활성 ref 확인 (아직 존재하는 브랜치)

복수 매칭 시 disambiguation 메시지 → `repository_path` 명시 요구

### 스마트 Diff 필터링 (`_smart_truncate_diff`)

우선순위 기반 diff 자르기 (기본 30,000자):
- **High** (소스 코드): 모든 비-low/medium 확장자
- **Medium**: `.json, .yaml, .yml, .css, .scss, .md, .svg`
- **Low** (자동 생성): `package-lock.json, yarn.lock, .min.js, .generated.` 등

포함/제외 파일 리포트 생성. 민감 정보 마스킹 (`_mask_sensitive_in_diff`).

### 보안 기능

- **인자 마스킹**: `approval_token, commit_list, change_summary, content, jql, body` 로그 시 마스킹
- **저장소 허용 목록**: `GIT_REPOSITORIES` 설정 시 등록 외 경로 차단
- **diff 내 민감 정보**: API키/비밀번호/Bearer 토큰 regex 마스킹

---

## DI Container (`src/configuration/container.py`)

`Container` — `@dataclass(frozen=True)` + `@lru_cache(maxsize=1)` 싱글톤.

| 컴포넌트 | 클래스 | 의존성 |
|---|---|---|
| `jira_adapter` | `JiraAdapter` | base_url, user, password |
| `wiki_adapter` | `WikiAdapter` | wiki_base_url (jira 폴백), user, password |
| `template_repo` | `YamlTemplateRepository` | template_yaml_path |
| `template_renderer` | `TemplateRenderer` | template_repo, wiki_author_name |
| `diff_collector` | `GitLocalAdapter` | (없음) |
| `session_store` | `InMemorySessionStore` | ttl=30분 |
| `wiki_orchestrator` | `WikiGenerationOrchestrator` | 위 전체 + root_page_id, space_key |
| Jira use cases (6개) | 각 `*UseCase` | jira_adapter [, user_id] |
| Wiki use cases (2개 legacy) | 각 `*UseCase` | wiki_adapter + renderer + diff_collector |
| `reload_templates` | `ReloadTemplatesUseCase` | template_repo |

---

## Settings (`src/configuration/settings.py`)

`@dataclass(frozen=True)`. `.env.{APP_ENV}` 파일에서 로드.

| 필드 | 환경변수 | 기본값 | 설명 |
|---|---|---|---|
| `app_env` | `APP_ENV` | 필수 | local/dev |
| `server_name` | `SERVER_NAME` | 필수 | MCP 서버명 |
| `jira_base_url` | `JIRA_BASE_URL` | 필수 | Jira 서버 URL |
| `user_id` | `USER_ID` | 필수 | Jira/Confluence 인증 ID |
| `user_password` | `USER_PASSWORD` | 필수 | 인증 비밀번호 |
| `wiki_base_url` | `WIKI_BASE_URL` | `""` | Confluence URL (미설정 시 jira_base_url 사용) |
| `wiki_issue_space_key` | `WIKI_ISSUE_SPACE_KEY` | `""` | Confluence Space 키 |
| `wiki_issue_root_page_id` | `WIKI_ISSUE_ROOT_PAGE_ID` | `""` | Wiki 루트 페이지 ID |
| `template_yaml_path` | `TEMPLATE_YAML_PATH` | `config/wiki_templates.yaml` | 템플릿 파일 경로 |
| `git_repositories` | `GIT_REPOSITORIES` (JSON) | `{}` | `{프로젝트명: 경로}` 매핑 |
| `wiki_author_name` | `WIKI_AUTHOR_NAME` | `""` | Wiki 페이지 제목에 포함될 작성자명 |
| `max_diff_chars` | `MAX_DIFF_CHARS` | `30000` | Diff 최대 문자수 |

---

## 템플릿 설정 (`config/wiki_templates.yaml`)

### 제목 형식

```yaml
title_formats:
  year:  "[{{ AUTHOR_NAME }}] {{ YEAR }}"
  month: "[{{ AUTHOR_NAME }}] {{ YEAR }}-{{ MONTH_PADDED }}"
```

### 워크플로우 템플릿 (3종)

| 워크플로우 | 주요 변수 | 설명 |
|---|---|---|
| `workflow_a` | `ISSUE_KEY, ISSUE_TITLE, ASSIGNEE, RESOLUTION_DATE, COMMIT_LIST, CHANGE_SUMMARY_HTML, JIRA_*` | Jira 이슈 기반 |
| `workflow_b` | `INPUT_TYPE, INPUT_VALUE, BASE_DATE, COMMIT_LIST, CHANGE_SUMMARY_HTML, JIRA_ISSUES_HTML` | 커밋 직접 입력 |
| `workflow_c` | `CONTENT_HTML` | 자유 형식 (마크다운 → HTML 변환) |

`reload_wiki_templates` MCP 도구로 서버 재시작 없이 핫 리로드 가능.

---

## 에러 처리 전략

### 3단계 에러 처리 (tools.py)

1. **사전 검증 (early return)**: 필수 파라미터 누락, Wiki 설정 미완료, 저장소 경로 거부 → `[TextContent]` 직접 반환
2. **스코프 try/except**: Git 도구별 자체 catch → 포맷된 에러 TextContent
3. **외부 catch-all**: `call_tool` 전체 래핑 → 에러 타입/메시지 로깅 + stderr traceback + TextContent 반환

### 어댑터별 에러 패턴

| 어댑터 | 에러 전략 |
|---|---|
| `JiraAdapter` | `_raise_jira_error()` — HTTP 상태별 한국어 RuntimeError |
| `WikiAdapter` | `_raise_http_error()` — 401/403/404/409별 한국어 RuntimeError |
| `GitLocalAdapter` | 60초 타임아웃 kill, 브랜치 미발견 RuntimeError |
| `InMemorySessionStore` | 만료 시 `None` 반환 (silent) |

### 오케스트레이터 에러

| 상황 | 처리 |
|---|---|
| 세션 미발견 | `RuntimeError("세션을 찾을 수 없습니다")` |
| 잘못된 상태 전이 | `RuntimeError("잘못된 상태 전이")` |
| 토큰 불일치 | `RuntimeError("승인 토큰이 일치하지 않습니다")` |
| 토큰 만료 (30분) | `RuntimeError("승인 토큰이 만료")` → 워크플로우 재시작 필요 |
| 페이지 생성 실패 | `session.state = FAILED`, 예외 재전파 |
| Git 수집 실패 | 경고 로그 + 플레이스홀더 HTML (graceful degradation) |
| Jira 보강 실패 | 경고 로그 + 건너뜀 (non-fatal) |
| 중복 페이지 (project_name 없음) | RuntimeError |
| 버전 충돌 (update) | 최대 3회 낙관적 잠금 재시도 |

---

## 코드 컨벤션

- 설정/엔티티: `@dataclass(frozen=True)` (WikiSession만 예외 — mutable 상태머신)
- 타입 힌트: `X | None` (not `Optional[X]`), `from __future__` 미사용
- 외부 계약: `typing.Protocol` (구조적 서브타이핑)
- DI Container: `@lru_cache(maxsize=1)` 싱글톤
- Import: 최상위 레벨만 (인라인 import 금지, `list_tools()`의 `mcp.types.Tool` 제외)
- HTTP 헬퍼: `_request()` 패턴 (jira_adapter, wiki_adapter)
- Git 헬퍼: `_run_git()` 패턴 (git_local_adapter)
- 비동기 I/O: `async/await` (HTTP, subprocess)
- 동기: 세션 저장소 (`threading.Lock`), 템플릿 리포지토리 (파일 I/O)
- MCP Tool 스키마 (`list_tools()`): 외부 계약 — 리팩토링 시 수정 금지

## 새 Tool 추가

1. `src/application/ports/` — Port Protocol 정의
2. `src/adapters/outbound/` — Adapter 구현
3. `src/application/use_cases/` — Use Case 작성
4. `src/configuration/container.py` — DI 등록
5. `src/adapters/inbound/mcp/tools.py` — MCP Tool 등록 (`call_tool` 핸들러 + `list_tools` 스키마)
