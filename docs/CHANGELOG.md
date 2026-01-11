# Hattz Empire - Changelog

**Current Version**: v2.6.4 (2026-01-09)

---

## v2.6.4 (2026-01-09) - Mode System + PM Decision Machine Upgrade

### 핵심 변경
- **Mode System**: BLOCKED, RETRY 액션 추가
- **PMOutput Contract**: `action: Literal["DISPATCH", "ESCALATE", "DONE", "BLOCKED", "RETRY"]`
- **summary 100자 제한**: PM이 시인 되는 거 방지

### 파일 변경
- `src/core/contracts.py`: PMOutput.action BLOCKED/RETRY 추가
- CLAUDE.md: ESCALATE 운영 정책 문서화

---

## v2.6.0 (2026-01-08) - 문서 정리 + Persona Pack 최신화

### 문서 개편
- **README.md 전면 개편**: ai_team_아키텍쳐.md 내용으로 교체 (35줄 → 340줄)
- **중복 문서 삭제**: PROMPT.md (527줄), ai_team_아키텍쳐.md (360줄) 제거
- **총 887줄 중복 제거**

### Persona Pack 업데이트
- `.claude/agents/GLOBAL_RULES.md`: v2.6.0 업데이트
- Dual Engine 아키텍처 테이블 추가
- PM State Machine 섹션 추가
- 역할 경계 테이블에 Analyst, Researcher 추가

### 파일 변경
- `scripts/sync_version.py`: 삭제된 파일 참조 제거, README 버전 뱃지 패턴 추가
- `templates/chat.html`: 푸터 "희망회로 금지" → GitHub 주소 변경

---

## v2.5.5 (2026-01-07) - RAG Agent Filter + 부트로더 원칙

### RAG Agent Filter
- **에이전트별 임베딩 검색 필터링** (`src/services/rag.py`)
  - `search(agent_filter=...)`: 특정 에이전트 임베딩만 검색
  - `search_by_agent(agent, ...)`: 에이전트별 검색 헬퍼 함수
  - `build_context(agent_filter=..., session_id=...)`: 에이전트별 컨텍스트 빌드

### index_document() 버그 수정
- **문제**: metadata에 agent 있어도 embeddings.agent 컬럼에 저장 안 됨
- **수정**: `agent` 파라미터 추가, metadata에서도 자동 추출

### 부트로더 원칙 확립
- **FLOW는 프롬프트가 아니라 부트로더**
- 에이전트는 서로의 존재를 모름 (PM만 전체 파악)
- 에이전트는 대화하지 않음 (계약 JSON만 주고받음)

### 파일 변경
- `src/services/rag.py`: agent_filter, search_by_agent 추가
- `src/services/embedding_queue.py`: agent 파라미터 전달
- `src/core/llm_caller.py`: 에이전트별 RAG 컨텍스트 주입

---

## v2.5.4 (2026-01-07) - PM Decision Machine + Semantic Guard

### PM Decision Machine
- **summary → enum 변환** (인간 흉내 제거)
- `PMDecision` enum: DISPATCH, ESCALATE, DONE, BLOCKED, RETRY
- summary는 로그용, 의사결정에 사용 금지
- 의미 없는 summary → confidence 감소 (0.5)

### CLI Semantic Guard
- **의미적 NULL 패턴 블랙리스트**
  - 한글: "검토했습니다", "확인했습니다", "문제없습니다", "진행하겠습니다"
  - 영어: "looks good", "no issues", "seems fine", "I have reviewed"
- **프로필별 필드 규칙**
  - coder: summary(10자+동사+대상), diff(20자+형식), files_changed(필수)
  - qa: verdict(PASS/FAIL/SKIP), tests(PASS시 필수)
  - reviewer: verdict(APPROVE/REVISE/REJECT), score(0-10), risks(REJECT시 필수)

### 파일 변경
- `src/services/cli_supervisor.py`: DecisionMachine.process() 추가
- `src/core/decision_machine.py`: PMDecision enum, Semantic Guard

---

## v2.5.3 (2026-01-07) - Semantic Guard 강화

### CLI Semantic Guard
- 코드 기반 의미 검증
- 의미적 NULL 패턴 감지
- 프로필별 필드 규칙 검증

---

## v2.5.2 (2026-01-07) - Retry Escalation 시스템

