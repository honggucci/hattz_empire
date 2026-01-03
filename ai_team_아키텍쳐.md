# HATTZ EMPIRE - AI Orchestration System

> **2026.01 | Multi-Dual-Engine Architecture**

---

## System Overview

```
                         ┌──────────────────────┐
                         │   CEO (하홍구)        │
                         │  의식의 흐름 입력     │
                         └──────────┬───────────┘
                                    │ (Korean)
                    ┌───────────────▼────────────────┐
                    │   Flask Web Interface          │
                    │   localhost:5000               │
                    └────────────┬──────────────────┘
                                 │
┌────────────────────────────────┼────────────────────────────────┐
│                        AGENT LAYER                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─── DUAL ENGINES ──────────────────────────────────────────┐ │
│  │                                                            │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │ │
│  │  │  EXCAVATOR   │  │  STRATEGIST  │  │    CODER     │     │ │
│  │  │ Claude+GPT5  │  │ GPT5+Gemini  │  │ Claude+GPT5  │     │ │
│  │  │  consensus   │  │  consensus   │  │primary_fallbk│     │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │ │
│  │                                                            │ │
│  │  ┌──────────────┐  ┌──────────────┐                       │ │
│  │  │      QA      │  │  RESEARCHER  │                       │ │
│  │  │ GPT5+Claude  │  │Gemini+Claude │                       │ │
│  │  │   parallel   │  │  consensus   │                       │ │
│  │  └──────────────┘  └──────────────┘                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─── SINGLE ENGINES ────────────────────────────────────────┐ │
│  │  ┌──────────────┐  ┌──────────────┐                       │ │
│  │  │     PM       │  │   ANALYST    │                       │ │
│  │  │ Claude Opus  │  │ Gemini 3 Pro │                       │ │
│  │  │ 오케스트레이션 │  │ 1M Context   │                       │ │
│  │  └──────────────┘  └──────────────┘                       │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Dual Engine 상세 구성

### EXCAVATOR (CEO 의도 발굴)

| 구분 | 상세 |
|------|------|
| **역할** | CEO 의식의 흐름 → 숨은 의도 발굴 → 선택지 생성 |
| **Engine 1** | Claude Opus 4.5 (감성/맥락/뉘앙스) |
| **Engine 2** | GPT-5.2 Thinking Extended (논리/구조화) |
| **Merge Strategy** | `consensus` - 둘의 합의 |
| **Temperature** | Opus: 0.5 / GPT: 0.2 |
| **Output** | `ExcavatorOutput` (explicit, implicit, questions, confidence) |

```
┌─ EXCAVATOR ──────────────────────────────────────────────────────┐
│                                                                  │
│  Engine 1: Claude Opus 4.5                                      │
│    ├─ Temperament: Empathetic Listener                          │
│    ├─ Strength: Nuance/Context/Emotion understanding            │
│    └─ Focus: "CEO가 진짜 원하는 게 뭐야?"                        │
│                                                                  │
│  Engine 2: GPT-5.2 Thinking Extended                            │
│    ├─ Temperament: Logical Analyzer                             │
│    ├─ Strength: Structure/Categorization/Clarity                │
│    └─ Focus: "모호함을 구체적 선택지로"                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

### STRATEGIST (전략 연구)

| 구분 | 상세 |
|------|------|
| **역할** | 전략 설계 + 리스크 분석 + 실패 시나리오 |
| **Engine 1** | GPT-5.2 (전진 - "결정안 + 근거") |
| **Engine 2** | Gemini 3.0 Pro (브레이크 - "반례 + 리스크") |
| **Merge Strategy** | `consensus` |
| **Temperature** | GPT: 0.2 / Gemini: 1.0 |
| **Output** | `StrategyOutput` (decision, rationale, risks, failure_scenarios) |

```
┌─ STRATEGIST ─────────────────────────────────────────────────────┐
│                                                                  │
│  Engine 1: GPT-5.2 (Pragmatist - 전진 담당)                     │
│    ├─ "그래서 이번 스프린트에 뭘 하냐"                           │
│    ├─ "근거 뭐냐"                                               │
│    └─ 옵션 5개 나열 금지 → 결정안 1개 + 근거                    │
│                                                                  │
│  Engine 2: Gemini 3.0 (Contrarian - 브레이크 담당)              │
│    ├─ "이거 반대로 보면?"                                       │
│    ├─ "실패 시나리오부터 깔자"                                  │
│    └─ 결론 없는 비판 금지 → 반례 + 대응책                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

### CODER (코드 구현)

| 구분 | 상세 |
|------|------|
| **역할** | 클린 코드 생성 + 아키텍처 설계 + 엣지케이스 |
| **Engine 1** | Claude Opus (Primary - 고품질 코드) |
| **Engine 2** | GPT-5.2 (Reviewer - 버그/엣지케이스) |
| **Merge Strategy** | `primary_fallback` - Opus 우선, 실패시 GPT |
| **Temperature** | Opus: 0.5 / GPT: 0.2 |
| **Output** | `CodeOutput` (code, files, dependencies, complexity) |

```
┌─ CODER ──────────────────────────────────────────────────────────┐
│                                                                  │
│  Engine 1: Claude Opus (Primary)                                │
│    ├─ Temperament: Perfectionist Pragmatist                     │
│    ├─ "깔끔하게, 근데 끝내자"                                   │
│    └─ 과도한 추상화/프레임워크 욕심 금지                        │
│                                                                  │
│  Engine 2: GPT-5.2 (Reviewer)                                   │
│    ├─ Temperament: Skeptic Perfectionist                        │
│    ├─ "왜 이렇게 했지?"                                         │
│    └─ 전면 재설계 금지 → 버그/엣지케이스/누락만 지적            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

