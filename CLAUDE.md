# Hattz Empire - AI Orchestration System (v2.5.5)

## 프로젝트 개요
비용 최적화 AI 팀 오케스트레이션 시스템. 비용 86% 절감 + 품질 유지 + JSONL 영속화.

---

## ESCALATE 운영 정책 (v2.5.5)

### 상태 전이 그래프

PM Decision Machine의 핵심은 **PMDecision 전이 규칙**이다.
허용된 전이만 통과하고, 나머지는 FAIL 처리된다.

```
ALLOWED_TRANSITIONS:
┌─────────────┬────────────────────────────────────────────┐
│ From State  │ Allowed To States                          │
├─────────────┼────────────────────────────────────────────┤
│ DISPATCH    │ RETRY, DONE, BLOCKED                       │
│ RETRY       │ DISPATCH, BLOCKED                          │
│ BLOCKED     │ ESCALATE                                   │
│ ESCALATE    │ DONE                                       │
│ DONE        │ (terminal - 어디로도 전이 불가)            │
└─────────────┴────────────────────────────────────────────┘

금지된 전이 (바로가기 금지):
- DISPATCH → ESCALATE ❌  (BLOCKED 경유 필수)
- DONE → RETRY ❌         (완료 후 재시도 불가)
- RETRY → ESCALATE ❌     (BLOCKED 경유 필수)
- BLOCKED → DISPATCH ❌   (ESCALATE로만 가능)
```

### 표준 경로

```
행복 경로: DISPATCH → DONE
재시도 경로: DISPATCH → RETRY → DISPATCH → DONE
에스컬레이션 경로: DISPATCH → BLOCKED → ESCALATE → DONE
```

### Retry Escalation 불변조건

| 원칙 | 설명 |
|------|------|
| **Monotonic** | 에스컬레이션 레벨은 절대 감소하지 않음 (SELF_REPAIR → ROLE_SWITCH → HARD_FAIL) |
| **Terminal** | HARD_FAIL은 시스템 종료점. 이후 모든 실패는 HARD_FAIL 유지 |
| **Once** | ROLE_SWITCH는 프로필당 1회만 허용. 2회 시도 시 즉시 abort |

### 에스컬레이션 트리거 조건

```
EscalationReason 자동 감지:
- DEPLOY: 배포, production, 릴리즈
- API_KEY: api key, 토큰, credential
- PAYMENT: 결제, billing, 비용
- DATA_DELETE: 삭제, delete, drop, truncate
- DEPENDENCY: pip install, npm install
- SECURITY: 보안, auth, 권한
```

### CEO 개입이 필요한 경우

1. **HARD_FAIL 도달**: 동일 에러 3회 반복 (self-repair + role-switch 모두 실패)
2. **BLOCKED → ESCALATE**: 정보 부족, 모순된 요구사항, 권한 필요
3. **EscalationReason 감지**: 배포/결제/보안 등 민감 작업

### 코드 참조

```python
# src/core/decision_machine.py
ALLOWED_TRANSITIONS = {
    PMDecision.DISPATCH: {PMDecision.RETRY, PMDecision.DONE, PMDecision.BLOCKED},
    PMDecision.RETRY: {PMDecision.DISPATCH, PMDecision.BLOCKED},
    PMDecision.BLOCKED: {PMDecision.ESCALATE},
    PMDecision.ESCALATE: {PMDecision.DONE},
    PMDecision.DONE: set(),  # Terminal state
}

# src/services/cli_supervisor.py
EscalationLevel:
- SELF_REPAIR (count=1): 에러 피드백 포함 재시도
- ROLE_SWITCH (count=2): 다른 역할로 전환 (1회 제한)
- HARD_FAIL (count≥3): CEO 에스컬레이션
```

---

## v2.5.5 아키텍처 (2026-01-07)

**핵심 변경**: RAG Agent Filter + 에이전트별 컨텍스트 주입

### v2.5.5 신규 변경사항

1. **RAG Agent Filter**: 에이전트별 임베딩 검색 필터링
   - `search(agent_filter=...)`: 특정 에이전트 임베딩만 검색
   - `search_by_agent(agent, ...)`: 에이전트별 검색 헬퍼 함수
   - `build_context(agent_filter=..., session_id=...)`: 에이전트별 컨텍스트 빌드

2. **index_document() agent 컬럼 저장 수정**
   - 기존: metadata에 agent 있어도 embeddings.agent 컬럼에 저장 안 됨
   - 수정: `agent` 파라미터 추가, metadata에서도 자동 추출

3. **에이전트별 RAG 컨텍스트 주입** (`llm_caller.py`)
   - PM: 전체 검색 (top_k=5)
   - Coder/QA/Strategist/Researcher: 에이전트별 필터 (top_k=3)
   - `RAG_ENABLED_AGENTS = ["pm", "coder", "qa", "strategist", "researcher"]`

### RAG Agent Filter 흐름
```
메시지 저장 (database.add_message)
    │
    ├─ agent 파라미터 전달 → embedding_queue.enqueue_message()
    │                           │
    │                           └─ EmbeddingTask.metadata["agent"]
    │
    └─ 임베딩 워커 처리 → rag.index_document(agent=...)
                              │
                              └─ embeddings.agent 컬럼에 저장 ✅

LLM 호출 (call_agent)
    │
    ├─ PM → rag.build_context(agent_filter=None, top_k=5)
    │           └─ 전체 임베딩 검색
    │
    └─ Coder/QA/... → rag.build_context(agent_filter="coder", top_k=3)
                          └─ WHERE agent = 'coder' 필터링
```

