# Hattz Empire - AI Orchestration System

## 프로젝트 개요
비용 최적화 AI 팀 오케스트레이션 시스템. 비용 86% 절감 + 품질 유지.

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

## 최근 작업 내역 (2026-01-04)

### 세션 5 (최신)
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

## 개발 시 참고사항
- Flask 서버: `python app.py` (포트 5000)
- ngrok 터널: `ngrok http 5000`
- 로그인: admin/admin

## CEO 프로필
- ID: 하홍구 (Hattz)
- 특성: 의식의 흐름 입력, 완벽주의 트랩
- AI 대응: 말 안 한 것까지 추론, MVP로 유도
