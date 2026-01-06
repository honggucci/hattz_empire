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

## 다음 세션에서 이어갈 내용

1. **Claude CLI 인증**
   - 각 Claude 컨테이너에서 `claude login` 실행 필요
   - 또는 `claude_state` 볼륨에 인증 정보 미리 설정

2. **전체 파이프라인 E2E 테스트**
   - PM → CODER → QA → REVIEWER 전체 흐름 테스트
   - REVISE 시나리오 테스트 (2회 초과 시 CEO 개입)
   - SHIP 시나리오 테스트

3. **Monitor 대시보드 검증**
   - Docker 탭에서 컨테이너 상태 확인
   - Pipeline 탭에서 작업 흐름 확인

---

*Last Updated: 2026-01-06 10:25 KST*