### Retry Escalation
- **3단계 에스컬레이션**: Self-repair → Role-switch → Hard Fail
- `FailureSignature`: 실패 시그니처 (error_type, missing_fields, profile, prompt_hash)
- `EscalationLevel`: SELF_REPAIR, ROLE_SWITCH, HARD_FAIL
- `RetryEscalator`: 실패 히스토리 관리 + 에스컬레이션 결정

### 모니터링 API
- `GET /api/monitor/escalation`: 에스컬레이션 상태 조회
- `POST /api/monitor/escalation/clear`: 히스토리 초기화

### 파일 변경
- `src/services/cli_supervisor.py`: RetryEscalator 추가
- `src/api/monitor.py`: 에스컬레이션 API 추가

---

## v2.4.1 (2026-01-07) - Analyst 파일 컨텍스트 주입

### Analyst 컨텍스트 주입
- **문제**: Gemini Flash API는 파일시스템 접근 불가
- **해결**: `collect_project_context()` 함수 추가
  - 프로젝트 파일 구조 + 주요 파일 내용 자동 수집
  - `PROJECT_PATHS`: 프로젝트별 루트 경로 매핑

### 파일 변경
- `src/core/llm_caller.py`: collect_project_context() 추가

---

## v2.4 (2026-01-07) - Dual Engine V3 + Persona Pack

### Dual Engine V3
- **Write → Audit → Rewrite** 패턴 (붙여넣기 방식 폐기)
- Auditor JSON verdict: `APPROVE | REVISE | REJECT`
- max 3회 rewrite 후 Council 소집

### Persona Pack
- **역할별 JSON 출력 강제 페르소나** (`.claude/agents/*.md`)
- `GLOBAL_RULES.md`: 공통 헌법 (잡담 금지, JSON 출력, CEO 에스컬레이션 조건)
- 12개 페르소나 파일 생성/업데이트

### 모델 변경
- Researcher Writer: Gemini Flash → **Perplexity Sonar Pro**
- Coder Writer: **Claude CLI Opus 4.5** (coder profile)
- 모든 Auditor: **Claude CLI Sonnet 4로 통일**
- GPT-5 mini 제거

### CEO→PM Only Routing
- CEO는 PM만 직접 호출 가능
- 하위 에이전트는 PM의 `[CALL:*]` 태그로만 호출

### 파일 변경
- `.claude/agents/`: 12개 페르소나 파일 생성
- `docker/Dockerfile.monitor`: COPY 경로 수정
- grafana 권한: `grafana:grafana` → `472:0`

---

## v2.3.1 (2026-01-06) - 위원회 DB 저장 + 임베딩

### Council DB 저장
- `council.py` 업그레이드
  - `_save_persona_judgment_to_db()`: 개별 페르소나 판정 저장
  - `_save_council_verdict_to_db()`: 최종 판정 저장
  - `set_session_context()`: 세션/프로젝트 컨텍스트 설정

### 저장 구조
- `agent`: `council_skeptic`, `council_pragmatist` 등
- `model_id`: `council-skeptic`, `council-code-verdict` 등
- `is_internal`: True (웹에 안 보임, DB/임베딩만)

### 파일 변경
- `src/infra/council.py`: DB 저장 기능 추가
- `src/api/council_api.py`: session_id, project 파라미터 추가

---

## v2.3 (2026-01-06) - Hook Chain 아키텍처

### Hook Chain System
- **PRE_RUN**: 세션 규정 로드, rules_hash 계산
- **PRE_REVIEW**: Static Gate (0원 1차 게이트)
- **POST_REVIEW**: 감사 로그 기록
- **StopHook**: StopCode Enum (COMPLETED, STATIC_REJECT, LLM_REJECT 등)
- **HookChain**: 체인 실행기 + `create_default_chain()`

### Context Management
- **TokenCounter**: 토큰 사용량 추적 (85% 경고, 압축 임계치)
- **Compactor**: Preemptive Compaction (휴리스틱 + LLM 요약)
- **ContextInjector**: Constitution + Session Rules 프롬프트 주입

### JSONC 파서 추가
- `src/control/jsonc_parser.py`: // 라인 주석, /* */ 블록 주석 지원
- 후행 쉼표 허용
- `JsoncRulesStore`: .json/.jsonc 모두 지원

### Router Agent 신설
- PM 병목 해소를 위한 자동 태스크 라우팅
- 키워드 기반 + LLM 하이브리드 라우팅
- CEO 프리픽스: 검색/, 코딩/, 분석/

