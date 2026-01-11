# Conversations - JSONL Stream Logs

Hattz Empire AI 오케스트레이션 시스템의 모든 대화를 기록하는 append-only 로그 시스템입니다.

## 폴더 구조

```
conversations/
├── stream/                 # 활성 로그 (최근 7일)
│   ├── 2026-01-07.jsonl
│   └── 2026-01-09.jsonl
├── stream/archive/         # 보관 로그 (7일 이상)
│   ├── 2026-01-03.jsonl
│   ├── 2026-01-04.jsonl
│   ├── 2026-01-05.jsonl
│   └── 2026-01-06.jsonl
└── tasks/                  # Task별 정리 (YAML)
    └── 2026-01-02_001.yaml
```

## JSONL 스키마

각 라인은 하나의 메시지를 나타내는 JSON 객체입니다.

```json
{
  "id": "msg_20260109_061700_abc123",
  "t": "2026-01-09T06:17:00.123456",
  "from_agent": "ceo",
  "to_agent": "pm",
  "type": "request",
  "content": "사용자 메시지 내용",
  "parent_id": "msg_20260109_061659_def456",
  "metadata": {}
}
```

### 필드 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | string | 고유 메시지 ID (`msg_YYYYMMDD_HHMMSS_랜덤6자`) |
| `t` | string | ISO 8601 타임스탬프 |
| `from_agent` | string | 발신자 (ceo, pm, coder, qa, reviewer 등) |
| `to_agent` | string? | 수신자 (없으면 null) |
| `type` | string | 메시지 타입 (request, response, error, decision, state) |
| `content` | any | 메시지 내용 (문자열 또는 객체) |
| `parent_id` | string? | 이전 메시지 ID (대화 체인 추적용) |
| `metadata` | object | 추가 메타데이터 |

### 메시지 타입

- `request`: 사용자 또는 에이전트 요청
- `response`: 에이전트 응답
- `error`: 에러 메시지
- `decision`: PM 의사결정 (PMDecision enum)
- `state`: 상태 변경 로그 (롤백용)

## 보관 정책

### 활성 로그 (stream/)
- **보관 기간**: 최근 7일
- **목적**: 빠른 조회 및 디버깅
- **자동 이동**: 7일 경과 시 archive/로 자동 이동 (TODO: 크론 작업)

### 아카이브 (stream/archive/)
- **보관 기간**: 무기한 (또는 30일 후 압축)
- **압축**: `.jsonl.gz` 형식으로 압축 (TODO)
- **목적**: 장기 감사 추적 및 RAG 시스템 학습

## 인코딩

모든 JSONL 파일은 **UTF-8 인코딩**을 사용합니다.

쓰기/읽기 시 반드시 `encoding='utf-8'`을 명시하세요:

```python
# 쓰기 (stream.py:141)
with open(filepath, "a", encoding="utf-8") as f:
    f.write(msg.to_json() + "\n")

# 읽기 (stream.py:216)
with open(filepath, "r", encoding="utf-8") as f:
    for line in f:
        messages.append(json.loads(line))
```

## 사용법

### 1. 메시지 로그

```python
from src.infra.stream import get_stream

stream = get_stream()

# 메시지 로그
msg_id = stream.log(
    from_agent="ceo",
    to_agent="pm",
    msg_type="request",
    content="프로젝트 상태를 알려줘",
    parent_id="msg_20260109_061659_abc123"
)
```

### 2. 오늘 로그 읽기

```python
today_logs = stream.read_today()
print(f"Today: {len(today_logs)} messages")
```

### 3. 특정 날짜 로그 읽기

```python
logs = stream.read_date("2026-01-07")
```

### 4. 대화 체인 추적

```python
# parent_id를 따라가며 전체 대화 체인 조회
chain = stream.get_chain("msg_20260109_061700_abc123")

for msg in chain:
    print(f"{msg['from_agent']} → {msg['to_agent']}: {msg['content'][:50]}")
```

## RAG 시스템 연동

모든 메시지는 자동으로 RAG 시스템에 임베딩되어 향후 검색 가능합니다.

- **임베딩 큐**: `src/services/embedding_queue.py`
- **임베딩 모델**: Gemini Embedding 004
- **저장소**: SQLite `hattz_empire.db` - `embeddings` 테이블
- **검색**: `src/services/rag.py` - `search_by_agent()`

## 주의 사항

### Append-Only 원칙
- **절대 수정/삭제 금지**: 로그는 감사 추적용이므로 수정하지 않습니다.
- **테스트 데이터**: 테스트는 별도 환경에서 수행하고, production 로그에 남기지 않습니다.

### 스레드 안전성
- `StreamLogger`는 `threading.Lock`을 사용하여 스레드 안전합니다.
- 동시에 여러 에이전트가 로그를 작성해도 안전합니다.

### 대용량 파일 처리
- 하루에 1.5MB 이상 로그가 쌓일 경우, 세션 단위로 분할 고려
- 예: `2026-01-04_session1.jsonl`, `2026-01-04_session2.jsonl`

## 문제 해결

### Q: 한글이 깨져서 저장됩니다.
A: `stream.py`에서 이미 `encoding='utf-8'`을 사용하고 있습니다. 읽을 때 인코딩을 확인하세요.

### Q: 파일이 너무 큽니다.
A: `stream/archive/`로 이동하고, gzip으로 압축하세요:
```bash
gzip 2026-01-04.jsonl  # → 2026-01-04.jsonl.gz
```

### Q: 특정 메시지를 삭제하고 싶습니다.
A: Append-only 원칙상 삭제 불가능합니다. 필요 시 archive로 이동하거나, 민감 정보는 처음부터 로그에 남기지 마세요.

## 관련 파일

- **구현**: [src/infra/stream.py](../stream.py)
- **임베딩 큐**: [src/services/embedding_queue.py](../../services/embedding_queue.py)
- **RAG 시스템**: [src/services/rag.py](../../services/rag.py)
- **DB 스키마**: [src/services/database.py](../../services/database.py)

## 버전 히스토리

- **v2.6.4** (2026-01-09): archive/ 폴더 구조 추가, README 작성
- **v2.2.1** (2026-01-06): JSONL 영속화 구현, parent_id 체인 추적
- **v2.0** (2026-01-03): StreamLogger 최초 구현
