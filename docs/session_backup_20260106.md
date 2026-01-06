# Hattz Empire Session Backup - 2026-01-06

## Session Summary: v2.2.2 Docker Full Run

### 주요 작업

#### 1. Test 계정 추가
- **id**: `test` / **password**: `1234`
- **allowed_projects**: `["test"]` (test 프로젝트만 접근 가능)
- User 클래스에 `allowed_projects` 필드 추가
- `/api/projects` 엔드포인트에서 사용자별 프로젝트 필터링

#### 2. Docker 전체 실행 성공 (9개 컨테이너)
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

#### 3. ODBC Driver 수정
- ODBC Driver 17 → 18 변경 (Docker용)
- `TrustServerCertificate=yes` 추가
- 환경변수 `ODBC_DRIVER`로 오버라이드 가능

#### 4. ngrok 설정
- `.env`에 `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` 추가
- 고정 도메인: `caitlyn-supercivilized-intrudingly.ngrok-free.app`

#### 5. 시작 스크립트
- `start.bat`: Flask + ngrok 동시 실행 (로컬용)
- `stop.bat`: 프로세스 종료

---

## 핵심 파일 변경사항

| 파일 | 변경 내용 |
|------|----------|
| [src/utils/auth.py](../src/utils/auth.py) | User 모델에 allowed_projects 추가, test 계정 등록 |
| [src/api/chat.py](../src/api/chat.py) | /api/projects 사용자별 필터링 |
| [src/services/database.py](../src/services/database.py) | ODBC Driver 18 + TrustServerCertificate |
| [src/services/rag.py](../src/services/rag.py) | ODBC Driver 18 + TrustServerCertificate |
| [.env](../.env) | NGROK_AUTHTOKEN, NGROK_DOMAIN 추가 |
| [start.bat](../start.bat) | 신규 - 로컬 실행 스크립트 |
| [stop.bat](../stop.bat) | 신규 - 프로세스 종료 스크립트 |

---

## Docker 상태

```
✅ hattz_web (healthy) - Flask + ngrok + Gunicorn
✅ hattz_pm_worker - GPT-5.2
✅ hattz_pm_reviewer - Claude CLI (Skeptic)
✅ hattz_coder_worker - Claude CLI (Implementer, RW)
✅ hattz_coder_reviewer - Claude CLI (Devil's Advocate, RO)
✅ hattz_qa_worker - Claude CLI (Tester, tests RW)
✅ hattz_qa_reviewer - Claude CLI (Breaker, RO)
✅ hattz_reviewer_worker - Gemini 2.5 (Pragmatist)
✅ hattz_reviewer_reviewer - Claude CLI (Security Hawk, RO)
```

---

## 접속 정보

| 타입 | URL |
|------|-----|
| Local | http://localhost:5000 |
| Public | https://caitlyn-supercivilized-intrudingly.ngrok-free.app |
| Monitor | http://localhost:5000/monitor |

### 계정
- **admin** / `admin` - 모든 프로젝트 접근 가능
- **test** / `1234` - test 프로젝트만 접근 가능

---

## Quick Commands

```bash
# Docker 상태 확인
docker ps -a

# 전체 실행
docker-compose up -d

# 전체 종료
docker-compose down

# 로그 확인
docker-compose logs -f web

# 특정 컨테이너 재시작
docker-compose restart web
```

---

## Docker Q&A (v2.2.2 이후)

### Q1: Volume Mount 원리
**Q**: 도커에서 코드수정하면 로컬 파일이 수정되는 원리?

**A**: `docker-compose.yml`의 volumes 설정으로 로컬 폴더와 컨테이너 폴더가 **실시간 동기화**됨
```yaml
volumes:
  - ./:/app:rw  # 로컬 현재폴더 ↔ 컨테이너 /app 연결
```
- `coder-worker`만 전체 RW (코드 수정 가능)
- `qa-worker`는 tests/만 RW
- 나머지는 RO (읽기 전용)

### Q2: 세션 이어가기 방식
**Q**: 컨테이너 꺼지거나 세션 닫혔을 때 이어가기?

**A**: **세션 이어가기 X → TaskSpec 패킷 주입**
- 이유: 컨텍스트 오염 방지, 토큰 절약
- 방식: Jobs API로 `context` 필드에 필요한 정보만 전달
- 전체 히스토리는 JSONL에 저장 (`parent_id`로 연결)

### Q3: 대화 이어가기 프롬프트
**Q**: 대화 이어가려면 어떤 프롬프트?

