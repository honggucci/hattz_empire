# HATTZ EMPIRE - AI Orchestration System v2.2.1

> **2026.01.06 | Docker Worker-Reviewer Pair Architecture**
> **비용 86% 절감 + 품질 유지 + JSONL 영속화**

---

## System Overview v2.2.1

```
                         ┌──────────────────────┐
                         │   CEO (하홍구)        │
                         │  의식의 흐름 입력     │
                         └──────────┬───────────┘
                                    │ (Korean)
                    ┌───────────────▼────────────────┐
                    │     Docker Container: WEB      │
                    │   Flask + ngrok + supervisord  │
                    │   DB 소유자 (SQLite)           │
                    │   localhost:5000               │
                    └────────────┬──────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │           Jobs API (HTTP)           │
              │   /api/jobs/pull  /api/jobs/push    │
              └──────────────────┬──────────────────┘
                                 │
┌────────────────────────────────┼────────────────────────────────┐
│                    WORKER-REVIEWER PAIRS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─── PM LAYER ────────────────────────────────────────────┐   │
│  │  PM-Worker     : GPT-5.2 Thinking    (Strategist)       │   │
│  │  PM-Reviewer   : Claude CLI          (Skeptic)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓ APPROVE                              │
│  ┌─── CODER LAYER ─────────────────────────────────────────┐   │
│  │  Coder-Worker  : Claude CLI (RW)     (Implementer)      │   │
│  │  Coder-Reviewer: Claude CLI (RO)     (Devil's Advocate) │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓ APPROVE                              │
│  ┌─── QA LAYER ────────────────────────────────────────────┐   │
│  │  QA-Worker     : Claude CLI (tests/ RW) (Tester)        │   │
│  │  QA-Reviewer   : Claude CLI (RO)        (Breaker)       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓ APPROVE                              │
│  ┌─── REVIEWER LAYER ──────────────────────────────────────┐   │
│  │  Reviewer-Worker  : Gemini 2.5 Flash (Pragmatist)       │   │
│  │  Reviewer-Reviewer: Claude CLI       (Security Hawk)    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          ↓ SHIP                                 │
│                    [Pipeline Complete]                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Docker Architecture (9 Containers)

### Container 구성

| Container | LLM | Persona | 권한 | 역할 |
|-----------|-----|---------|------|------|
| **web** | - | Control Tower | RW | DB 소유, Flask + ngrok |
| **pm-worker** | GPT-5.2 Thinking | Strategist | RO | 태스크 분해, 전략 |
| **pm-reviewer** | Claude CLI | Skeptic | RO | 전략 검증 |
| **coder-worker** | Claude CLI | Implementer | **RW** | 코드 구현 |
| **coder-reviewer** | Claude CLI | Devil's Advocate | RO | 코드 리뷰 |
| **qa-worker** | Claude CLI | Tester | tests/ RW | 테스트 작성 |
| **qa-reviewer** | Claude CLI | Breaker | RO | 테스트 검증 |
| **reviewer-worker** | Gemini 2.5 Flash | Pragmatist | RO | 최종 리뷰 |
| **reviewer-reviewer** | Claude CLI | Security Hawk | RO | 보안 감사 |

### Docker Files

```
docker/
├── Dockerfile.web      # Flask + Gunicorn + ngrok + supervisord
├── Dockerfile.api      # Python only (OpenAI/Gemini API)
├── Dockerfile.claude   # Python + Node.js + Claude CLI
└── supervisord.conf    # gunicorn + ngrok 동시 실행

docker-compose.yml      # 9개 컨테이너 오케스트레이션
```

---

## JSONL 영속화 (v2.2.1 NEW)

### 대화 연결 구조

모든 에이전트 간 대화가 `parent_id`로 연결되어 저장됩니다:

```
CEO → PM-Worker → PM-Reviewer → CODER-Worker → ...
  │        │            │
  └────────┴────────────┴── parent_id로 연결

JSONL 파일: src/infra/conversations/stream/YYYY-MM-DD.jsonl
```

### 메시지 구조

```json
{
  "id": "msg_20260106_120000_abc123",
  "t": "2026-01-06T12:00:00.000000",
  "from_agent": "pm-worker",
  "to_agent": "pipeline",
  "type": "response",
  "content": "TaskSpec: ...",
  "parent_id": "msg_20260106_115959_def456",
  "metadata": {
    "job_id": "...",
    "task_id": "...",
    "verdict": "APPROVE",
    "success": true
  }
}
```

---

## Jobs API

### Endpoints

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/jobs/pull?role=X&mode=Y` | 대기 중인 작업 가져오기 |
| POST | `/api/jobs/push` | 작업 결과 제출 |
| POST | `/api/jobs/create` | 새 작업 생성 (파이프라인 시작) |
| GET | `/api/jobs/status` | 작업 상태 요약 |
| GET | `/api/jobs/list` | 최근 작업 목록 |