### 파일 변경
- `src/hooks/`: Hook Chain 패키지 추가
- `src/context/`: Context Management 패키지 추가
- `src/control/jsonc_parser.py`: JSONC 파서 추가
- `src/services/router.py`: Router Agent 추가

---

## v2.2.3 (2026-01-06) - JSON Output 업그레이드

### Subagent JSON-Only 출력
- **결정론적 파싱**: 텍스트 기반 APPROVE/REJECT 감지의 불확실성 제거
- **자동화 용이**: 파이프라인에서 verdict 자동 추출 가능
- **에러 감소**: 휴먼 에러 및 포맷 불일치 방지

### 업그레이드된 에이전트 (6개)
- pm-reviewer.md: `verdict: APPROVE/REJECT`
- coder-worker.md: `status: DONE/NEED_INFO`
- coder-reviewer.md: `verdict: APPROVE/REJECT`
- qa-worker.md: `status: DONE/NEED_INFO`
- qa-reviewer.md: `verdict: APPROVE/REJECT`
- security-hawk.md: `decision: SHIP/HOLD`

### extract_verdict() 파서 업그레이드
- JSON 블록 찾기 (```json ... ``` 또는 순수 JSON)
- JSON 파싱 시도
- Fallback: 텍스트 기반 (레거시 지원)
- Verdict 정규화: SHIP/DONE → APPROVE, HOLD/NEED_INFO → REVISE

### 파일 변경
- `src/workers/agent_worker.py`: extract_verdict() 파서 업그레이드
- `.claude/agents/`: 6개 에이전트 파일 JSON 출력 강제

---

## v2.2.2 (2026-01-06) - Docker Full Run + Test 계정

### Docker 전체 실행 (9개 컨테이너)
| 컨테이너 | 역할 | LLM |
|---------|------|-----|
| hattz_web | Flask + ngrok + Gunicorn | - |
| hattz_pm_worker | PM Worker | GPT-5.2 |
| hattz_pm_reviewer | PM Reviewer | Claude CLI |
| hattz_coder_worker | Coder Worker (RW) | Claude CLI |
| hattz_coder_reviewer | Coder Reviewer (RO) | Claude CLI |
| hattz_qa_worker | QA Worker (tests RW) | Claude CLI |
| hattz_qa_reviewer | QA Reviewer (RO) | Claude CLI |
| hattz_reviewer_worker | Reviewer Worker | Gemini 2.5 |
| hattz_reviewer_reviewer | Security Hawk (RO) | Claude CLI |

### Test 계정 추가
- **id**: `test` / **password**: `1234`
- **allowed_projects**: `["test"]` (test 프로젝트만 접근 가능)
- User 클래스에 `allowed_projects` 필드 추가
- `/api/projects` 엔드포인트에서 사용자별 프로젝트 필터링

### ODBC Driver 수정
- ODBC Driver 17 → 18 변경 (Docker용)
- `TrustServerCertificate=yes` 추가
- 환경변수 `ODBC_DRIVER`로 오버라이드 가능

### ngrok 설정
- `.env`에 `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` 추가
- 고정 도메인: `caitlyn-supercivilized-intrudingly.ngrok-free.app`

### 파일 변경
- `src/utils/auth.py`: User 모델에 allowed_projects 추가
- `src/api/chat.py`: /api/projects 사용자별 필터링
- `src/services/database.py`: ODBC Driver 18 + TrustServerCertificate
- `src/services/rag.py`: ODBC Driver 18 + TrustServerCertificate
- `.env`: NGROK_AUTHTOKEN, NGROK_DOMAIN 추가
- `start.bat`, `stop.bat`: 신규 생성

---

## v2.2.1 (2026-01-06) - JSONL 영속화

### JSONL Persistence
- `_save_to_jsonl()` 함수 추가
- 모든 대화가 `parent_id`로 연결되어 저장
- CEO → PM-Worker → PM-Reviewer → ... 체인 추적
- 저장 경로: `src/infra/conversations/stream/YYYY-MM-DD.jsonl`

### Docker Compose 수정
- YAML 앵커 중복 오류 수정 (각 서비스 명시적 정의)
- `docker/Dockerfile.web`: apt-key → gpg --dearmor 방식 변경
- `requirements.txt`: psutil 추가

### 파일 변경
- `src/api/jobs.py`: JSONL 저장 기능 추가
- `docker-compose.yml`: YAML 앵커 수정
- `docker/Dockerfile.web`: apt-key 방식 변경

