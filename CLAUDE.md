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
│   │   └── council_api.py # 위원회
│   ├── core/              # 비즈니스 로직
│   │   ├── llm_caller.py  # LLM 호출
│   │   └── router.py      # 라우팅
│   ├── services/          # 서비스 레이어
│   │   ├── database.py
│   │   └── background_tasks.py
│   └── infra/             # 인프라
│       ├── circuit_breaker.py
│       └── council.py
├── static/
│   ├── js/chat.js         # 클라이언트 로직
│   └── css/style.css
└── templates/chat.html
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

## 최근 작업 내역 (2026-01-04)
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
