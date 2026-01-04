"""
Hattz Empire - Flask Web Interface
Blueprint 기반 모듈화 구조

폴더 구조:
├── app.py                 # Entry point (이 파일)
├── config.py              # 설정
├── src/
│   ├── api/               # Blueprint routes
│   │   ├── auth.py        # 로그인/로그아웃
│   │   ├── chat.py        # 채팅 API
│   │   ├── sessions.py    # 세션 관리
│   │   ├── execute.py     # 파일/명령 실행
│   │   ├── rag_api.py     # RAG 검색
│   │   ├── scores.py      # 스코어카드
│   │   ├── router_api.py  # 라우터 분석
│   │   ├── tasks.py       # 백그라운드 작업
│   │   ├── breaker.py     # Circuit Breaker
│   │   ├── council_api.py # 위원회
│   │   └── health.py      # Health Check
│   ├── core/              # 비즈니스 로직
│   │   ├── llm_caller.py  # LLM 호출
│   │   ├── router.py      # 라우팅
│   │   └── session_state.py # 세션 상태
│   ├── services/          # 서비스 레이어
│   │   ├── database.py
│   │   ├── rag.py
│   │   ├── executor.py
│   │   ├── agent_scorecard.py
│   │   └── background_tasks.py
│   ├── infra/             # 인프라
│   │   ├── circuit_breaker.py
│   │   ├── council.py
│   │   └── stream.py
│   └── utils/             # 유틸리티
│       ├── auth.py
│       └── context_loader.py
"""
from flask import Flask
import os
from pathlib import Path
from dotenv import load_dotenv

# .env를 가장 먼저 로드
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path, override=True)

# Flask 앱 생성
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "hattz-empire-secret-key-2024")

# Flask-Login 초기화
from src.utils.auth import init_login
init_login(app)

# Blueprint 등록
from src.api import register_blueprints
register_blueprints(app)

# 임베딩 큐 워커 초기화
from src.services.embedding_queue import init_embedding_worker, shutdown_embedding_worker
import atexit

# 앱 컨텍스트 내에서 워커 시작
with app.app_context():
    init_embedding_worker()
    print("[EmbeddingQueue] Background worker started")

# 종료 시 워커 정리
atexit.register(shutdown_embedding_worker)


if __name__ == '__main__':
    print("\n" + "="*60)
    print("HATTZ EMPIRE - Web Interface")
    print("="*60)
    print("http://localhost:5000")
    print("="*60 + "\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