### QA (품질 검증)

| 구분 | 상세 |
|------|------|
| **역할** | 로직 검증 + 보안 스캔 + 테스트 케이스 |
| **Engine 1** | GPT-5.2 (로직 - 엣지케이스/불변조건) |
| **Engine 2** | Claude Opus (보안 - OWASP/취약점) |
| **Merge Strategy** | `parallel` - 합집합 (둘 다의 이슈 수집) |
| **Temperature** | GPT: 0.2 / Opus: 0.5 |
| **Output** | `QAOutput` (status, issues, test_cases, security_scan) |

```
┌─ QA ─────────────────────────────────────────────────────────────┐
│                                                                  │
│  Engine 1: GPT-5.2 (Logic)                                      │
│    ├─ Temperament: Skeptic Perfectionist                        │
│    ├─ "이거 테스트 안 해봤지?"                                  │
│    └─ 엣지케이스/불변조건/백테스트-라이브 괴리 집요하게 파기    │
│                                                                  │
│  Engine 2: Claude Opus (Security)                               │
│    ├─ Temperament: Pessimist Devil's Advocate                   │
│    ├─ "해커 입장에서 볼게. 여기 뚫림"                           │
│    └─ OWASP Top 10 + injection/auth/exposure 스캔              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

### RESEARCHER (외부 검색)

| 구분 | 상세 |
|------|------|
| **역할** | 외부 데이터 검색 + 팩트체크 + 정보 검증 |
| **Engine 1** | Gemini 3.0 Pro (수집 - 웹 검색/패턴 발견) |
| **Engine 2** | Claude Opus (검증 - 신뢰도/팩트체크) |
| **Merge Strategy** | `consensus` |
| **Temperature** | Gemini: 1.0 / Opus: 0.5 |
| **Output** | `ResearchOutput` (findings, key_insights, sources, warnings) |

```
┌─ RESEARCHER ─────────────────────────────────────────────────────┐
│                                                                  │
│  Engine 1: Gemini 3.0 Pro (Collection)                          │
│    ├─ Temperament: Detective Explorer                           │
│    ├─ "어디서 정보를 더 찾을 수 있지?"                          │
│    └─ 대용량 웹 데이터 처리, 패턴 발견                          │
│                                                                  │
│  Engine 2: Claude Opus (Verification)                           │
│    ├─ Temperament: Skeptic Fact-Checker                         │
│    ├─ "소스가 뭐야? 신뢰할 수 있어?"                            │
│    └─ 정보 검증, 신뢰도 평가, 팩트체크                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Single Engine 에이전트

### PM (Project Manager)

| 구분 | 상세 |
|------|------|
| **역할** | 오케스트레이션, 작업 위임, 결과 종합 |
| **Engine** | Claude Opus 4.5 |
| **Temperature** | 0.5 |

### ANALYST (시스템 분석)

| 구분 | 상세 |
|------|------|
| **역할** | 로그 분석, 패턴 탐지, 시스템 모니터링 |
| **Engine** | Gemini 3.0 Pro (1M Context) |
| **Temperature** | 1.0 |
| **특징** | 100만 토큰 컨텍스트 활용 |

---

## Agent Chain 실행 흐름

```
CEO Input (Korean)
      │
      ▼
┌──────────────┐
│  EXCAVATOR   │ → ExcavatorOutput (explicit/implicit/confidence)
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                    TASK TYPE DETECTION                        │
├──────────────────────────────────────────────────────────────┤
│  CODE?     → Coder → QA → Combined Output                    │
│  STRATEGY? → Strategist → Risk Analysis                       │
│  ANALYSIS? → Analyst → Historical Insights                    │
│  RESEARCH? → Researcher → Web Data + Verification             │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
Response (Korean) → CEO Display
```

### Code Chain (코드 작업)

```
Excavator → Coder (Dual) → QA (Dual) → Final Code + Test Cases
```

### Strategy Chain (전략 작업)

```
Excavator → Strategist (Dual) → Decision + Risks + Failure Scenarios
```

### Analysis Chain (분석 작업)

```
Excavator → Analyst (Single) → Insights + Patterns + Recommendations
```

### Research Chain (검색 작업)

```
Excavator → Researcher (Dual) → Findings + Sources + Fact-Check
```

---

## API Endpoints