**A**: `POST /api/jobs/create`의 `context` 필드에 이전 세션 요약 포함
```json
{
  "content": "새 요청",
  "context": "이전 세션 요약: Flask-Login 구현 완료, test 계정 추가됨..."
}
```

---

## v2.2.3 Session: JSON Output Upgrade (2026-01-06 12:30 KST)

### 핵심 변경: Subagent JSON-Only 출력

**배경**: CEO 기술 가이드라인 제공 → 모든 Subagent를 JSON-only 출력으로 표준화

**장점**:
1. **결정론적 파싱** - 텍스트 기반 APPROVE/REJECT 감지의 불확실성 제거
2. **자동화 용이** - 파이프라인에서 verdict 자동 추출 가능
3. **에러 감소** - 휴먼 에러 및 포맷 불일치 방지

### 업그레이드된 파일 (6개)

| 파일 | 역할 | 출력 포맷 |
|------|------|----------|
| [pm-reviewer.md](../.claude/agents/pm-reviewer.md) | 계획 검열관 | `verdict: APPROVE/REJECT` |
| [coder-worker.md](../.claude/agents/coder-worker.md) | 구현 담당 | `status: DONE/NEED_INFO` |
| [coder-reviewer.md](../.claude/agents/coder-reviewer.md) | 코드 리뷰어 | `verdict: APPROVE/REJECT` |
| [qa-worker.md](../.claude/agents/qa-worker.md) | 테스트 작성 | `status: DONE/NEED_INFO` |
| [qa-reviewer.md](../.claude/agents/qa-reviewer.md) | 테스트 검수 | `verdict: APPROVE/REJECT` |
| [security-hawk.md](../.claude/agents/security-hawk.md) | 배포 판결 | `decision: SHIP/HOLD` |

### extract_verdict() 파서 업그레이드

**파일**: [src/workers/agent_worker.py](../src/workers/agent_worker.py):205-253

**변경 내용**:
```python
def extract_verdict(output: str) -> Optional[str]:
    """
    LLM 응답에서 JSON 블록을 찾아 파싱하고 verdict/decision 추출
    JSON 파싱 실패 시 텍스트 기반 fallback
    """
    # 1. JSON 블록 찾기 (```json ... ``` 또는 순수 JSON)
    json_patterns = [
        r'```json\s*(\{.*?\})\s*```',  # markdown code block
        r'(\{[^{}]*"(?:verdict|decision|status)"[^{}]*\})',  # inline JSON
    ]

    # 2. JSON 파싱 시도
    for pattern in json_patterns:
        match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
        if match:
            data = json.loads(match.group(1))
            verdict = data.get("verdict") or data.get("decision") or data.get("status")
            # 정규화: SHIP/DONE → APPROVE, HOLD/NEED_INFO → REVISE

    # 3. Fallback: 텍스트 기반 (레거시 지원)
```

### JSON 출력 포맷 예시

**Coder-Reviewer**:
```json
{
  "verdict": "APPROVE" | "REJECT",
  "blocking_issues": ["REJECT 사유 1", "REJECT 사유 2"],
  "non_blocking": ["개선 권장 사항"],
  "suggested_fixes": ["구체적 수정 지시 3개 이내"]
}
```

**Security-Hawk**:
```json
{
  "decision": "SHIP" | "HOLD",
  "blocking_risks": ["HOLD인 경우 사유"],
  "mitigations": ["위험 완화 방안"],
  "ops_notes": ["모니터링/롤백 포인트 3개 이내"]
}
```

### Verdict 정규화 규칙

| 원본 | 정규화 결과 |
|------|------------|
| APPROVE, SHIP, DONE | → APPROVE |
| REJECT, REVISE, HOLD, NEED_INFO | → REVISE |

---

## 다음 세션에서 이어갈 내용

1. **Claude CLI 인증**
   - 각 Claude 컨테이너에서 `claude login` 실행 필요
   - 또는 `claude_state` 볼륨에 인증 정보 미리 설정

2. **전체 파이프라인 E2E 테스트**
   - PM → CODER → QA → REVIEWER 전체 흐름 테스트
   - REVISE 시나리오 테스트 (2회 초과 시 CEO 개입)
   - SHIP 시나리오 테스트
   - **JSON 출력 파싱 검증** (새 항목)

3. **Monitor 대시보드 검증**
   - Docker 탭에서 컨테이너 상태 확인
   - Pipeline 탭에서 작업 흐름 확인

---

*Last Updated: 2026-01-06 12:40 KST*