### 파이프라인 흐름

```
1. POST /api/jobs/create (CEO 요청)
   → PM-Worker pending 작업 생성
   → JSONL 저장: ceo → pm-worker (request)

2. PM-Worker가 pull → 처리 → push
   → JSONL 저장: pm-worker → pipeline (response)
   → PM-Reviewer pending 작업 자동 생성
   → JSONL 저장: pipeline → pm-reviewer (request)

3. PM-Reviewer가 pull → 검증 → push (APPROVE)
   → JSONL 저장: pm-reviewer → pipeline (review)
   → CODER-Worker pending 작업 자동 생성
   → ...

4. 최종 Reviewer가 SHIP
   → JSONL 저장: pipeline → ceo (complete)
   → Pipeline 완료
```

### 핑퐁 방지

```
MAX_REWORK_ROUNDS = 2

Worker → Reviewer (REVISE) → Worker (재작업)
Worker → Reviewer (REVISE) → Worker (재작업)
Worker → Reviewer (REVISE) → CEO 개입 요청 (escalation)
```

---

## 핵심 설계 원칙

### 1. SQLite 락지옥 방지

```
❌ 기존: 9개 컨테이너가 SQLite 직접 접근 → 락 충돌
✅ 변경: DB는 web만 소유, 워커는 HTTP API로 접근
```

### 2. 권한 분리

```
coder-worker : ./:/app:rw         # 유일하게 전체 RW
qa-worker    : ./tests:/app/tests:rw  # tests만 RW
나머지       : ./:/app:ro         # 읽기 전용
```

### 3. Claude CLI 구독 사용

```yaml
# docker-compose.yml
environment:
  - ANTHROPIC_API_KEY=  # 비우면 Pro/Max 구독으로 CLI 실행
```

### 4. 컨텍스트 오염 방지

```
❌ 세션 이어가기 → 이전 대화가 영향
✅ TaskSpec 패킷 주입 → 매번 새로운 컨텍스트
```

---

## Subagent 시스템

### 페르소나 정의

```
.claude/agents/
├── pm-reviewer.md      # Skeptic - 전략 의심
├── coder-worker.md     # Implementer - diff만 출력
├── coder-reviewer.md   # Devil's Advocate - 코드 반박
├── qa-worker.md        # Tester - 테스트 작성
├── qa-reviewer.md      # Breaker - 엣지케이스 공격
└── security-hawk.md    # Security Hawk - SHIP/HOLD 결정
```

### Output Styles

```
.claude/output-styles/
├── silent-diff.md      # diff만, 설명 금지
└── verdict-only.md     # APPROVE/REVISE/SHIP/HOLD만
```

---

## 비용 효율

### 모델 티어별 사용량

| 티어 | 모델 | 사용 비율 | 비용 (per 1M) |
|------|------|----------|---------------|
| BUDGET | Gemini 2.0 Flash | 80% | $0.10/$0.40 |
| STANDARD | Claude Sonnet 4 | 15% | $3/$15 |
| VIP | Opus 4.5 / GPT Thinking | 5% | $5/$25 |

### 절감 효과

```
💰 월간 예상 (10,000 requests):
   Before: $323
   After:  $45.60
   절감:   $277.40/월 (85.9%)
```

---

## Quick Start (Docker)

```bash
# 1. .env 설정
cp .env.example .env
# API 키 입력

# 2. Docker 빌드 & 실행
docker-compose up -d --build

# 3. 로그 확인
docker-compose logs -f web

# 4. 테스트
curl http://localhost:5000/api/health/ping

# 5. 작업 생성
curl -X POST http://localhost:5000/api/jobs/create \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "role": "pm", "mode": "worker"}'

# 6. 종료
docker-compose down
```

---

## Key Files

| 파일 | 역할 |
|------|------|
| `docker-compose.yml` | 9개 컨테이너 오케스트레이션 |
| `src/api/jobs.py` | Jobs API + JSONL 저장 |
| `src/workers/agent_worker.py` | HTTP 기반 워커 |
| `src/infra/conversations/stream/` | JSONL 대화 로그 |
| `.claude/agents/*.md` | Subagent 페르소나 |

---

*Last Updated: 2026-01-06 | Hattz Empire v2.2.1 (Docker + JSONL Persistence)*