### Chat Operations

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/chat` | 단일 턴 대화 |
| POST | `/api/chat/stream` | 스트리밍 대화 (SSE) |
| GET | `/api/history` | 현재 세션 히스토리 |
| POST | `/api/history/clear` | 히스토리 초기화 |

### Session Management

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/sessions` | 세션 목록 |
| POST | `/api/sessions` | 새 세션 생성 |
| GET | `/api/sessions/<id>` | 세션 상세 |
| DELETE | `/api/sessions/<id>` | 세션 삭제 |

### Execution

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/execute` | [EXEC] 태그 실행 |
| POST | `/api/execute/batch` | 배치 실행 |

### Projects

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/projects` | 프로젝트 목록 |
| GET | `/api/projects/<id>/files` | 프로젝트 파일 |

### Health Check

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/health/<provider>` | API 상태 (openai/anthropic/google) |
| GET | `/api/health/db` | DB 연결 상태 |

---

## Storage Layer

### MSSQL Database

```
┌─ Tables ─────────────────────────────────────────────────────────┐
│  chat_sessions  - 세션 메타데이터 (id, name, project, agent)    │
│  chat_messages  - 대화 내역 (session_id, role, content, agent)  │
│  tasks          - 작업 추적 (id, title, status, created_by)     │
│  logs           - 시스템 로그 (source, level, message)          │
└──────────────────────────────────────────────────────────────────┘
```

### File Storage

```
┌─ Paths ──────────────────────────────────────────────────────────┐
│  conversations/stream/YYYY-MM-DD.jsonl  - 스트림 로그 (JSONL)   │
│  conversations/tasks/YYYY-MM-DD_NNN.yaml - 태스크 파일          │
│  storage/index.db                        - SQLite FTS 인덱스    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Files

| 파일 | 역할 |
|------|------|
| `config.py` | 모델 설정, 듀얼 엔진, 시스템 프롬프트, CEO 프로필 |
| `app.py` | Flask API 엔드포인트 |
| `agent_chain.py` | 에이전트 체인 오케스트레이션 |
| `stream.py` | 로깅 시스템 (append-only JSONL) |
| `context_loader.py` | 세션 컨텍스트 복원 |
| `executor.py` | 코드/명령어 실행 (보안 샌드박스) |
| `database.py` | MSSQL 연결 및 CRUD |
| `agents/base.py` | 듀얼 엔진 베이스 클래스 |
| `agents/excavator.py` | CEO 의도 발굴 |
| `agents/strategist.py` | 전략 연구 |
| `agents/coder.py` | 코드 생성 |
| `agents/qa_dual.py` | 품질 검증 |
| `agents/analyst.py` | 시스템 분석 |
| `agents/researcher.py` | 외부 검색 |

---

## Model Configuration

### Claude Opus 4.5

```yaml
Provider: anthropic
Model ID: claude-opus-4-5-20251101
Temperature: 0.5
Max Tokens: 8192
Use Cases: Excavator(E1), Coder(E1), QA(E2), Researcher(E2), PM
```

### GPT-5.2 Thinking Extended

```yaml
Provider: openai
Model ID: gpt-5.2
Temperature: 0.2
Max Tokens: 16384
Thinking Mode: Enabled
Use Cases: Excavator(E2), Strategist(E1), Coder(E2), QA(E1)
```

### Gemini 3.0 Pro

```yaml
Provider: google
Model ID: gemini-3-pro-preview
Temperature: 1.0
Max Tokens: 16384
Context Window: 1M tokens
Use Cases: Strategist(E2), Researcher(E1), Analyst
```

---

## CEO Profile

```yaml
Name: 하홍구 (Hattz)
Role: System Architect / Visionary
Saju: 己酉일주, Metal 과다 (4), 식신격, 신약

Characteristics:
  - Input: 의식의 흐름 (10% 명시, 90% 숨겨짐)
  - Thinking: Metal 과다 → 분석/생각 과잉
  - Weakness: 완벽주의 트랩, 고립 경향

AI Must Do:
  - 말 안 한 것까지 추론해서 끄집어내기
  - 모호한 입력 → 구체적 선택지로 변환
  - 완벽주의 감지시 "80% MVP로 가자" 유도
  - 감정 차단, 로직으로 전환
```

---

## Critical Stance (비판적 스탠스)

모든 에이전트가 공유하는 원칙:

1. **오냐오냐 금지** - CEO가 원한다고 다 해주지 마라
2. **희망회로 금지** - "잘 될 거야"는 근거가 아님
3. **리스크 먼저** - 기회보다 위험을 먼저 분석
4. **근거 필수** - 추측만 나열하고 질문 안 하면 실패
5. **MVP 유도** - 완벽주의 감지시 즉시 개입

---

## Environment Variables

```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...

# Database
MSSQL_SERVER=localhost
MSSQL_DATABASE=hattz_empire
MSSQL_USER=sa
MSSQL_PASSWORD=...

# Flask
FLASK_SECRET_KEY=hattz-empire-secret-key-2024
```

---

## Quick Start

```bash
# 1. 환경 설정
cd hattz_empire
pip install -r requirements.txt

# 2. .env 파일 설정
cp .env.example .env
# API 키 입력

# 3. 서버 실행
python app.py

# 4. 브라우저 접속
http://localhost:5000
```

---

*Last Updated: 2026-01-03*