### RAG 함수 시그니처 (v2.5.5)
```python
# 검색
search(
    query: str,
    project: Optional[str] = None,
    top_k: int = 5,
    agent_filter: Optional[str] = None  # NEW
) -> List[Dict]

# 에이전트별 검색 헬퍼
search_by_agent(
    agent: str,
    query: str,
    project: Optional[str] = None,
    top_k: int = 3
) -> List[Dict]

# 컨텍스트 빌드
build_context(
    query: str,
    project: Optional[str] = None,
    agent_filter: Optional[str] = None,  # NEW
    top_k: int = 5,
    use_gemini: bool = True,
    language: str = "en",
    session_id: Optional[str] = None  # NEW
) -> str

# 인덱싱
index_document(
    source_type: str,
    source_id: str,
    content: str,
    metadata: Dict[str, Any] = None,
    project: Optional[str] = None,
    source: str = "web",
    agent: Optional[str] = None  # NEW - metadata["agent"]에서도 자동 추출
) -> str
```

---

## v2.5.4 아키텍처 (2026-01-07)

**핵심 변경**: PM Decision Machine + Semantic Guard + Retry Escalation

### v2.5.4 신규 변경사항

1. **PM Decision Machine**: summary → enum 변환 (인간 흉내 제거)
   - PM JSON → `DecisionOutput` 정형화
   - `PMDecision` enum: DISPATCH, ESCALATE, DONE, BLOCKED, RETRY
   - summary는 로그용, 의사결정에 사용 금지
   - 의미 없는 summary → confidence 감소 (0.5)

2. **CLI Semantic Guard** (v2.5.3): 코드 기반 의미 검증
   - 의미적 NULL 패턴 블랙리스트
   - 프로필별 필드 규칙

3. **Retry Escalation 시스템** (v2.5.2): 동일 실패 반복 방지
   - 3단계 에스컬레이션: Self-repair → Role-switch → Hard Fail

### PM Decision Machine 흐름
```
PM JSON 출력 → DecisionMachine.process()
    │
    ├─ action: "DISPATCH" → PMDecision.DISPATCH + targets 추출
    ├─ action: "ESCALATE" → PMDecision.ESCALATE + reason 자동 추론
    ├─ action: "DONE" → PMDecision.DONE
    └─ tasks 없음 → PMDecision.BLOCKED

summary 검증:
    ├─ "검토했습니다", "진행하겠습니다" 등 → confidence = 0.5
    └─ 유효한 내용 → confidence = 1.0
```

### Decision Enums
```python
PMDecision:     DISPATCH | ESCALATE | DONE | BLOCKED | RETRY
EscalationReason: deploy | api_key | payment | data_delete | dependency | security
```

### Semantic Guard 검사 항목
```
의미적 NULL 블랙리스트:
- 한글: 검토했습니다, 확인했습니다, 문제없습니다, 진행하겠습니다
- 영어: looks good, no issues, seems fine, I have reviewed

프로필별 규칙:
- coder: summary(10자+동사+대상), diff(20자+형식), files_changed(필수)
- qa: verdict(PASS/FAIL/SKIP), tests(PASS시 필수)
- reviewer: verdict(APPROVE/REVISE/REJECT), score(0-10), risks(REJECT시 필수)
- council: score(0-10), reasoning(20자 이상)
```

### Semantic + Retry 통합 흐름
```
LLM 응답 → JSON 파싱 → Semantic Guard
    │                        │
    │                        ├─ 의미적 NULL? → SEMANTIC_NULL 에러
    │                        ├─ 필드 규칙 위반? → FIELD_TOO_SHORT, INVALID_VALUE 등
    │                        └─ 통과 → 성공 반환
    │
    └─ JSON 파싱 실패 → JSON_PARSE_ERROR
                            │
                            └─→ RetryEscalator 편입
                                    │
                                    ├─ count=1 → SELF_REPAIR
                                    ├─ count=2 → ROLE_SWITCH
                                    └─ count≥3 → HARD_FAIL
```

### Escalation API
```
GET  /api/monitor/escalation       - 에스컬레이션 상태 조회
POST /api/monitor/escalation/clear - 히스토리 초기화
```

---

## v2.4 아키텍처 (2026-01-07)

**핵심 변경**: Dual Engine V3 + Persona Pack + CEO→PM Only Routing

### v2.4 신규 변경사항

