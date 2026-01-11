# Hattz Empire - Architecture History

**주요 아키텍처 전환점 및 설계 철학 문서**

---

## 목차
1. [Worker-Reviewer Pair → Dual Engine V3](#1-worker-reviewer-pair--dual-engine-v3)
2. [Docker 분산 → 단일 Flask 앱 회귀](#2-docker-분산--단일-flask-앱-회귀)
3. [Persona 시스템 도입](#3-persona-시스템-도입)
4. [PM Decision Machine](#4-pm-decision-machine)
5. [Hook Chain 아키텍처](#5-hook-chain-아키텍처)
6. [비용 최적화 전략](#6-비용-최적화-전략)

---

## 1. Worker-Reviewer Pair → Dual Engine V3

### 초기 설계 (v2.2.1 - 2026-01-06)

**Worker-Reviewer Pair 패턴**:
```
PM-Worker (GPT-5.2) → PM-Reviewer (Claude CLI)
Coder-Worker (Claude CLI) → Coder-Reviewer (Claude CLI)
QA-Worker (Claude CLI) → QA-Reviewer (Claude CLI)
Reviewer-Worker (Gemini 2.5) → Reviewer-Reviewer (Claude CLI)
```

**문제점**:
1. **컨텍스트 오염**: Worker 출력을 Reviewer에게 붙여넣기 → 누적 오염
2. **비용 폭발**: 동일 작업을 2번 LLM에게 전달
3. **복잡도**: 9개 Docker 컨테이너 관리 오버헤드
4. **세션 이어가기 불가**: 컨테이너 재시작 시 컨텍스트 손실

### Dual Engine V3 (v2.4 - 2026-01-07)

**Write → Audit → Rewrite 패턴**:
```
Writer LLM → Auditor LLM (JSON verdict) → Writer LLM (rewrite)
                │
                ├─ APPROVE → 다음 단계
                ├─ REVISE → Writer에게 피드백 + 재작성
                └─ REJECT (3회 초과) → Council 소집
```

**개선사항**:
1. **컨텍스트 분리**: Writer와 Auditor가 독립적인 세션
2. **비용 절감**: 필요할 때만 재작성 (APPROVE 시 즉시 통과)
3. **단일 프로세스**: Flask 앱 하나로 통합
4. **재시도 제어**: max 3회 rewrite 후 Council 소집

**코드 위치**: `src/services/cli_supervisor.py`

---

## 2. Docker 분산 → 단일 Flask 앱 회귀

### Docker 9개 컨테이너 구조 (v2.2.2)

**배경**: 역할별 독립 실행 환경 제공

**구조**:
```
hattz_web (Flask + ngrok + Gunicorn)
├─ hattz_pm_worker
├─ hattz_pm_reviewer
├─ hattz_coder_worker (RW)
├─ hattz_coder_reviewer (RO)
├─ hattz_qa_worker (tests RW)
├─ hattz_qa_reviewer (RO)
├─ hattz_reviewer_worker
└─ hattz_reviewer_reviewer (RO)
```

**문제점**:
1. **Volume Mount 복잡도**: 권한 관리 (RW vs RO)
2. **Claude CLI 인증**: 각 컨테이너마다 `claude login` 필요
3. **네트워크 오버헤드**: Jobs API HTTP 통신
4. **디버깅 어려움**: 로그가 9개 컨테이너에 분산

### 단일 Flask 앱 (v2.4 이후)

**구조**:
```
Flask App (app.py)
├─ Dual Engine (cli_supervisor.py)
│  ├─ Writer (Claude CLI Opus 4.5)
│  └─ Auditor (Claude CLI Sonnet 4)
├─ PM (Claude CLI Sonnet 4)
├─ Council (7개 페르소나 병렬)
└─ Analyst (Gemini 2.0 Flash)
```

**개선사항**:
1. **간편한 배포**: Python app.py + ngrok 터널
2. **인증 단순화**: 1회 `claude login`으로 모든 역할 사용 가능
3. **로그 통합**: 단일 프로세스 로그
4. **개발 속도**: 수정 후 즉시 재시작

**코드 위치**: `app.py`, `src/api/chat.py`

---

## 3. Persona 시스템 도입

### 배경 (v2.4 - 2026-01-07)

**문제**: LLM이 자기 역할을 명확히 인지하지 못함
- Coder가 전략 제안
- Strategist가 코드 작성
- Reviewer가 구현 수정

### Persona Pack (.claude/agents/)

**구조**:
```
.claude/agents/
├── GLOBAL_RULES.md      # 공통 헌법 (모든 에이전트)
├── pm.md                # Bureaucrat Router
├── coder.md             # Silent Implementer
├── stamp.md             # Strict Verdict Clerk
├── coder-reviewer.md    # Devil's Advocate
├── qa.md                # Test Designer
├── qa-reviewer.md       # Breaker
├── strategist.md        # Systems Architect
├── excavator.md         # Requirements Interrogator
├── researcher.md        # Source Harvester
├── analyst.md           # Log Summarizer
└── council.md           # 7-member Jury
```

### 역할 경계 강제 (HARD BLOCK)

| 역할 | 허용 | 금지 |
|------|------|------|
| PM | 상태 전이, 라우팅 | 코드, 전략, 구현 |
| Strategist | 옵션, 리스크, 추천 | 코드, 파일명, 함수명 |
| Coder | 구현, diff | 전략, 대안 제시 |
| QA | 테스트, 검증 | 구현 변경 |
| Reviewer | 리스크 검토 | 코드 수정 |

### 부트로더 원칙 (v2.5.5)

**핵심 철학**: FLOW는 프롬프트가 아니라 부트로더

1. **에이전트는 서로의 존재를 모른다.** PM만 전체를 안다.
2. **에이전트는 대화하지 않는다.** 계약(JSON)만 주고받는다.
3. **FLOW는 협업이 아니라 상태 전이다.**
4. **역할 침범 = 프로토콜 위반 = INVALID 출력.**

**코드 위치**: `.claude/agents/GLOBAL_RULES.md`

---

## 4. PM Decision Machine

### 초기 설계 (v2.4 이전)

**문제**: PM이 summary 텍스트로 의사결정
```python
if "coder에게 할당" in pm_response:
    route_to_coder()
elif "전략 검토 필요" in pm_response:
    route_to_strategist()
```

**문제점**:
1. **불확실성**: 텍스트 기반 파싱
2. **인간 흉내**: "검토했습니다", "진행하겠습니다" 같은 무의미한 출력
3. **디버깅 어려움**: 왜 이 결정을 내렸는지 추적 불가

### PMOutput Contract (v2.5.4)

**enum 기반 의사결정**:
```python
class PMOutput(BaseModel):
    action: Literal["DISPATCH", "ESCALATE", "DONE", "BLOCKED", "RETRY"]
    tasks: List[TaskSpec]  # DISPATCH일 때
    summary: str = Field(..., max_length=100)  # 로그용만
    requires_ceo: bool = False
```

**상태 전이 그래프 (v2.5.5)**:
```
ALLOWED_TRANSITIONS:
┌─────────────┬────────────────────────────────────────────┐
│ From State  │ Allowed To States                          │
├─────────────┼────────────────────────────────────────────┤
│ DISPATCH    │ RETRY, DONE, BLOCKED                       │
│ RETRY       │ DISPATCH, BLOCKED                          │
│ BLOCKED     │ ESCALATE                                   │
│ ESCALATE    │ DONE                                       │
│ DONE        │ (terminal)                                 │
└─────────────┴────────────────────────────────────────────┘
```

**개선사항**:
1. **결정론적**: enum 기반 파싱
2. **추적 가능**: action만 보면 다음 단계 명확
3. **불변조건**: 허용된 전이만 통과
4. **summary 제한**: 100자 이내 (시인 되는 거 방지)

**코드 위치**: `src/core/contracts.py`, `src/core/decision_machine.py`

---

## 5. Hook Chain 아키텍처

### 배경 (v2.3 - 2026-01-06)

**문제**: LLM 호출 전후 검증 로직이 분산
- Static check: `executor.py`에 하드코딩
- Token count: `chat.py`에서 수동 체크
- Audit log: 각 에이전트마다 중복 코드

### Hook Chain 패턴

**흐름**:
```
PRE_RUN → PRE_REVIEW (Static Gate) → LLM Review → POST_REVIEW → STOP
```

**Hook 종류**:
| Hook | 역할 | 비용 |
|------|------|------|
| PRE_RUN | 세션 규정 로드, rules_hash 계산 | 0원 |
| PRE_REVIEW | Static Gate (API 키 감지, 무한루프 감지) | 0원 |
| LLM Review | LLM에게 코드 리뷰 요청 | $0.001~$0.01 |
| POST_REVIEW | 감사 로그 기록, 이벤트 발행 | 0원 |
| STOP | 실패/중단 코드 기록 | 0원 |

**개선사항**:
1. **0원 1차 게이트**: Static Gate로 명백한 위반 즉시 차단
2. **컨텍스트 주입**: Constitution + Session Rules 자동 주입
3. **토큰 관리**: 85% 임계치에서 자동 압축
4. **감사 추적**: 모든 결정이 audit_log에 기록

**코드 위치**: `src/hooks/`, `src/context/`

---

## 6. 비용 최적화 전략

### HattzRouter v2.0 (2026-01-03)

**4티어 시스템**:
```
BUDGET        Gemini 2.0 Flash         (~$0.0001/req)
STANDARD      GPT-5.2 pro (medium)     (~$0.003/req)
VIP-THINKING  GPT-5.2 pro (high)       (~$0.02/req)
EXEC          Claude CLI Opus 4.5      (~$0.015/req)
RESEARCH      Perplexity Sonar Pro     (~$0.005/req)
```

**자동 승격 규칙**:
1. **고위험 키워드** → VIP
   - api_key, production, deploy, payment, delete
2. **추론 키워드 + 에러** → VIP-THINKING
   - "왜", "원인", "분석" + Traceback 존재
3. **검색 키워드** → RESEARCH
   - "검색", "최신", "동향", "트렌드"

**비용 절감 결과**:
- **86% 절감**: $32.30 → $4.56 per 1K requests
- Budget 80%, Standard 15%, VIP 5%

### Gemini 요약 전략

**대용량 파일 처리** (v2.0):
```python
if file_size > 10KB:
    summary = gemini_flash.summarize(content)
    # 비용: $0.00001 (Claude 대비 1/1000)
```

**RAG 검색 결과 요약** (v2.0):
```python
if search_results > 5:
    summary = gemini_flash.summarize(results)
    # 비용: $0.00001
```

**코드 위치**: `src/core/router.py`, `src/services/executor.py`, `src/services/rag.py`

---

## 주요 아키텍처 원칙 요약

| 원칙 | 설명 | 버전 |
|------|------|------|
| **Persona as Contract** | 역할 = JSON 계약 | v2.4 |
| **State over Chat** | 대화 X, 상태 전이 O | v2.5.4 |
| **Static First** | LLM 호출 전 0원 검증 | v2.3 |
| **Tier by Risk** | 위험도별 모델 선택 | v2.0 |
| **Dual Engine** | Write + Audit 분리 | v2.4 |
| **Hook Chain** | 전후 처리 체인화 | v2.3 |
| **Monotonic Escalation** | 에스컬레이션은 감소 안 함 | v2.5.2 |
| **Agent Filter RAG** | 에이전트별 임베딩 검색 | v2.5.5 |

---

## 버전 히스토리 요약

| 버전 | 날짜 | 핵심 변경 | 아키텍처 영향 |
|------|------|----------|--------------|
| v2.0 | 2026-01-03 | HattzRouter, Agent Scorecard | 비용 최적화 기반 마련 |
| v2.1 | 2026-01-04 | CEO 프리픽스, ngrok 고정 | CEO 통제력 강화 |
| v2.2 | 2026-01-06 | Docker 9개 컨테이너, JSONL | 분산 아키텍처 시도 |
| v2.3 | 2026-01-06 | Hook Chain, Context Management | 내부통제 시스템 구축 |
| v2.4 | 2026-01-07 | Dual Engine V3, Persona Pack | 역할 경계 강제 |
| v2.5 | 2026-01-07 | PM Decision Machine, Semantic Guard, RAG Filter | 결정론적 의사결정 |
| v2.6 | 2026-01-08 | 문서 정리, Persona 최신화 | 문서 체계화 |

---

## 폐기된 설계들

### 1. Worker-Reviewer Pair (v2.2.2)
**폐기 이유**: 컨텍스트 오염, 비용 폭발, 복잡도
**대체**: Dual Engine V3

### 2. Docker 9개 컨테이너 (v2.2.2)
**폐기 이유**: 인증 복잡도, 네트워크 오버헤드, 디버깅 어려움
**대체**: 단일 Flask 앱

### 3. 텍스트 기반 PM 라우팅 (v2.4 이전)
**폐기 이유**: 불확실성, 인간 흉내
**대체**: PMOutput Contract (enum)

### 4. GPT-5 mini (v2.4)
**폐기 이유**: 품질 불안정, Claude Sonnet과 비용 차이 미미
**대체**: Claude CLI Sonnet 4로 통일

### 5. Gemini Flash Researcher (v2.4)
**폐기 이유**: 최신 정보 부족, 검색 품질 낮음
**대체**: Perplexity Sonar Pro

---

## 다음 진화 방향 (추측)

1. **Agent Router 확장**: PM 병목 완전 해소
2. **Multi-Modal Support**: 이미지/오디오 입력
3. **Fine-tuned Models**: 역할별 전용 모델
4. **Distributed Tracing**: OpenTelemetry 통합
5. **Self-Healing**: 자동 에러 복구 + 학습

---

*Last Updated: 2026-01-09*