---

## v2.1 (2026-01-04) - CEO 프리픽스 + ngrok 고정 도메인

### CEO 프리픽스 기능
- `최고/`: Opus 4.5 (VIP-AUDIT) 강제
- `생각/`: GPT-5.2 Thinking Extend (VIP-THINKING) 강제
- `검색/`: Perplexity Sonar Pro (RESEARCH) 강제

### ngrok 고정 도메인 설정
- URL: `https://caitlyn-supercivilized-intrudingly.ngrok-free.app`
- 실행: `ngrok http 5000 --domain=caitlyn-supercivilized-intrudingly.ngrok-free.app`

### [CALL:agent] 태그 감지 수정
- **문제**: PM이 `[CALL:coder]`, `[CALL:qa]` 출력해도 백엔드에서 감지 못함
- **원인**: `executor.py`의 CALL_PATTERN 정규식이 `\n` 필수로 요구
- **수정**: `\s*\n` → `[\s\n]*` (줄바꿈 유무 모두 지원)

### Git 작업
- master 브랜치 삭제, main으로 통합
- dev → main 머지

### 파일 변경
- `src/core/llm_caller.py`: CEO 프리픽스 기능 추가
- `src/core/router.py`: CEO 프리픽스 라우팅
- `src/services/executor.py`: CALL_PATTERN 정규식 수정

---

## v2.0 (2026-01-03) - HattzRouter + Agent Scorecard

### HattzRouter v2.0
- **4티어 시스템**: BUDGET/STANDARD/VIP/RESEARCH
- 고위험 키워드 → VIP 자동 승격
- 추론 키워드 → Thinking Mode
- Perplexity 검색 통합
- 자동 폴백/에스컬레이션
- **비용 86% 절감** ($32.30 → $4.56 per 1K requests)

### Agent Scorecard
- CEO 피드백 기반 점수 시스템
- MSSQL 연동 완료
- 코드 자동 검증 (CodeValidator)
- 동적 라우팅용 `get_best_model()`

### Background Tasks
- 브라우저 닫아도 서버에서 계속 실행
- MSSQL DB에 결과 영구 저장
- 3초 간격 폴링
- 브라우저 알림 지원

### Gemini 요약 로그 DB 기록
- `executor.py`: `_log_gemini_summarization()` 함수 추가
- `rag.py`: `_log_gemini_rag_summarization()` 함수 추가
- role: `summarizer`, engine: `gemini`, task_type: `file_summarize`/`rag_summarize`

### UI 개선
- `static/css/style.css`: 채팅 히스토리 박스 높이 조정
- `.session-list` max-height: `250px` → `calc(100vh - 450px)`
- 뷰포트 높이에 따라 동적 확장

### 파일 변경
- `src/core/router.py`: HattzRouter v2.0 구현 (645줄)
- `src/services/agent_scorecard.py`: AgentScorecard 구현 (494줄)
- `src/services/background_tasks.py`: BackgroundTask 구현
- `src/services/executor.py`: Gemini 요약 로깅
- `src/services/rag.py`: Gemini RAG 요약 로깅
- `static/css/style.css`: 채팅 히스토리 박스 높이 조정

---

## API 엔드포인트 (v2.0~)

### Task API
- `/api/task/start` - 백그라운드 작업 시작
- `/api/task/<id>` - 작업 상태 조회
- `/api/tasks` - 세션별 작업 목록
- `/api/task/<id>/cancel` - 작업 취소

### Router API
- `/api/router/analyze` - 메시지 라우팅 분석
- `/api/router/stats` - 라우터 설정 통계

### Feedback API
- `/api/feedback` - CEO 피드백
- `/api/scores` - 모델별 점수
- `/api/scores/best/<role>` - 역할별 최고 모델
- `/api/scores/dashboard` - 대시보드

### Monitor API
- `/api/monitor/escalation` - 에스컬레이션 상태 조회
- `/api/monitor/escalation/clear` - 히스토리 초기화

---

**핵심 운영 원칙**: "가난하지만 안 죽는" 전략

1. 기본은 최저가 (Gemini Flash) - 80%
2. 코딩은 Sonnet (가성비)
3. VIP는 진짜 필요할 때만 - 5%
4. 검색은 Perplexity (트리거 기반)
5. 실패 시 자동 승격

---

*Last Updated: 2026-01-09*
