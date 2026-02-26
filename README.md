# auto-mcp-server

Claude Desktop / Claude Code에서 사용할 수 있는 로컬 MCP(Model Context Protocol) 서버입니다.

**제공 기능:**
- ✅ Jira 이슈 조회/관리 (조회, 상태 전환, 완료 처리, 필터 생성)
- ✅ Confluence Wiki 페이지 자동 생성 (Jira 이슈 정리, 브랜치 커밋 기록, 자유 형식 커스텀 페이지, 멀티프로젝트 병합)
- ✅ Git 브랜치 커밋 수집 및 변경사항 분석 (베이스 브랜치 자동 탐지, 스마트 Diff 필터링)

---

## 📑 목차

1. [빠른 시작](#-빠른-시작)
2. [초기 설정 가이드](#-초기-설정-가이드)
   - [환경 변수 설정](#1-환경-변수-설정)
   - [Jira 계정 정보](#2-jira-계정-정보-설정)
   - [Confluence Wiki 설정](#3-confluence-wiki-설정-선택)
   - [Wiki 작성자 이름 설정](#4-wiki-작성자-이름-설정-선택)
   - [Wiki 템플릿 커스터마이징](#5-wiki-템플릿-커스터마이징-선택)
3. [제공 기능](#-제공-기능)
   - [Jira 기능](#1-jira-기능)
   - [Wiki 생성 기능](#2-confluence-wiki-생성-기능) (멀티프로젝트 병합 포함)
   - [Git 커밋 수집 및 분석](#3-git-커밋-수집-및-분석)
4. [Claude Desktop/Code 연동](#-claude-desktopcode-연동)
5. [사용 예시](#-사용-예시)
6. [문제 해결](#-문제-해결)

---

## 🚀 빠른 시작

### 1. 사전 요구사항

- Python 3.11 이상
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) (권장) 또는 Python venv

### 2. 설치

```bash
# 저장소 Fork 후 클론
git clone <your-forked-repository-url>
cd auto-mcp-server
```

**방법 A: Miniconda 가상환경 (권장)**

```bash
conda create -n auto-mcp python=3.11 -y
conda activate auto-mcp
pip install -r requirements.txt
```

**방법 B: Python venv**

```bash
python3.11 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> **중요:** 가상환경의 Python 절대 경로를 확인해두세요. Claude Code/Desktop 등록 시 필요합니다.
> ```bash
> which python
> # 예: /Users/username/miniconda3/envs/auto-mcp/bin/python
> ```

### 3. 환경 설정

```bash
# 환경 변수 템플릿 복사
cp .env.local.example .env.local

# .env.local 파일을 열어 Jira 정보 입력
vi .env.local  # 또는 원하는 에디터 사용
```

### 4. 서버 실행 (테스트)

가상환경이 활성화된 상태에서 실행합니다.

```bash
# 가상환경 활성화 확인
conda activate auto-mcp   # 또는 source .venv/bin/activate

APP_ENV=local python -m src
```

정상적으로 실행되면 로그에서 "✅ MCP Tools 등록 완료" 메시지를 확인할 수 있습니다.

---

## ⚙️ 초기 설정 가이드

### 1. 환경 변수 설정

`.env.local.example` 파일을 복사하여 `.env.local` 파일을 생성합니다.

```bash
cp .env.local.example .env.local
```

**기본 환경 변수:**

```env
# 환경 구분
APP_ENV=local

# MCP 서버 이름
SERVER_NAME=auto-mcp-server

# Jira 서버 설정
JIRA_BASE_URL=http://your-jira-server:8080
USER_ID=your_jira_username
USER_PASSWORD=your_jira_password

# Wiki 설정
WIKI_BASE_URL=https://your-confluence-server
WIKI_ISSUE_SPACE_KEY=YOUR_SPACE
WIKI_ISSUE_ROOT_PAGE_ID=YOUR_ROOT_PAGE_ID

# Wiki 작성자 이름 (Wiki 페이지 제목에 표시, 선택)
# WIKI_AUTHOR_NAME=홍길동

# Git 저장소 매핑 (JSON 형식, 선택)
# collect_branch_commits / analyze_branch_changes에서 repository_path 미지정 시 자동 탐지
# GIT_REPOSITORIES={"project-a": "/path/to/project-a", "project-b": "/path/to/project-b"}

# Diff 최대 문자수 (선택, 기본값: 30000)
# MAX_DIFF_CHARS=30000
```

### 2. Jira 계정 정보 설정

#### 2.1 Jira 서버 URL 확인

Jira 웹 브라우저 주소창에서 기본 URL을 확인합니다.

**예시:**
- `http://jira.yourcompany.com:8080` → 이 값을 `JIRA_BASE_URL`에 입력
- `https://yourcompany.atlassian.net` → Atlassian Cloud의 경우

#### 2.2 Jira 사용자 계정

**on-premise Jira:**
- `USER_ID`: Jira 로그인 아이디
- `USER_PASSWORD`: Jira 로그인 비밀번호

**Atlassian Cloud Jira:**
- `USER_ID`: Jira 계정 이메일
- `USER_PASSWORD`: API 토큰 (비밀번호 아님!)
  - 생성 방법: https://id.atlassian.com/manage-profile/security/api-tokens
  - "Create API token" 클릭 → 토큰 복사 → `USER_PASSWORD`에 입력

#### 2.3 환경 변수 예시

```env
# On-premise Jira
JIRA_BASE_URL=http://jira.mycompany.com:8080
USER_ID=your_username
USER_PASSWORD=my_password_here

# Atlassian Cloud Jira
JIRA_BASE_URL=https://mycompany.atlassian.net
USER_ID=your_username@mycompany.com
USER_PASSWORD=ATBBxxx...xxx  # API 토큰
```

### 3. Confluence Wiki 설정

Wiki 페이지 자동 생성 기능을 사용하려면 다음 설정이 필요합니다.

#### 3.1 Confluence 서버 URL

```env
WIKI_BASE_URL=https://confluence.mycompany.com
```

#### 3.2 Space Key 확인

Confluence에서 Wiki 페이지를 생성할 Space의 Key를 확인합니다.

**확인 방법:**
1. Confluence 웹에서 원하는 Space로 이동
2. 주소창 확인: `https://confluence.../display/**SPACEKEY**/...`
3. SPACEKEY 부분을 복사

```env
WIKI_ISSUE_SPACE_KEY=DEVOPS  # 예시
```

#### 3.3 루트 페이지 ID 확인

Wiki 페이지가 생성될 최상위(루트) 페이지의 ID를 확인합니다.

**확인 방법:**
1. Confluence에서 루트 페이지로 사용할 페이지로 이동
2. 페이지 우측 상단 메뉴 `...` → `페이지 정보 보기` 클릭
3. 주소창 확인: `.../pages/viewinfo.action?pageId=**123456789**`
4. pageId 값을 복사

```env
WIKI_ISSUE_ROOT_PAGE_ID=123456789  # 예시
```

#### 3.4 Confluence 인증

Confluence는 Jira와 동일한 계정을 사용합니다. (`USER_ID`, `USER_PASSWORD`)

- On-premise: Jira와 Confluence가 통합 계정을 사용하는 경우 추가 설정 불필요
- Atlassian Cloud: 동일한 API 토큰 사용

### 4. Wiki 작성자 이름 설정 (선택)

Wiki 페이지 제목에 표시할 작성자 이름을 설정합니다.

```env
WIKI_AUTHOR_NAME=홍길동
```

설정하면 Wiki 페이지 제목이 다음과 같이 생성됩니다:
- 연도 페이지: `[홍길동] 2026`
- 월 페이지: `[홍길동] 2026-02`

미설정 시 제목에 작성자 이름이 빈 값으로 표시됩니다.

### 5. Wiki 템플릿 커스터마이징 (선택)

Wiki 페이지 생성 시 사용할 템플릿을 커스터마이징할 수 있습니다.

#### 5.1 템플릿 파일 위치

```
config/wiki_templates.yaml
```

#### 5.2 템플릿 구조

```yaml
# 페이지 제목 형식
# {{ AUTHOR_NAME }}은 환경변수 WIKI_AUTHOR_NAME에서 설정
title_formats:
  year: "[{{ AUTHOR_NAME }}] {{ YEAR }}"
  month: "[{{ AUTHOR_NAME }}] {{ YEAR }}-{{ MONTH_PADDED }}"

# 워크플로우별 본문 템플릿
workflows:
  workflow_a:
    description: "Jira 이슈 완료 후 Wiki 생성"
    body: |
      <h2>이슈 정보</h2>
      <table>
        <tbody>
          <tr><th>이슈키</th><td>{{ ISSUE_KEY }}</td></tr>
          <tr><th>제목</th><td>{{ ISSUE_TITLE }}</td></tr>
          ...
        </tbody>
      </table>
```

#### 5.3 사용 가능한 변수

**제목 형식 (title_formats):**
- `{{ AUTHOR_NAME }}` - 작성자 이름 (환경변수 `WIKI_AUTHOR_NAME`)
- `{{ YEAR }}` - 년도
- `{{ MONTH }}` - 월
- `{{ MONTH_PADDED }}` - 월 (2자리, 예: `02`)

**Workflow A (Jira 이슈):**
- `{{ ISSUE_KEY }}` - Jira 이슈 키
- `{{ ISSUE_TITLE }}` - Jira 이슈 제목
- `{{ ASSIGNEE }}` - 담당자
- `{{ RESOLUTION_DATE }}` - 완료일
- `{{ PRIORITY }}` - 우선순위
- `{{ BRANCH_NAME }}` - 브랜치명
- `{{ COMMIT_LIST }}` - 커밋 목록 (HTML)
- `{{ CHANGE_SUMMARY_HTML }}` - 변경 내용 요약 (HTML)
- `{{ JIRA_URL }}` - Jira 이슈 링크
- `{{ JIRA_STATUS }}` - Jira 상태
- `{{ JIRA_ISSUETYPE }}` - Jira 이슈 유형

**Workflow B (브랜치/커밋):**
- `{{ INPUT_TYPE }}` - 입력 유형 (브랜치명/MR 등)
- `{{ INPUT_VALUE }}` - 입력 값
- `{{ BASE_DATE }}` - 기준 날짜
- `{{ COMMIT_LIST }}` - 커밋 목록 (HTML)
- `{{ CHANGE_SUMMARY_HTML }}` - 변경 내용 요약 (HTML)
- `{{ JIRA_ISSUES_HTML }}` - 관련 Jira 이슈 테이블 (선택)

#### 5.4 템플릿 리로드

템플릿을 수정한 후 서버 재시작 없이 반영하려면:

```
Claude에게: "Wiki 템플릿 리로드해줘"
```

또는 `reload_wiki_templates` MCP 도구를 직접 호출합니다.

### 6. Git 저장소 매핑 (선택)

`collect_branch_commits` / `analyze_branch_changes` 도구에서 `repository_path`를 지정하지 않으면
`GIT_REPOSITORIES`에 등록된 저장소들을 자동 순회하여 브랜치를 탐지합니다.

```env
GIT_REPOSITORIES={"oper-back-office": "/path/to/oper-back-office", "supplier-back-office": "/path/to/supplier-back-office"}
```

### 7. Diff 최대 문자수 (선택)

`collect_branch_commits`의 `include_diff=true` 시 스마트 필터링 후 반환할 최대 Diff 크기입니다.

```env
MAX_DIFF_CHARS=30000  # 기본값
```

---

## 🎯 제공 기능

### MCP Tool 전체 목록

| 카테고리 | Tool | 설명 |
|---------|------|------|
| **Jira** | `get_jira_issue` | 특정 이슈 조회 (key로) |
| | `get_jira_issues` | 내 이슈 목록 조회 (상태/프로젝트 필터링) |
| | `get_jira_project_meta` | 프로젝트 이슈 유형 및 상태값 조회 |
| | `complete_jira_issue` | 이슈 완료 처리 (상태 전환 + 종료일 설정) |
| | `transition_jira_issue` | 이슈 상태 전환 (임의 상태로) |
| | `create_jira_filter` | JQL 기반 필터 생성 |
| **Wiki** | `create_wiki_issue_page` | Jira 이슈 정리 Wiki 페이지 생성 (워크플로우 A) |
| | `create_wiki_page_with_content` | 브랜치/커밋 기반 Wiki 페이지 생성 (워크플로우 B) |
| | `create_wiki_custom_page` | 자유 형식 커스텀 Wiki 페이지 생성 (워크플로우 C) |
| | `approve_wiki_generation` | Wiki 생성 승인 (실제 페이지 생성) |
| | `get_wiki_generation_status` | Wiki 생성 세션 상태 조회 |
| | `reload_wiki_templates` | Wiki 템플릿 핫 리로드 |
| **Git** | `collect_branch_commits` | 브랜치 커밋 수집 (Wiki 생성용) |
| | `analyze_branch_changes` | 브랜치 변경사항 분석 (범용) |

---

### 1. Jira 기능

#### 1.1 특정 이슈 조회 (`get_jira_issue`)

```
Claude에게: "BNFDEV-2365 이슈 상세정보 알려줘"
```

**파라미터:**
- `key` (필수): Jira 이슈 키 (예: `BNFDEV-2365`)

**응답:**
- 이슈 키, 제목, 상태, 담당자, 유형
- 클릭 가능한 Jira 링크
- 전체 설명(Description)

---

#### 1.2 내 이슈 목록 조회 (`get_jira_issues`)

```
Claude에게: "내 Jira 이슈 목록 보여줘"
Claude에게: "진행 중인 이슈만 보여줘"
```

**파라미터:**
- `statuses` (선택): 조회할 상태 목록 (생략 시 전체 조회)
- `project_key` (선택): 특정 프로젝트로 필터링 (예: `BNFDEV`)

**영어 상태값 자동 변환:**

| 영어 입력 | 변환되는 한글 상태값 |
|-----------|---------------------|
| `Done` / `Completed` | 완료, 완료(개발), DONE(BNF), 개발완료(BNF), 배포완료(BNF) 등 |
| `In Progress` | 진행중(개발), 진행중(설계), 처리중(BNF), 개발(BNF) |
| `To Do` / `Open` | 할일, 할일(개발), 할일(BNF), 개발접수(BNF) |

---

#### 1.3 프로젝트 메타 조회 (`get_jira_project_meta`)

```
Claude에게: "BNFDEV 프로젝트 이슈 유형 알려줘"
```

**파라미터:**
- `project_key` (필수): Jira 프로젝트 키 (예: `BNFDEV`)

**응답:**
- 이슈 유형 목록 (Bug, Task, Story 등)
- 각 유형별 사용 가능한 상태값

---

#### 1.4 이슈 완료 처리 (`complete_jira_issue`)

```
Claude에게: "BNFDEV-1234 이슈 완료처리 해줘"
```

**파라미터:**
- `key` (필수): Jira 이슈 키
- `due_date` (선택): 종료일 (YYYY-MM-DD, 생략 시 오늘)

**동작:**
- 이슈를 완료 상태로 자동 전환
- 이슈 키 프리픽스에 따라 종료일 설정 방식이 다름

**종료일 처리 규칙 (이슈 키 프리픽스별):**
- **BNFDEV-***: `customfield_10833` 필드에 종료일 설정
- **BNFMT-***: 종료일 설정 안 함
- **기타**: `duedate` 필드에 종료일 설정

**완료 상태 우선순위:**
배포완료(BNF) → DONE(BNF) → 검수완료(BNF) → 개발완료(BNF) → 완료

---

#### 1.5 이슈 상태 전환 (`transition_jira_issue`)

```
Claude에게: "BNFDEV-1234 진행중(개발)으로 바꿔줘"
```

**파라미터:**
- `key` (필수): Jira 이슈 키
- `target_status` (필수): 전환할 목표 상태명

---

#### 1.6 Jira 필터 생성 (`create_jira_filter`)

```
Claude에게: "내 진행중 이슈 필터 만들어줘"
```

**파라미터:**
- `name` (필수): 필터 이름
- `jql` (필수): JQL 쿼리

**예시:**
```
name: "내 진행중 이슈"
jql: "assignee = currentUser() AND status = '진행중(개발)'"
```

---

### 2. Confluence Wiki 생성 기능

#### 🔴 중요: 2단계 승인 프로세스

**모든 Wiki 생성은 반드시 사용자 승인이 필요합니다!**

1. **준비 단계**: `create_wiki_issue_page` 또는 `create_wiki_page_with_content` 호출
   - 즉시 생성되지 않음
   - 프리뷰 + 승인 토큰 반환
   - 상태: `WAIT_APPROVAL`

2. **승인 단계**: `approve_wiki_generation` 호출
   - 세션 ID + 승인 토큰 일치 시에만 생성
   - 실제 Confluence Wiki 페이지 생성
   - 상태: `DONE`

---

#### 2.1 Jira 이슈 정리 페이지 생성 (`create_wiki_issue_page`)

Jira 이슈 완료 후 Wiki에 정리 페이지를 생성합니다.

```
Claude에게: "BNFDEV-1234 Wiki 이슈 정리 페이지 만들어줘"
```

**필수 파라미터:**
- `issue_key`: Jira 이슈 키 (예: `BNFDEV-1234`)
- `issue_title`: Jira 이슈 제목

**선택 파라미터:**
- `commit_list`: 커밋 목록 (줄바꿈 구분). 미제공 시 로컬 git에서 자동 조회
- `change_summary`: 변경 내용 요약. 미제공 시 커밋 메시지에서 자동 생성
- `assignee`: 담당자 (기본값: "미지정")
- `resolution_date`: 완료일 (YYYY-MM-DD, 기본값: 오늘)
- `priority`: 우선순위 (기본값: "보통")
- `project_name`: 프로젝트명 (예: `oper-back-office`). 동일 이슈 페이지가 이미 존재하면 프로젝트별 섹션으로 추가됩니다. 생략 시 기존처럼 동작 (중복 페이지 에러). 자세한 내용은 [멀티프로젝트 Wiki 병합](#26-멀티프로젝트-wiki-병합) 참조

**프로세스:**
1. 프리뷰 생성 → 승인 대기
2. 사용자 확인
3. `approve_wiki_generation(session_id, approval_token)` 호출
4. Wiki 페이지 생성 완료 (또는 기존 페이지에 프로젝트 섹션 추가)

---

#### 2.2 브랜치/커밋 내용으로 Wiki 생성 (`create_wiki_page_with_content`)

브랜치, GitLab MR, 커밋 범위 등으로 Wiki 페이지를 생성합니다.

```
Claude에게: "dev_rf 브랜치 커밋 목록으로 Wiki 페이지 만들어줘"
```

**필수 파라미터:**
- `page_title`: Wiki 페이지 제목
- `commit_list`: 커밋 목록 (줄바꿈 구분)

**선택 파라미터:**
- `input_type`: 입력 유형 설명 (기본값: "브랜치명", 예: "GitLab MR", "커밋 범위")
- `input_value`: 브랜치명, MR 번호 등 원본 값
- `base_date`: 기준 날짜 (YYYY-MM-DD, 기본값: 오늘)
- `change_summary`: 변경 내용 요약 (생략 시 자동 생성)
- `diff_stat`: git diff --stat 결과 (`collect_branch_commits`에서 받은 값 전달 시 Wiki "변경 파일 목록" 섹션에 포함)
- `jira_issue_keys`: 관련 Jira 이슈 키 (콤마 구분, 예: `BNFDEV-1234,BNFMT-567`)
  - 포함 시 Jira 이슈 내용이 Wiki에 추가됨
  - 프로젝트별 날짜 기준 자동 적용 (BNFDEV: 종료일, BNFMT: 생성일)
- `project_name`: 프로젝트명 (예: `oper-back-office`). 동일 제목의 페이지가 이미 존재하면 프로젝트별 섹션으로 추가됩니다. 생략 시 기존처럼 동작 (중복 페이지 에러). 자세한 내용은 [멀티프로젝트 Wiki 병합](#26-멀티프로젝트-wiki-병합) 참조

**프로세스:**
1. 프리뷰 생성 → 승인 대기
2. 사용자 확인
3. `approve_wiki_generation(session_id, approval_token)` 호출
4. Wiki 페이지 생성 완료 (또는 기존 페이지에 프로젝트 섹션 추가)

---

#### 2.3 커스텀 Wiki 페이지 생성 (`create_wiki_custom_page`)

특정 부모 페이지 아래에 자유 형식(마크다운/텍스트)으로 Wiki 페이지를 생성합니다.

```
Claude에게: "'AI' 페이지 아래에 기술 문서 작성해줘"
```

**필수 파라미터:**
- `page_title`: 생성할 페이지 제목
- `content`: 페이지 내용 (마크다운 또는 텍스트)
- `parent_page_id` 또는 `parent_page_title` 중 하나

**선택 파라미터:**
- `space_key`: Confluence Space 키 (생략 시 `WIKI_ISSUE_SPACE_KEY` 기본값 사용)

**특징:**
- 기존 워크플로우(A/B)와 달리 연/월 계층 구조를 사용하지 않음
- 사용자가 지정한 부모 페이지 바로 아래에 페이지 생성
- 마크다운 형식 지원 (제목, 목록, 코드블록, 볼드, 이탤릭 등)
- 일반 텍스트도 자동으로 Confluence HTML로 변환

---

#### 2.4 Wiki 생성 승인 (`approve_wiki_generation`)

```
Claude에게: "Wiki 생성 승인해줘"
```

**필수 파라미터:**
- `session_id`: 세션 ID
- `approval_token`: 승인 토큰

**응답:**
- 생성된 페이지 제목, ID, URL
- **새 페이지 생성** 시: "Wiki 페이지 생성 완료 (승인)"
- **기존 페이지에 프로젝트 섹션 추가** 시: "Wiki 페이지 업데이트 완료 (기존 페이지에 프로젝트 섹션 추가)"

---

#### 2.5 Wiki 생성 상태 조회 (`get_wiki_generation_status`)

```
Claude에게: "Wiki 생성 세션 상태 확인해줘"
```

**필수 파라미터:**
- `session_id`: 세션 ID

**응답:**
- 세션 ID, 워크플로우 유형, 현재 상태
- 페이지 제목, 승인 토큰, 프리뷰

---

#### 2.6 멀티프로젝트 Wiki 병합

하나의 Jira 이슈가 여러 프로젝트(예: `oper-back-office`, `supplier-back-office`)에 걸쳐 수정될 때, 각 프로젝트의 변경사항을 **하나의 Wiki 페이지에 통합**할 수 있습니다.

**동작 원리:**
- `project_name` 파라미터를 지정하여 Wiki 생성 도구를 호출하면, 동일 제목의 페이지가 이미 존재할 때 에러 대신 **기존 페이지에 프로젝트별 섹션을 추가**(append)합니다.
- 추가되는 섹션은 Confluence info 매크로로 시각적으로 구분됩니다.
- `project_name`을 생략하면 기존 동작과 동일합니다 (중복 페이지 시 에러).

**페이지 구조 예시:**

```
[BNFDEV-1234] 로그인 버그 수정
├── (원본) 이슈 정보 테이블, 커밋 내역, 변경 요약 (첫 번째 프로젝트)
├── ──────── (구분선) ────────
└── [info 매크로] supplier-back-office 추가 변경사항 (2026-02-26)
     ├── 브랜치 및 커밋 내역
     ├── 커밋 요약
     └── 변경 내용 요약
```

**Upsert 동작 흐름:**

| 시나리오 | `project_name` | 동일 제목 페이지 | 결과 |
|---------|---------------|-----------------|------|
| 첫 번째 프로젝트 | `oper-back-office` | 없음 | 새 페이지 생성 |
| 두 번째 프로젝트 | `supplier-back-office` | 있음 | 기존 페이지에 섹션 추가 |
| 단일 프로젝트 (기존 방식) | 생략 | 없음 | 새 페이지 생성 |
| 단일 프로젝트 (기존 방식) | 생략 | 있음 | 에러 발생 (하위호환) |

**동시성 처리:**
- Confluence Optimistic Locking 기반으로 동시 수정 충돌(409) 시 자동 재시도 (최대 3회)
- 수동 승인 단계가 있어 실제 동시 충돌 확률은 매우 낮음

---

### 3. Git 커밋 수집 및 분석

#### 3.1 브랜치 커밋 수집 (`collect_branch_commits`)

브랜치의 고유 커밋 목록과 변경사항(diff)을 수집합니다. Wiki 페이지 생성 워크플로우에 사용됩니다.

```
Claude에게: "dev_BNFDEV-1234 브랜치 커밋 수집해줘"
```

**필수 파라미터:**
- `branch_name`: 조회할 브랜치명 (예: `dev_BNFDEV-1234`)

**선택 파라미터:**
- `repository_path`: git 저장소 경로 (생략 시 `GIT_REPOSITORIES`에 등록된 저장소에서 자동 탐지)
- `include_diff`: `true` 시 스마트 필터링된 diff 원본 포함 (기본값: `false`)

**베이스 브랜치 자동 탐지:**
다음 순서로 베이스 브랜치를 찾아 정확한 커밋 범위를 계산합니다:
1. `dev` → 2. `origin/dev` → 3. `develop` → 4. `origin/develop` → 5. `main` → 6. `master`

**저장소 자동 탐지:**
- `repository_path` 미지정 시 `.env.local`의 `GIT_REPOSITORIES`에 등록된 저장소를 순회하여 브랜치를 탐지
- 머지 커밋이 있는 저장소 우선, 활성 브랜치가 있는 저장소 차순

**스마트 Diff 필터링 (`include_diff=true`):**
- 소스코드(high priority) > 설정/스타일 파일(medium) > lock/생성 파일(low) 순으로 우선 포함
- `package-lock.json`, `yarn.lock`, `OpenApi/`, `.min.js` 등 자동 제외
- `MAX_DIFF_CHARS` 환경변수로 최대 크기 조절 (기본값: 30000자)

**응답:**
- 커밋 수, 커밋 목록 (줄바꿈 구분)
- 변경 파일 통계 (diff --stat)
- Diff 크기 및 예상 토큰 수 + 방법 A/B 선택 안내
- 감지된 Jira 이슈 키 (브랜치명/커밋에서 자동 추출)

**2단계 선택 워크플로우:**
```
1. collect_branch_commits("dev_BNFDEV-1234")  # 기본: include_diff=false
2. diff 크기 확인 → 방법 A(커밋 메시지 기반) / 방법 B(diff 분석 기반) 선택
3. 방법 B 선택 시: include_diff=true로 재호출
4. change_summary 작성 후 create_wiki_page_with_content(...) 호출
```

---

#### 3.2 브랜치 변경사항 분석 (`analyze_branch_changes`)

브랜치의 변경사항을 분석하여 보고합니다. Wiki 생성 없이 변경사항에 대한 질문에 답변할 때 사용합니다.

```
Claude에게: "dev_feature 브랜치에서 뭐 바뀌었어?"
Claude에게: "이번 변경사항 요약해줘"
```

**필수 파라미터:**
- `branch_name`: 분석할 브랜치명

**선택 파라미터:**
- `repository_path`: git 저장소 경로 (생략 시 `GIT_REPOSITORIES`에서 자동 탐지)

**`collect_branch_commits`와의 차이:**
- `collect_branch_commits`: Wiki 페이지 생성 워크플로우 전용
- `analyze_branch_changes`: 범용 변경사항 분석/질문 답변용

**응답:**
- 커밋 수, 커밋 목록
- 변경 파일 통계 (diff --stat)
- 스마트 필터링된 코드 변경사항
- 감지된 Jira 이슈 키

---

## 🔗 Claude Desktop/Code 연동

### Claude Desktop 설정

macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "auto-mcp-server": {
      "command": "/Users/username/miniconda3/envs/auto-mcp/bin/python",
      "args": ["-m", "src"],
      "cwd": "/Users/username/projects/auto-mcp-server",
      "env": {
        "APP_ENV": "local",
        "PYTHONPATH": "/Users/username/projects/auto-mcp-server"
      }
    }
  }
}
```

- `command`: 가상환경의 Python **절대 경로** (`which python`으로 확인한 값)
- `cwd`: auto-mcp-server 프로젝트의 **절대 경로**
- `PYTHONPATH`: `cwd`와 동일한 경로 (Python이 `src` 모듈을 찾을 수 있도록)
- `APP_ENV`: 사용할 환경 파일 (`local`, `dev` 등)

설정 후 **Claude Desktop 재시작** 필요.

---

### Claude Code 설정

Claude Code는 **MCP 서버 프로젝트가 아닌, 실제 작업할 프로젝트 디렉토리**에서 실행합니다.
MCP 서버는 가상환경의 Python 절대 경로와 `PYTHONPATH`를 지정하여 등록합니다.

#### Step 1. 가상환경 Python 경로 확인

auto-mcp-server 디렉토리에서 가상환경을 활성화한 후 경로를 확인합니다.

```bash
cd /path/to/auto-mcp-server
conda activate auto-mcp   # 또는 source .venv/bin/activate
which python
# 예: /Users/username/miniconda3/envs/auto-mcp/bin/python
```

#### Step 2. 작업할 프로젝트에서 MCP 등록

```bash
# 실제 작업할 프로젝트로 이동
cd /path/to/your-project

# MCP 서버 등록
claude mcp add auto-mcp-server \
  -e APP_ENV=local \
  -e PYTHONPATH=/path/to/auto-mcp-server \
  -- /path/to/miniconda3/envs/auto-mcp/bin/python -m src
```

**파라미터 설명:**
- `-e PYTHONPATH=...` : auto-mcp-server 프로젝트 루트 경로 (Python이 `src` 모듈을 찾기 위해 필요)
- `-e APP_ENV=local` : 환경 변수 파일 구분 (`.env.local` 사용)
- `-- /path/to/.../python` : 가상환경의 Python 절대 경로 (의존성이 설치된 환경)

#### 구체적 예시 (macOS)

```bash
# miniconda 가상환경 사용 시
claude mcp add auto-mcp-server \
  -e APP_ENV=local \
  -e PYTHONPATH=/Users/username/projects/auto-mcp-server \
  -- /Users/username/miniconda3/envs/auto-mcp/bin/python -m src

# venv 사용 시
claude mcp add auto-mcp-server \
  -e APP_ENV=local \
  -e PYTHONPATH=/Users/username/projects/auto-mcp-server \
  -- /Users/username/projects/auto-mcp-server/.venv/bin/python -m src
```

#### 등록 확인

```bash
claude mcp list
```

---

## 💡 사용 예시

### 예시 1: Jira 이슈 완료 후 Wiki 페이지 생성

```
사용자: "BNFDEV-2365 이슈 완료처리 해줘"
→ complete_jira_issue 실행

Claude: "완료 처리되었습니다. Wiki 이슈 정리 페이지를 생성할까요?"

사용자: "yes"
→ create_wiki_issue_page 실행 (프리뷰 + 승인 토큰 반환)

Claude: "프리뷰를 확인해주세요. 승인할까요?"

사용자: "yes"
→ approve_wiki_generation 실행 (실제 Wiki 페이지 생성)

Claude: "Wiki 페이지 생성 완료: https://confluence.../..."
```

---

### 예시 2: 브랜치 커밋으로 Wiki 페이지 생성

```
사용자: "oper-back-office 프로젝트의 dev_rf 브랜치 커밋 수집해줘"
→ collect_branch_commits 실행

Claude: "12개 커밋 수집 완료. 커밋 목록: ..."

사용자: "커밋 내용 분석해서 Wiki 페이지 만들어줘"
→ 커밋 분석 + create_wiki_page_with_content 실행 (프리뷰)

Claude: "프리뷰를 확인해주세요. 승인할까요?"

사용자: "yes"
→ approve_wiki_generation 실행

Claude: "Wiki 페이지 생성 완료"
```

---

### 예시 3: 여러 Jira 이슈 포함 Wiki 생성

```
사용자: "dev_feature 브랜치 커밋 수집하고, BNFDEV-100,BNFDEV-101 이슈 내용 포함해서 Wiki 만들어줘"

→ collect_branch_commits("dev_feature")
→ 커밋 분석
→ create_wiki_page_with_content(
    page_title="dev_feature",
    commit_list="...",
    change_summary="...",
    jira_issue_keys="BNFDEV-100,BNFDEV-101"
  )

Claude: "프리뷰 - Jira 이슈 2건 포함됨. 승인할까요?"

사용자: "yes"
→ approve_wiki_generation

Claude: "Wiki 페이지 생성 완료"
```

---

### 예시 4: 커스텀 Wiki 페이지 생성

```
사용자: "'AI' 페이지 아래에 회의록 페이지 만들어줘"
→ create_wiki_custom_page 실행 (프리뷰 + 승인 토큰 반환)

Claude: "프리뷰를 확인해주세요. 승인할까요?"

사용자: "yes"
→ approve_wiki_generation 실행

Claude: "Wiki 페이지 생성 완료: https://confluence.../..."
```

---

### 예시 5: 브랜치 변경사항 분석 (Wiki 생성 없이)

```
사용자: "dev_feature 브랜치에서 뭐 바뀌었어?"
→ analyze_branch_changes 실행

Claude: "15개 커밋, 8개 파일 변경. 주요 변경사항: ..."
```

---

### 예시 6: 멀티프로젝트 Wiki 병합

하나의 Jira 이슈(BNFDEV-1234)가 `oper-back-office`와 `supplier-back-office` 두 프로젝트에 걸쳐 수정된 경우:

```
# 1단계: 첫 번째 프로젝트 (oper-back-office)
사용자: "oper-back-office의 dev_BNFDEV-1234 커밋으로 Wiki 만들어줘"
→ create_wiki_issue_page(
    issue_key="BNFDEV-1234",
    issue_title="로그인 버그 수정",
    commit_list="...",
    project_name="oper-back-office"
  )
→ approve_wiki_generation
→ Wiki 페이지 생성 완료: "[BNFDEV-1234] 로그인 버그 수정"

# 2단계: 두 번째 프로젝트 (supplier-back-office)
사용자: "supplier-back-office의 dev_BNFDEV-1234 커밋도 같은 Wiki에 추가해줘"
→ create_wiki_issue_page(
    issue_key="BNFDEV-1234",
    issue_title="로그인 버그 수정",
    commit_list="...",
    project_name="supplier-back-office"
  )
→ 기존 페이지 발견 → 프로젝트 섹션 추가 모드로 전환
→ approve_wiki_generation
→ 기존 페이지에 supplier-back-office 섹션 추가 완료
```

결과: 하나의 Wiki 페이지에 두 프로젝트의 변경사항이 시각적으로 구분되어 통합됩니다.

> **⚠️ 주의: 첫 번째 프로젝트부터 `project_name`을 명시하세요**
>
> 첫 번째 호출에서 `project_name`을 생략하면 프로젝트 구분 없이 페이지가 생성되고,
> 두 번째 호출에서만 프로젝트별 섹션이 추가되어 **비대칭적인 페이지 구조**가 됩니다.
>
> ```
> # ✅ 권장 - 처음부터 프로젝트명 지정
> "BNFDEV-1234 oper-back-office Wiki 이슈 정리 페이지 만들어줘"
> "BNFDEV-1234 supplier-back-office도 같은 Wiki에 추가해줘"
>
> # ⚠️ 비권장 - 첫 번째에 프로젝트명 누락
> "BNFDEV-1234 Wiki 이슈 정리 페이지 만들어줘"              ← 프로젝트 구분 표시 없음
> "BNFDEV-1234 supplier-back-office도 같은 Wiki에 추가해줘"  ← 이것만 구분 표시됨
> ```

---

## 🛠 문제 해결

### 1. Jira 인증 실패

**증상:**
```
❌ Jira 인증 실패: 사용자명 또는 비밀번호를 확인하세요
```

**해결 방법:**
1. `.env.local` 파일의 `USER_ID`, `USER_PASSWORD` 확인
2. Atlassian Cloud 사용 시 **API 토큰** 사용 확인 (비밀번호 아님)
3. `JIRA_BASE_URL`이 올바른지 확인 (포트 포함, 마지막 `/` 제거)

---

### 2. Wiki 설정 오류

**증상:**
```
⚠️ Wiki 설정이 필요합니다
```

**해결 방법:**
1. `.env.local` 파일에 다음 변수 추가:
   - `WIKI_BASE_URL`
   - `WIKI_ISSUE_SPACE_KEY`
   - `WIKI_ISSUE_ROOT_PAGE_ID`
2. Confluence 페이지 ID 확인: 페이지 우측 상단 `...` → `페이지 정보 보기`

---

### 3. Git 커밋 수집 실패

**증상:**
```
❌ 브랜치 커밋 수집 실패
브랜치가 존재하지 않거나 로컬 git 저장소에 문제가 있을 수 있습니다.
```

**해결 방법:**
1. 브랜치명 확인: `git branch -a` 실행
2. `repository_path` 파라미터로 정확한 git 저장소 경로 지정
3. `GIT_REPOSITORIES` 환경 변수에 저장소가 등록되어 있는지 확인

---

### 4. MCP 서버가 Claude에서 보이지 않음

**Claude Desktop:**
1. `claude_desktop_config.json` 파일 경로 확인
2. `cwd` 경로가 **절대 경로**인지 확인
3. Claude Desktop 완전히 재시작 (종료 후 재실행)

**Claude Code:**
```bash
# MCP 서버 목록 확인
claude mcp list

# 재등록
claude mcp remove auto-mcp-server
claude mcp add auto-mcp-server \
  -e APP_ENV=local \
  -e PYTHONPATH=/path/to/auto-mcp-server \
  -- /path/to/miniconda3/envs/auto-mcp/bin/python -m src
```

**가상환경 관련 문제:**
1. Python 경로가 실제 존재하는지 확인: `ls /path/to/miniconda3/envs/auto-mcp/bin/python`
2. `PYTHONPATH`가 auto-mcp-server 프로젝트 루트를 가리키는지 확인
3. 가상환경에 의존성이 설치되었는지 확인: 해당 Python으로 `python -c "import mcp"` 실행

---

### 5. 로그 확인

서버 실행 중 문제가 발생하면 로그를 확인하세요.

```bash
tail -f logs/mcp-server.log
```

로그 파일 위치: `logs/mcp-server.log`
- 최대 크기: 10MB
- 백업 파일: 5개 (자동 순환)

---

## 📚 추가 정보

### 아키텍처

Hexagonal Architecture (Ports & Adapters) 기반

```
[MCP Inbound]  ← Claude
     ↓
[Use Cases] ↔ [Ports] ↔ [Outbound Adapters]
     ↓
 [Domain]
```

| 레이어 | 위치 | 역할 |
|---|---|---|
| Domain | `src/domain/` | 핵심 도메인 엔티티 |
| Application | `src/application/` | Port 인터페이스, Use Case |
| Inbound | `src/adapters/inbound/mcp/` | MCP Tool 핸들러 |
| Outbound | `src/adapters/outbound/` | 외부 서비스 어댑터 |
| Config | `src/configuration/` | DI Container, Settings |

---

### 주요 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `mcp` | 1.9.4 | MCP 서버 프레임워크 |
| `httpx` | 0.28.1 | 비동기 HTTP 클라이언트 (Jira/Confluence API) |
| `pydantic` | 2.12.5 | 데이터 검증 |
| `Jinja2` | 3.1+ | Wiki 템플릿 렌더링 |
| `PyYAML` | 6.0+ | 템플릿 YAML 파싱 |
| `mistune` | 3.0+ | 마크다운→HTML 변환 (커스텀 Wiki 페이지) |
| `python-dotenv` | 1.2.1 | 환경 변수 로딩 |

### 개발

```bash
# 가상환경 활성화
conda activate auto-mcp   # 또는 source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 로컬 실행
APP_ENV=local python -m src

# 로그 확인
tail -f logs/mcp-server.log
```

---

### 새 MCP Tool 추가 방법

1. `src/application/ports/` - Port Protocol 정의
2. `src/adapters/outbound/` - Adapter 구현
3. `src/application/use_cases/` - Use Case 작성
4. `src/configuration/container.py` - DI 등록
5. `src/adapters/inbound/mcp/tools.py` - MCP Tool 등록

---

### 코드 컨벤션

- 설정/엔티티: `@dataclass(frozen=True)`
- 외부 계약: `typing.Protocol`
- DI Container: `@lru_cache` 싱글톤
- 비동기 I/O: `async/await`
- CPU 바운드: `asyncio.to_thread()`
- Type hints: `X | None` (not `Optional[X]`)

---

## 📄 라이선스

MIT License

---

## 🙋 지원

- 이슈 등록: GitHub Issues
- 문서: [CLAUDE.md](./CLAUDE.md)