1. **Dual Engine V3**: Write → Audit → Rewrite 패턴 (붙여넣기 방식 폐기)
2. **Persona Pack**: 역할별 JSON 출력 강제 페르소나 (.claude/agents/*.md)
3. **CEO→PM Only Routing**: CEO는 PM만 호출 가능, 하위 에이전트 직접 호출 차단
4. **GPT-5 mini 제거**: 모든 Auditor를 Claude CLI Sonnet 4로 통일
5. **Researcher Writer**: Perplexity Sonar Pro로 변경 (Gemini Flash → Perplexity)

### 모델 티어 시스템 v2.4
```
BUDGET        Gemini 2.0 Flash         (Analyst 로그 압축)
EXEC          Claude CLI Opus 4.5      (Coder Writer)
              Claude CLI Sonnet 4      (PM, QA, Auditor, Stamp, Council)
VIP-THINKING  GPT-5.2 Thinking Extended(Strategist/Excavator Writer)
RESEARCH      Perplexity Sonar Pro     (Researcher Writer, "검색/" 프리픽스)
VIP-AUDIT     Claude CLI Opus 4.5      ("최고/" 프리픽스)
```

### Dual Engine 역할별 모델 매핑
| 역할 | Writer | Auditor | Stamp |
|------|--------|---------|-------|
| coder | Claude CLI Opus 4.5 (coder) | Claude CLI Sonnet 4 (reviewer) | Claude CLI Sonnet 4 |
| strategist | GPT-5.2 Thinking Extended | Claude CLI Sonnet 4 | Claude CLI Sonnet 4 |
| qa | Claude CLI Sonnet 4 (qa) | Claude CLI Sonnet 4 | Claude CLI Sonnet 4 |
| researcher | Perplexity Sonar Pro | Claude CLI Sonnet 4 | Claude CLI Sonnet 4 |
| excavator | GPT-5.2 Thinking Extended | Claude CLI Sonnet 4 | Claude CLI Sonnet 4 |

### Single Engine
| 역할 | 모델 | 설명 |
|------|------|------|
| pm | Claude CLI Sonnet 4 (reviewer) | Bureaucrat Router |
| analyst | Gemini 2.0 Flash | Log Summarizer |

### Persona Pack (.claude/agents/)
```
.claude/agents/
├── GLOBAL_RULES.md      # 공통 헌법
├── pm.md                # Bureaucrat Router
├── coder.md             # Silent Implementer (Opus 4.5)
├── stamp.md             # Strict Verdict Clerk
├── coder-reviewer.md    # Devil's Advocate
├── qa.md                # Test Designer
├── qa-reviewer.md       # Breaker
├── strategist.md        # Systems Architect
├── excavator.md         # Requirements Interrogator
├── researcher.md        # Source Harvester (Perplexity)
├── analyst.md           # Log Summarizer (Gemini)
└── council.md           # 7-member Jury
```

### CEO 라우팅 규칙
```
CEO ─────┬──→ PM ✅ (유일하게 허용)
         │
         ├──✗ Coder      ❌ 차단
         ├──✗ QA         ❌ 차단
         ├──✗ Strategist ❌ 차단
         └──✗ ...        ❌ 차단

PM ──────┬──→ [CALL:coder]      ✅ (_internal_call=True)
         ├──→ [CALL:qa]         ✅
         ├──→ [CALL:strategist] ✅
         └──→ ...               ✅
```

---

## v2.3 아키텍처 (2026-01-06)

**핵심 변경**: Hook Chain 기반 내부통제 시스템 추가

### v2.3 신규 패키지

#### 1. src/hooks/ - Hook Chain System
```
hooks/
├── __init__.py     # 패키지 엔트리
├── base.py         # Hook, HookContext, HookResult 기본 클래스
├── pre_run.py      # 세션 규정 로드 + rules_hash 계산
├── pre_review.py   # Static Gate (0원 1차 게이트)
├── post_review.py  # 감사 로그 기록
├── stop.py         # StopCode Enum (실패/중단 사유)
└── chain.py        # HookChain 체인 실행기
```

**훅 흐름**:
```
PRE_RUN → PRE_REVIEW (Static Gate) → LLM Review → POST_REVIEW → STOP
```

#### 2. src/context/ - Context Management
```
context/
├── __init__.py
├── counter.py      # TokenCounter (토큰 사용량 추적)
├── compactor.py    # Preemptive Compaction (85% 임계치)
└── injector.py     # Constitution + Session Rules 주입
```

#### 3. src/control/ - 내부통제 시스템
```
control/
├── constitution.py   # 헌법 (절대 금지)
├── rules.py          # SessionRules Pydantic 스키마
├── rules_store.py    # JSON 파일 로더
├── jsonc_parser.py   # JSONC (JSON with Comments) 파서 [NEW]
├── static_check.py   # AST + Regex 정적 검사
├── prompt_injector.py
├── verdict.py
├── audit_log.py
└── event_bus.py
```

#### 4. src/services/router.py - Router Agent [NEW]
PM 병목 해소를 위한 자동 태스크 라우팅:
- 키워드 기반 + LLM 하이브리드 라우팅
- CEO 프리픽스 강제 라우팅 (검색/, 코딩/, 분석/)
- 에이전트: Coder, Excavator, QA, Researcher, Analyst, Strategist, PM

### Session Rules (config/session_rules/)
```json
// live-trade-btc-001.json
{
  "session_id": "live-trade-btc-001",
  "mode": "live",
  "risk_profile": "strict",
  "rules": {
    "trading": {"market_order": "forbid", "max_order_usd": 100},
    "code": {"forbid_sleep_in_api_loop": true, "secrets_hardcoding": "forbid"},
    "quality": {"allow_skip_tests": false, "max_files_changed": 12}
  }
}
```

### Static Gate 검사 항목
- API Key 패턴 감지 (OpenAI, AWS, GitHub, Slack, Google)
- 무한루프 감지 (while True without break)
- Sleep in loop 감지

---

## v2.2.1 아키텍처

**핵심 철학**: Docker Worker-Reviewer Pair + JSONL 영속화
- 9개 Docker 컨테이너로 분산 처리
- DB는 web만 소유, 워커는 HTTP API로 접근
- 모든 대화가 parent_id로 연결되어 JSONL에 저장

### 모델 티어 시스템 v2.2.1
```
BUDGET        Gemini 2.0 Flash      (요약/정리/대용량)
STANDARD      GPT-5.2 pro (medium)  (PM-Worker 기본)
VIP-THINKING  GPT-5.2 pro (high)    (에러+원인일 때만)
EXEC          Claude Code CLI       (Coder/QA/Reviewer 전용)
RESEARCH      Perplexity Sonar Pro  (최신/검색)
SAFETY        Claude Opus 4.5       (Security Hawk 감사)
```

### Worker-Reviewer Pair 매핑
| Container | LLM | Persona | 권한 |
|-----------|-----|---------|------|
| web | - | Control Tower | RW (DB 소유) |
| pm-worker | GPT-5.2 Thinking | Strategist | RO |
| pm-reviewer | Claude CLI | Skeptic | RO |
| coder-worker | Claude CLI | Implementer | **RW** |
| coder-reviewer | Claude CLI | Devil's Advocate | RO |
| qa-worker | Claude CLI | Tester | tests/ RW |
| qa-reviewer | Claude CLI | Breaker | RO |
| reviewer-worker | Gemini 2.5 Flash | Pragmatist | RO |
| reviewer-reviewer | Claude CLI | Security Hawk | RO |

## 기술 스택
- **Backend**: Flask (Blueprint 구조)
- **DB**: SQLite (hattz_empire.db)
- **Frontend**: Vanilla JS + CSS
- **LLM**: Anthropic, OpenAI, Google, Perplexity

## 폴더 구조
```
hattz_empire/
├── app.py                 # Entry point
├── config.py              # 설정 (모델, 에이전트)
├── src/
│   ├── api/               # Blueprint routes
│   │   ├── chat.py        # 채팅 API (abort 기능 포함)
│   │   ├── sessions.py    # 세션 관리
│   │   ├── tasks.py       # 백그라운드 작업
│   │   ├── breaker.py     # Circuit Breaker
│   │   ├── council_api.py # 위원회
│   │   ├── monitor.py     # 에이전트 모니터 API (NEW)
│   │   └── health.py      # 헬스체크 + 임베딩 큐 상태
│   ├── core/              # 비즈니스 로직
│   │   ├── llm_caller.py  # LLM 호출
│   │   └── router.py      # 라우팅
│   ├── services/          # 서비스 레이어
│   │   ├── database.py    # DB + 자동 임베딩 enqueue
│   │   ├── background_tasks.py
│   │   ├── embedding_queue.py  # 비동기 임베딩 (NEW)
│   │   ├── agent_monitor.py    # 작업 추적 (NEW)
│   │   └── rag.py         # RAG 검색/인덱싱
│   └── infra/             # 인프라
│       ├── circuit_breaker.py
│       └── council.py
├── static/
│   ├── js/chat.js         # 클라이언트 로직
│   └── css/style.css      # 반응형 스타일
└── templates/
    ├── chat.html
    └── monitor.html       # 에이전트 모니터 대시보드 (NEW)
```

## 주요 기능

### 1. 멀티 에이전트 시스템
- PM, Excavator, Coder, QA, Strategist, Analyst, Researcher
- 자동 티어 승격 (Budget → Standard → VIP)

### 2. Circuit Breaker (circuit_breaker.py)
- 무한 루프/비용 폭발 방지
- 호출 횟수 제한 (태스크당 10회)
- 비용 한도 (태스크 $0.50, 세션 $5, 일일 $10)
- 반복 응답 감지 (85% 유사도)
- 에이전트 핑퐁 감지

### 3. Persona Council (council.py)
- 7개 페르소나: Skeptic, Perfectionist, Pragmatist, Pessimist, Optimist, Devil's Advocate, Security Hawk
- 5개 위원회: Code, Strategy, Security, Deploy, MVP
- 병렬 심사 + 점수 집계

### 4. Abort 기능 (최근 추가)
- 서버 측 스트리밍 중단 기능
- `active_streams` 딕셔너리로 스트림 추적
- `/api/chat/abort` 엔드포인트
- 클라이언트 AbortController + 서버 abort flag

### 5. 백그라운드 작업
- 웹 닫아도 계속 실행
- 진행 상태 위젯
- 완료 알림

### 6. 임베딩 큐 시스템 (embedding_queue.py)
- 메시지 저장 시 자동 임베딩 enqueue
- 백그라운드 워커가 비동기 처리
- `/api/health/embedding-queue`로 상태 확인
- 싱글톤 패턴, 자동 재시도 로직

### 7. 에이전트 모니터 (/monitor)
- PM이 `[CALL:agent]` 태그로 에이전트 호출 시 자동 추적
- 실시간 SSE 스트림으로 상태 업데이트
- 작업 상태: running, success, failed
- DB에 작업 이력 저장

## 최근 작업 내역

### 세션 10 (2026-01-07) - v2.5.5 RAG Agent Filter

에이전트별 RAG 검색 필터링 및 컨텍스트 주입 시스템 구현:

1. **RAG Agent Filter 구현** (`src/services/rag.py`)
   - `search()`: `agent_filter` 파라미터 추가
   - `search_by_agent()`: 에이전트별 검색 헬퍼 함수 신설
   - `build_context()`: `agent_filter`, `session_id` 파라미터 추가

2. **index_document() agent 컬럼 버그 수정**
   - 버그: `metadata["agent"]`가 있어도 `embeddings.agent` 컬럼에 저장 안 됨
   - 원인: INSERT문에 agent 컬럼 누락
   - 수정: `agent` 파라미터 추가 + metadata에서 자동 추출 + INSERT에 agent 포함

3. **embedding_queue.py 수정**
   - `_process_task()`: `agent=task.metadata.get("agent")` 전달

4. **llm_caller.py 에이전트별 RAG 주입**
   - `RAG_ENABLED_AGENTS`: pm, coder, qa, strategist, researcher
   - PM: 전체 검색 (agent_filter=None, top_k=5)
   - 나머지: 에이전트별 필터 (agent_filter=role, top_k=3)

5. **QA 테스트 결과** (5/5 통과)
   - index_document() - agent parameter ✅
   - search() - agent_filter ✅
   - search_by_agent() helper ✅
   - build_context() - agent_filter ✅
   - agent extraction from metadata ✅

---

### 세션 9 (2026-01-07) - v2.5.2 Retry Escalation 시스템

동일 실패 반복 방지를 위한 에스컬레이션 시스템 구현:

1. **Retry Escalation 핵심 클래스** (`src/services/cli_supervisor.py`)
   - `FailureSignature`: 실패 시그니처 (error_type, missing_fields, profile, prompt_hash)
   - `EscalationLevel`: SELF_REPAIR → ROLE_SWITCH → HARD_FAIL
   - `RetryEscalator`: 실패 히스토리 관리 + 에스컬레이션 결정

2. **에스컬레이션 로직**
   - 같은 시그니처 1번: Self-repair (에러 피드백 포함 재시도)
   - 같은 시그니처 2번: Role-switch (coder→reviewer 등 역할 전환)
   - 같은 시그니처 3번+: Hard Fail (즉시 중단, PM 에스컬레이션)

3. **call_cli() 개선**
   - 기존 단순 재시도 로직 → 에스컬레이션 기반 재시도
   - JSON 검증 실패 시 시그니처 기반 에스컬레이션
   - 타임아웃/일반 에러도 에스컬레이션 적용
   - 역할 전환 시 메타데이터 기록 (role_switched, original_profile)

4. **모니터링 API** (`src/api/monitor.py`)
   - `GET /api/monitor/escalation`: 에스컬레이션 상태 조회
   - `POST /api/monitor/escalation/clear`: 히스토리 초기화

5. **CLIResult 확장**
   - `escalation_level`: 에스컬레이션 레벨
   - `role_switched`: 역할 전환 여부
   - `original_profile`: 원래 프로필

---

### 세션 8-1 (2026-01-07) - v2.4.1 Analyst 파일 컨텍스트 주입

Analyst(Gemini Flash)가 파일시스템에 접근할 수 없는 문제 해결:

1. **문제점**
   - Analyst가 프로젝트 분석 요청 받으면 "프로젝트 디렉토리가 존재하지 않음" 에러
   - 원인: Gemini Flash API는 파일시스템 접근 불가

2. **해결책: `collect_project_context()` 함수 추가**
   - 위치: `src/core/llm_caller.py`
   - 기능: 프로젝트 파일 구조 + 주요 파일 내용을 자동 수집
   - 프로젝트별 루트 경로 매핑 (`PROJECT_PATHS`)

3. **자동 컨텍스트 주입**
   - `call_agent()`에서 `agent_role == "analyst"`일 때 자동 주입
   - 수집 내용:
     - 파일 구조 (Python 파일 수, Markdown 파일 수)
     - 디렉토리별 파일 목록
     - 주요 파일 내용 (CLAUDE.md, config.py, app.py 등)
     - 테스트 파일 수 (품질 지표)
   - 최대 30,000자 제한

4. **지원 프로젝트**
   - `hattz_empire`: 현재 프로젝트
   - `wpcn`: WPCN 백테스터 프로젝트

---

### 세션 8 (2026-01-07) - v2.4 Dual Engine V3 + Persona Pack

Dual Engine V3 아키텍처 완성 및 페르소나 시스템 구축:

1. **Dual Engine V3 패턴**
   - Write → Audit → Rewrite (붙여넣기 방식 폐기)
   - Auditor JSON verdict: `APPROVE | REVISE | REJECT`
   - max 3회 rewrite 후 Council 소집

2. **Persona Pack 생성** (`.claude/agents/`)
   - `GLOBAL_RULES.md`: 공통 헌법 (잡담 금지, JSON 출력, CEO 에스컬레이션 조건)
   - 12개 페르소나 파일 생성/업데이트

3. **모델 변경**
   - Researcher Writer: Gemini Flash → Perplexity Sonar Pro
   - Coder Writer: Claude CLI Opus 4.5 확인 (coder profile)
   - 모든 Auditor: Claude CLI Sonnet 4로 통일

4. **CEO→PM Only Routing**
   - CEO는 PM만 직접 호출 가능
   - 하위 에이전트는 PM의 `[CALL:*]` 태그로만 호출

5. **Docker 수정**
   - `Dockerfile.monitor`: COPY 경로 수정 (`docker/` prefix)
   - grafana 권한: `grafana:grafana` → `472:0`

6. **문서 업데이트**
   - `ai_team_아키텍쳐.md` → v2.4
   - `CLAUDE.md` → v2.4

---

### 세션 7-3 (2026-01-06) - v2.3.1 위원회 DB 저장 + 임베딩

위원회 판정을 DB에 저장하고 임베딩되도록 개선:

1. **council.py 업그레이드**
   - `_save_persona_judgment_to_db()`: 개별 페르소나 판정 저장
   - `_save_council_verdict_to_db()`: 최종 판정 저장
   - `set_session_context()`: 세션/프로젝트 컨텍스트 설정
   - `get_council(session_id, project)`: 싱글톤에 세션 전달

2. **저장 구조**
   - `agent`: `council_skeptic`, `council_pragmatist` 등
   - `model_id`: `council-skeptic`, `council-code-verdict` 등
   - `is_internal`: True (웹에 안 보임, DB/임베딩만)

3. **council_api.py 업그레이드**
   - `session_id`, `project` 파라미터 추가
   - API 호출 시 자동 DB 저장

4. **웹 출력 vs DB 분리**
   - 웹: `is_internal=False`만 표시 (요약된 결과)
   - DB: 전체 저장 (에이전트/위원회 대화 포함)
   - 임베딩 큐: 10자 이상 자동 임베딩 → RAG 검색 가능

---

### 세션 7-2 (2026-01-06) - v2.3 chat.py 통합 완료

chat.py에 Hook Chain, Router Agent, TokenCounter 연동:

1. **chat.py Router Agent 연동**
   - `auto_route=true` 파라미터로 자동 라우팅 활성화
   - `auto_route_agent()` 헬퍼 함수 추가
   - AgentType → 실제 에이전트 role 매핑
   - CEO 프리픽스(검색/, 코딩/, 분석/)로 강제 라우팅

2. **chat.py Hook Chain 연동**
   - `run_pre_run_hook()` 헬퍼 함수: 세션 규정 로드
   - `run_static_gate()` 헬퍼 함수: 0원 1차 검사
   - SSE 스트림에 `route_info`, `rules_hash`, `token_stats` 전송

3. **TokenCounter 세션 적용**
   - `_session_counters`: 세션별 TokenCounter 관리
   - `get_token_counter()`: Lazy initialization
   - 85% 임계치에서 compaction_needed 플래그 전송

4. **Static Gate 통합**
   - 하위 에이전트 응답에 Static Gate 적용
   - Hook session_rules 우선 사용 (Fallback: 기존 방식)
   - `static_gate_reject` 이벤트로 클라이언트 경고

5. **테스트 추가**
   - `tests/test_v23_hooks.py`: 단위 테스트 (8/8 통과)
   - `tests/test_v23_api.py`: API 통합 테스트

---

### 세션 7 (2026-01-06) - v2.3 Hook Chain 아키텍처

oh-my-opencode 분석 기반 내부통제 시스템 구축:

1. **hooks/ 패키지 구현**
   - `PreRunHook`: 세션 규정 로드, rules_hash 계산
   - `PreReviewHook`: Static Gate (0원 1차 게이트)
   - `PostReviewHook`: 감사 로그 기록
   - `StopHook`: StopCode Enum (COMPLETED, STATIC_REJECT, LLM_REJECT 등)
   - `HookChain`: 체인 실행기 + `create_default_chain()`

2. **context/ 패키지 구현**
   - `TokenCounter`: 토큰 사용량 추적 (85% 경고, 압축 임계치)
   - `Compactor`: Preemptive Compaction (휴리스틱 + LLM 요약)
   - `ContextInjector`: Constitution + Session Rules 프롬프트 주입

3. **JSONC 파서 추가** (`src/control/jsonc_parser.py`)
   - // 라인 주석, /* */ 블록 주석 지원
   - 후행 쉼표 허용
   - `JsoncRulesStore`: .json/.jsonc 모두 지원

4. **Router Agent 신설** (`src/services/router.py`)
   - PM 병목 해소를 위한 자동 태스크 라우팅
   - 키워드 기반 + LLM 하이브리드 라우팅
   - CEO 프리픽스: 검색/, 코딩/, 분석/

5. **ReviewerService Hook 통합**
   - `review_with_hooks()` 메서드 추가
   - Static Gate → LLM Review → Audit Log 전체 흐름

6. **Static Checker 패턴 강화**
   - `sk-proj-*` OpenAI 프로젝트 키 감지
   - Generic `api_key=`, `secret_key=` 패턴 추가

---

### 세션 6 (2026-01-06) - Docker + JSONL Persistence

1. **JSONL 영속화 구현** (`src/api/jobs.py`)
   - `_save_to_jsonl()` 함수 추가
   - 모든 대화가 `parent_id`로 연결되어 저장
   - CEO → PM-Worker → PM-Reviewer → ... 체인 추적
   - 저장 경로: `src/infra/conversations/stream/YYYY-MM-DD.jsonl`

2. **Docker Compose 수정**
   - YAML 앵커 중복 오류 수정 (각 서비스 명시적 정의)
   - `docker/Dockerfile.web`: apt-key → gpg --dearmor 방식 변경
   - `requirements.txt`: psutil 추가

3. **Jobs API 테스트 완료**
   - POST /api/jobs/create → 작업 생성
   - GET /api/jobs/pull → 작업 가져오기
   - POST /api/jobs/push → 결과 제출 (JSONL 저장 + 다음 단계 자동 생성)

4. **문서 업데이트**
   - `ai_team_아키텍쳐.md` → v2.2.1
   - `docs/session_backup_20260106.md` 생성
   - `PROMPT.md` → v2.2.1
   - `CLAUDE.md` → v2.2.1

---

### 세션 5 (2026-01-04)
1. **CSS 반응형 추가 수정** - 80% 축소 시에도 버튼 안 잘리도록
   - `.header-left`에 `min-width: 0`, `flex-shrink: 1`, `overflow: hidden`
   - `.status` 텍스트("Ready") 숨김, 점만 표시
   - `.admin-dropdown-btn` 패딩/폰트 축소 (6px 10px, 11px)
   - `.abort-button` "중단" 텍스트 숨김, 아이콘만 표시
   - `.processing-bar` 높이/패딩 축소 (44px, 10px 12px)
   - `.processing-stage` 숨김 처리
2. **Git 커밋 & 푸시** - `e6ad617` hattz_empire 저장소
3. **대화 백업 & 임베딩** - 4개 새로 인덱싱 완료

---

### 세션 4
1. **[CALL:agent] 태그 감지 문제 수정**
   - **문제**: PM이 `[CALL:coder]`, `[CALL:qa]` 출력해도 백엔드에서 감지 못함
   - **원인**: `executor.py`의 CALL_PATTERN 정규식이 `\n` 필수로 요구
   - **수정**: `\s*\n` → `[\s\n]*` (줄바꿈 유무 모두 지원)
   ```python
   # src/services/executor.py
   CALL_PATTERN = re.compile(
       r'\[CALL:(\w+)\][\s\n]*(.*?)(?=\[/CALL\]|\[CALL:|\Z)',
       re.DOTALL
   )
   ```
   - **추가 에이전트**: `qa_logic`, `strategist`, `analyst`를 `CALLABLE_AGENTS`에 추가

2. **디버그 로깅 추가** (`src/api/chat.py`)
   ```python
   has_calls = executor.has_call_tags(pm_response)
   print(f"[DEBUG] has_call_tags: {has_calls}")
   print(f"[DEBUG] PM response (last 500 chars): {pm_response[-500:]}")
   ```

3. **CEO 프리픽스 기능** (`src/core/llm_caller.py`, `src/core/router.py`)
   - `최고/` : Opus 4.5 (VIP-AUDIT) 강제
   - `생각/` : GPT-5.2 Thinking Extend (VIP-THINKING) 강제
   - `검색/` : Perplexity Sonar Pro (RESEARCH) 강제

4. **ngrok 고정 도메인 설정**
   - URL: `https://caitlyn-supercivilized-intrudingly.ngrok-free.app`
   - 실행: `ngrok http 5000 --domain=caitlyn-supercivilized-intrudingly.ngrok-free.app`

5. **Git 작업**
   - master 브랜치 삭제, main으로 통합
   - dev → main 머지

### 미해결 이슈
- **위젯 사라짐 문제**: PM 응답 후 `done: true`가 바로 전송되어 위젯이 닫힘
- **테스트 필요**: PM이 올바른 형식(`[CALL:agent]\n메시지\n[/CALL]`)으로 출력하는지 확인

---

### 세션 3
1. **CSS 반응형 수정** - 80% 축소 시 버튼 잘림 문제 해결
   - `.chat-header`, `.processing-bar`에 `flex-wrap` 추가
   - `.abort-button`, `.header-right`에 `flex-shrink: 0` 추가
   - 992px 이하에서 텍스트 숨기고 아이콘만 표시
2. **WPCN 프로젝트 Git 작업**
   - charNavi 저장소에 push
   - QWAS-SYS-15M-V1 브랜치 → main 병합
   - 브랜치 rename: QWAS-SYS-15M-V1 → dev

### 세션 2
1. **임베딩 큐 시스템 구현** (`src/services/embedding_queue.py`)
   - 비동기 백그라운드 임베딩 처리
   - 싱글톤 패턴, 자동 재시도
   - `database.py`의 `add_message()`에서 자동 enqueue
2. **에이전트 모니터 대시보드** (`/monitor`)
   - `src/services/agent_monitor.py` - 실시간 작업 추적
   - `src/api/monitor.py` - SSE 스트림 API
   - `templates/monitor.html` - 대시보드 UI
   - PM의 `[CALL:agent]` 태그 처리 시 자동 추적
3. **RAG 테이블명 수정** - `messages` → `chat_messages`

### 세션 1
1. Blueprint 기반 모듈화 완료
2. 서버 측 Abort 기능 구현
3. 백그라운드 작업 위젯 추가

## Jobs API (v2.2.1)

Docker 워커들이 HTTP로 작업을 주고받는 핵심 API.

### Endpoints
| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/jobs/pull?role=X&mode=Y` | 대기 중인 작업 가져오기 |
| POST | `/api/jobs/push` | 작업 결과 제출 |
| POST | `/api/jobs/create` | 새 작업 생성 (파이프라인 시작) |
| GET | `/api/jobs/status` | 작업 상태 요약 |

### 파이프라인 흐름
```
CEO → PM-Worker → PM-Reviewer → CODER-Worker → CODER-Reviewer
    → QA-Worker → QA-Reviewer → Reviewer-Worker → Reviewer-Reviewer → SHIP
```

### Verdict 규칙
- **APPROVE**: 다음 단계로 진행
- **REVISE**: 이전 Worker에게 재작업 요청 (MAX_REWORK_ROUNDS=2)
- **HOLD**: 파이프라인 중단 + CEO 개입 요청
- **SHIP**: 최종 승인 (Reviewer-Reviewer만 사용)

### JSONL 영속화
모든 대화가 `parent_id`로 연결되어 저장:
```
저장 경로: src/infra/conversations/stream/YYYY-MM-DD.jsonl

{
  "id": "msg_20260106_120000_abc123",
  "t": "2026-01-06T12:00:00.000000",
  "from_agent": "pm-worker",
  "to_agent": "pipeline",
  "type": "response",
  "content": "TaskSpec: ...",
  "parent_id": "msg_20260106_115959_def456",
  "metadata": {"job_id": "...", "verdict": "APPROVE"}
}
```

## 개발 시 참고사항

### 로컬 개발
- Flask 서버: `python app.py` (포트 5000)
- ngrok 터널: `ngrok http 5000 --domain=caitlyn-supercivilized-intrudingly.ngrok-free.app`
- 로그인: admin/admin

### Docker 환경
```bash
# 빌드 & 실행
docker-compose up -d --build

# 로그 확인
docker-compose logs -f web

# 종료
docker-compose down
```

## CEO 프로필
- ID: 하홍구 (Hattz)
- 특성: 의식의 흐름 입력, 완벽주의 트랩
- AI 대응: 말 안 한 것까지 추론, MVP로 유도

---

## Claude Code CLI 체제 (v2.1.1 - Silence the Chatter)

Claude는 **EXEC(실행부대)**로만 쓴다.
설계/추론/라우팅(뇌)은 OpenAI API(GPT-5.2 pro)가 담당하고, Claude Code CLI는 **레포를 손으로 만지는 역할**만 한다.

### 공통 규칙 (v2.1.1)
- 설명/인사/추임새 금지.
- 기본 출력은 **unified diff**.
- 코드 외 텍스트는 주석으로만 허용.
- 비밀키/토큰/자격증명 출력 금지.
- **불가능하면 `# ABORT: [이유]` 한 줄만 출력.**

### 역할별 모드
| 역할 | 목표 | 출력 |
|------|------|------|
| Coder | TaskSpec → 최소 diff | diff, 주석으로 짧은 근거 |
| QA | PASS/FAIL 판정 | JSON 또는 테스트 코드 diff |
| Reviewer | 리스크 차단 | JSON (APPROVE/REQUEST_CHANGES) |

### 서브에이전트 파일 (.claude/agents/)
| 파일 | 역할 | 허용 도구 | 출력 |
|------|------|----------|------|
| `coder.md` | 코드 구현 | Edit, Write, Read, Bash, Glob | diff만 |
| `qa.md` | 테스트/검증 | Bash, Read, Glob (쓰기 금지) | JSON verdict |
| `reviewer.md` | 보안/리스크 | Read, Glob, Grep (읽기 전용) | JSON status |

**사용법**: CLI Supervisor가 `--allowedTools`로 프로필별 도구 제한

### 작업 플로우 (권장)
1. **CEO 입력** → Web/UI로 들어옴
2. **PM/Router (GPT-5.2 pro)**
   - 작업 분해 + TaskSpec(JSON) 생성
   - 필요하면 Strategist(VIP-THINKING)로 조건부 승격
3. **Coder (Claude Code CLI)**
   - TaskSpec에 따라 **코드/패치만** 생성
   - 장문 설명 금지 (주석으로 최소)
4. **QA (Claude Code CLI)**
   - 테스트 실행/재현/검증
   - FAIL이면 Coder로 회귀
5. **Reviewer (Claude Code CLI)**
   - 변경 리스크/보안/품질 점검
   - REQUEST_CHANGES면 Coder로 회귀
6. **CEO 보고**
   - 최종 diff/결과/실행 로그만 전달

### Coder "Code Only" 규칙
- 출력은 가능한 한 unified diff(또는 파일별 변경 내용)만
- 테스트 코드는 QA가 작성
- 설명이 필요하면 코드 주석으로만 최소한

### 라우팅 규칙 v2.1
- "왜" 같은 단어 하나로 VIP 태우지 않음
- 에러 컨텍스트(Traceback/Exception) + 원인 키워드 → VIP-THINKING
- 키워드만 있고 에러 없음 → STANDARD로 충분

---

## CLI Supervisor (v2.1.1)

Claude Code CLI 세션 관리 및 장애 복구 시스템.

### 위치
`src/services/cli_supervisor.py`

### 기능
1. **타임아웃 감지** - 5분 초과 시 태스크 분할 후 재시도
2. **컨텍스트 초과 감지** - Gemini로 요약 후 재시도
3. **자동 재시도** - 최대 2회 (치명적 에러 제외)
4. **세션 복구** - DB에서 최근 10개 메시지 로드
5. **ABORT 처리** - `# ABORT: [이유]` 감지 시 PM에게 리포트

### 에러 처리 흐름
```
CLI 호출 실패
    ├─ 컨텍스트 초과? → Gemini 요약 → 재시도
    ├─ 타임아웃? → 태스크 분할 → 재시도
    ├─ 치명적 에러? → ABORT (재시도 불가)
    └─ 일반 에러? → 2초 대기 → 재시도 (max 2회)

최대 재시도 초과 → ABORT 리포트 → PM 에스컬레이션
```

### 사용 예시
```python
from src.services.cli_supervisor import call_claude_cli, recover_and_continue

# 일반 호출 (llm_caller에서 자동 사용)
result = call_claude_cli(messages, system_prompt, profile="coder")

# 세션 복구 후 재개
result = recover_and_continue(session_id, "이전 작업 계속해줘", profile="coder")
```

### 설정 (cli_supervisor.py)
```python
CLI_CONFIG = {
    "timeout_seconds": 300,      # 5분 타임아웃
    "max_retries": 2,            # 최대 재시도 횟수
    "context_recovery_limit": 10, # 복구 시 가져올 메시지 수
    "output_max_chars": 50000,   # 출력 최대 길이
}
```
