"""
Hattz Empire - RAG (Retrieval-Augmented Generation) Module
로그, 세션, 코드베이스를 벡터 검색하여 컨텍스트 제공
"""
import os
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

# OpenAI Embeddings
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Google Gemini (for summarization)
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

load_dotenv()


# =============================================================================
# Gemini Summarizer
# =============================================================================

def summarize_with_gemini(query: str, documents: List[str], language: str = "ko", session_id: str = None) -> str:
    """
    Gemini를 사용해 검색된 문서들을 쿼리 관점에서 요약

    Args:
        query: 사용자 질문
        documents: 검색된 문서 내용들
        language: 출력 언어 ('ko' 또는 'en')
        session_id: 세션 ID (로깅용)

    Returns:
        요약된 컨텍스트
    """
    import time
    start_time = time.time()

    if not GEMINI_AVAILABLE:
        # Gemini 없으면 그냥 문서 합치기
        return "\n\n".join(documents)

    if not documents:
        return ""

    # 입력 크기 계산
    combined_input = query + "\n".join(documents)
    input_chars = len(combined_input)

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        # 문서들 합치기
        combined_docs = "\n\n---\n\n".join(documents)

        lang_instruction = "한국어로" if language == "ko" else "in English"

        prompt = f"""다음은 사용자 질문과 관련된 과거 대화/로그 기록입니다.

## 사용자 질문
{query}

## 관련 문서들
{combined_docs}

## 요청
위 문서들에서 사용자 질문에 답하는 데 필요한 핵심 정보만 {lang_instruction} 추출하세요.

포함해야 할 것:
1. 관련된 과거 결정/작업 내용
2. 이전에 발생한 문제와 해결 방법
3. 아직 완료되지 않은 작업
4. 주의해야 할 교훈(lessons learned)

불필요한 것 제외:
- 질문과 무관한 내용
- 중복 정보
- 일반적인 설명

간결하게 bullet point로 정리하세요."""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        output_text = response.text.strip()

        # 로그 기록 (agent_logs에 Gemini 요약 기록)
        latency_ms = int((time.time() - start_time) * 1000)
        _log_gemini_rag_summarization(
            session_id=session_id,
            query=query,
            doc_count=len(documents),
            input_chars=input_chars,
            output_chars=len(output_text),
            latency_ms=latency_ms
        )

        return output_text

    except Exception as e:
        print(f"[RAG] Gemini summarization failed: {e}")
        # 실패시 원본 문서 앞부분만 반환
        return "\n\n".join(doc[:500] for doc in documents[:3])


def _log_gemini_rag_summarization(
    session_id: str,
    query: str,
    doc_count: int,
    input_chars: int,
    output_chars: int,
    latency_ms: int
):
    """Gemini RAG 요약 호출을 agent_logs DB에 기록"""
    try:
        from .agent_scorecard import get_scorecard

        scorecard = get_scorecard()
        if not scorecard._initialized:
            print("[RAG] Scorecard not initialized, skipping log")
            return

        # 토큰 추정 (한글 1자 ≈ 2토큰, 영문 4자 ≈ 1토큰)
        input_tokens = input_chars // 3
        output_tokens = output_chars // 3

        task_summary = f"RAG 요약: {query[:50]}... ({doc_count}문서)"[:200]

        log_id = scorecard.log_task(
            session_id=session_id or "system",
            task_id=f"gemini_rag_{latency_ms}",
            role="summarizer",
            engine="gemini",
            model="gemini-2.0-flash",
            task_type="rag_summarize",
            task_summary=task_summary,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms
        )
        print(f"[RAG] Gemini summarization logged: {log_id}")
    except Exception as e:
        print(f"[RAG] Failed to log Gemini call: {e}")


# =============================================================================
# Configuration
# =============================================================================

EMBEDDING_MODEL = "text-embedding-3-small"  # OpenAI embedding model
EMBEDDING_DIM = 1536  # text-embedding-3-small dimension
CHUNK_SIZE = 500  # 청크 크기 (토큰 기준 대략)
CHUNK_OVERLAP = 50  # 청크 오버랩


@dataclass
class Document:
    """검색 가능한 문서"""
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    score: float = 0.0


@dataclass
class SearchResult:
    """검색 결과"""
    documents: List[Document]
    query: str
    total: int


# =============================================================================
# Database Connection
# =============================================================================

def get_connection():
    """MSSQL 연결"""
    driver = os.getenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={os.getenv('MSSQL_SERVER')};"
        f"DATABASE={os.getenv('MSSQL_DATABASE')};"
        f"UID={os.getenv('MSSQL_USER')};"
        f"PWD={os.getenv('MSSQL_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def init_vector_table():
    """벡터 저장 테이블 생성"""
    conn = get_connection()
    cursor = conn.cursor()

    # embeddings 테이블
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'embeddings')
        CREATE TABLE embeddings (
            id NVARCHAR(100) PRIMARY KEY,
            project NVARCHAR(100),  -- 프로젝트 ID (프로젝트별 분리 검색용)
            source NVARCHAR(50) DEFAULT 'web',  -- 'web', 'claude_code' (출처 구분)
            source_type NVARCHAR(50),  -- 'log', 'session', 'code', 'message'
            source_id NVARCHAR(100),
            content NVARCHAR(MAX),
            content_hash NVARCHAR(64),
            embedding NVARCHAR(MAX),  -- JSON array of floats
            metadata NVARCHAR(MAX),  -- JSON
            created_at DATETIME2 DEFAULT GETDATE(),
            updated_at DATETIME2 DEFAULT GETDATE()
        )
    """)

    # 인덱스
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_embeddings_source')
        CREATE INDEX IX_embeddings_source ON embeddings(source_type, source_id)
    """)

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_embeddings_hash')
        CREATE INDEX IX_embeddings_hash ON embeddings(content_hash)
    """)

    # 프로젝트별 검색용 인덱스
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_embeddings_project')
        CREATE INDEX IX_embeddings_project ON embeddings(project, source_type)
    """)

    conn.commit()
    conn.close()


def run_embeddings_migration() -> Dict[str, Any]:
    """기존 embeddings 테이블에 project, source 컬럼 추가 마이그레이션"""
    results = {"added_columns": [], "errors": []}

    conn = get_connection()
    cursor = conn.cursor()

    # project 컬럼 확인 및 추가
    cursor.execute("""
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('embeddings')
        AND name = 'project'
    """)
    if not cursor.fetchone():
        try:
            cursor.execute("ALTER TABLE embeddings ADD project NVARCHAR(100)")
            conn.commit()
            results["added_columns"].append("project")
        except Exception as e:
            results["errors"].append(f"project: {str(e)}")

    # source 컬럼 확인 및 추가
    cursor.execute("""
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('embeddings')
        AND name = 'source'
    """)
    if not cursor.fetchone():
        try:
            cursor.execute("ALTER TABLE embeddings ADD source NVARCHAR(50) DEFAULT 'web'")
            conn.commit()
            results["added_columns"].append("source")
        except Exception as e:
            results["errors"].append(f"source: {str(e)}")

    # 프로젝트 인덱스 추가
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_embeddings_project')
        CREATE INDEX IX_embeddings_project ON embeddings(project, source_type)
    """)
    conn.commit()

    conn.close()
    results["success"] = len(results["errors"]) == 0
    return results


def backfill_embeddings_null_values(default_project: str = "hattz_empire") -> Dict[str, int]:
    """
    기존 embeddings 테이블의 NULL 값을 채우기

    Args:
        default_project: project가 NULL인 레코드에 설정할 기본값

    Returns:
        업데이트된 레코드 수
    """
    conn = get_connection()
    cursor = conn.cursor()

    results = {"project_updated": 0, "source_updated": 0}

    # project가 NULL인 레코드 업데이트
    cursor.execute("""
        UPDATE embeddings
        SET project = ?
        WHERE project IS NULL
    """, (default_project,))
    results["project_updated"] = cursor.rowcount

    # source가 NULL인 레코드 업데이트
    cursor.execute("""
        UPDATE embeddings
        SET source = 'web'
        WHERE source IS NULL
    """)
    results["source_updated"] = cursor.rowcount

    conn.commit()
    conn.close()

    return results


# =============================================================================
# Embedding Functions
# =============================================================================

def get_embedding(text: str) -> List[float]:
    """OpenAI 임베딩 생성"""
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OpenAI package not installed")

    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # 텍스트 정리
    text = text.replace("\n", " ").strip()
    if not text:
        return [0.0] * EMBEDDING_DIM

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )

    return response.data[0].embedding


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """배치 임베딩 생성"""
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OpenAI package not installed")

    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # 텍스트 정리
    cleaned = [t.replace("\n", " ").strip() for t in texts]
    cleaned = [t if t else " " for t in cleaned]  # 빈 문자열 방지

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=cleaned
    )

    return [d.embedding for d in response.data]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """코사인 유사도 계산"""
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


# =============================================================================
# Document Indexing
# =============================================================================

def content_hash(content: str) -> str:
    """콘텐츠 해시 생성"""
    return hashlib.sha256(content.encode()).hexdigest()[:64]


def index_document(
    source_type: str,
    source_id: str,
    content: str,
    metadata: Dict[str, Any] = None,
    project: Optional[str] = None,
    source: str = "web",
    agent: Optional[str] = None
) -> str:
    """
    문서 인덱싱 (임베딩 생성 + 저장)

    Args:
        source_type: 문서 유형 ('log', 'session', 'code', 'message', 'conversation')
        source_id: 원본 ID
        content: 인덱싱할 텍스트
        metadata: 추가 메타데이터
        project: 프로젝트 ID (프로젝트별 필터링용)
        source: 출처 ('web', 'claude_code')
        agent: 에이전트 역할 ('pm', 'coder', 'qa' 등) - v2.5
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 해시 체크 (이미 인덱싱된 경우 스킵)
    c_hash = content_hash(content)
    cursor.execute(
        "SELECT id FROM embeddings WHERE content_hash = ?",
        (c_hash,)
    )
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing[0]

    # 임베딩 생성
    embedding = get_embedding(content)

    # ID 생성
    doc_id = f"{source_type}_{source_id}_{c_hash[:8]}"

    # v2.5: metadata에서 agent 추출 (파라미터 우선)
    doc_agent = agent or (metadata.get("agent") if metadata else None)

    # 저장 (agent 컬럼 추가)
    cursor.execute("""
        INSERT INTO embeddings (id, project, source, source_type, source_id, content, content_hash, embedding, metadata, agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        doc_id,
        project,
        source,
        source_type,
        source_id,
        content,
        c_hash,
        json.dumps(embedding),
        json.dumps(metadata or {}),
        doc_agent
    ))

    conn.commit()
    conn.close()

    return doc_id


def index_logs_from_db(limit: int = 1000, project: str = None) -> int:
    """
    hattz_logs 테이블에서 로그 인덱싱

    Args:
        limit: 최대 인덱싱 개수
        project: 프로젝트 ID (None이면 'hattz_empire' 기본값)
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 아직 인덱싱 안 된 로그 조회
    cursor.execute("""
        SELECT l.id, l.from_agent, l.to_agent, l.msg_type, l.content_preview,
               l.content_full, l.timestamp, l.task_id
        FROM hattz_logs l
        LEFT JOIN embeddings e ON e.source_id = l.id AND e.source_type = 'log'
        WHERE e.id IS NULL
        ORDER BY l.timestamp DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, (limit,))

    logs = cursor.fetchall()
    conn.close()

    # 기본 프로젝트
    default_project = project or "hattz_empire"

    indexed = 0
    for log in logs:
        log_id, from_agent, to_agent, msg_type, preview, full_content, timestamp, task_id = log

        # 인덱싱할 콘텐츠 구성
        content = f"[{from_agent} → {to_agent}] ({msg_type})\n{full_content or preview or ''}"

        metadata = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "msg_type": msg_type,
            "timestamp": str(timestamp) if timestamp else None,
            "task_id": task_id
        }

        try:
            index_document("log", log_id, content, metadata, project=default_project, source="web")
            indexed += 1
        except Exception as e:
            print(f"Failed to index log {log_id}: {e}")

    return indexed


def index_messages_from_db(limit: int = 1000, project: str = None) -> int:
    """
    messages 테이블에서 메시지 인덱싱

    Args:
        limit: 최대 인덱싱 개수
        project: 프로젝트 ID (세션에서 추출 시도, 없으면 기본값)
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 아직 인덱싱 안 된 메시지 조회 (세션의 프로젝트 정보도 함께)
    cursor.execute("""
        SELECT m.id, m.session_id, m.role, m.content, m.agent, m.timestamp, s.project
        FROM chat_messages m
        LEFT JOIN chat_sessions s ON m.session_id = s.id
        LEFT JOIN embeddings e ON e.source_id = CAST(m.id AS NVARCHAR(100)) AND e.source_type = 'message'
        WHERE e.id IS NULL AND m.content IS NOT NULL AND LEN(m.content) > 10
        ORDER BY m.timestamp DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, (limit,))

    messages = cursor.fetchall()
    conn.close()

    indexed = 0
    for msg in messages:
        msg_id, session_id, role, content, agent, created_at, session_project = msg

        # 프로젝트 결정: 파라미터 > 세션 > 기본값
        msg_project = project or session_project or "hattz_empire"

        metadata = {
            "session_id": session_id,
            "role": role,
            "agent": agent,
            "created_at": str(created_at) if created_at else None
        }

        try:
            index_document("message", str(msg_id), content, metadata, project=msg_project, source="web")
            indexed += 1
        except Exception as e:
            print(f"Failed to index message {msg_id}: {e}")

    return indexed


# =============================================================================
# Search Functions
# =============================================================================

def search(
    query: str,
    source_types: List[str] = None,
    project: Optional[str] = None,
    agent_filter: Optional[str] = None,
    top_k: int = 5,
    threshold: float = 0.3
) -> SearchResult:
    """
    벡터 검색 (v2.5: agent 필터 추가)

    Args:
        query: 검색 쿼리
        source_types: 소스 타입 필터 (['log', 'message', 'conversation'])
        project: 프로젝트 ID로 필터 (None이면 전체 검색)
        agent_filter: 에이전트 필터 ('coder', 'pm', 'qa' 등)
        top_k: 반환할 상위 결과 수
        threshold: 최소 유사도 임계값
    """
    # 쿼리 임베딩
    query_embedding = get_embedding(query)

    conn = get_connection()
    cursor = conn.cursor()

    # WHERE 조건 구성
    conditions = []
    params = []

    if source_types:
        placeholders = ",".join(["?" for _ in source_types])
        conditions.append(f"source_type IN ({placeholders})")
        params.extend(source_types)

    if project:
        conditions.append("project = ?")
        params.append(project)

    # v2.5: agent 필터 추가
    if agent_filter:
        conditions.append("agent = ?")
        params.append(agent_filter)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    cursor.execute(f"""
        SELECT id, source_type, source_id, content, embedding, metadata, project, agent
        FROM embeddings
        {where_clause}
    """, params)

    rows = cursor.fetchall()
    conn.close()

    # 유사도 계산
    results = []
    for row in rows:
        doc_id, source_type, source_id, content, embedding_json, metadata_json, doc_project, doc_agent = row

        try:
            embedding = json.loads(embedding_json)
            metadata = json.loads(metadata_json) if metadata_json else {}
        except:
            continue

        score = cosine_similarity(query_embedding, embedding)

        if score >= threshold:
            results.append(Document(
                id=doc_id,
                content=content,
                metadata={
                    **metadata,
                    "source_type": source_type,
                    "source_id": source_id,
                    "project": doc_project,
                    "agent": doc_agent  # v2.5: agent 추가
                },
                embedding=None,
                score=score
            ))

    # 정렬 및 top_k
    results.sort(key=lambda x: x.score, reverse=True)
    results = results[:top_k]

    return SearchResult(
        documents=results,
        query=query,
        total=len(results)
    )


def search_logs(query: str, project: Optional[str] = None, top_k: int = 5) -> SearchResult:
    """로그 검색"""
    return search(query, source_types=["log"], project=project, top_k=top_k)


def search_messages(query: str, project: Optional[str] = None, top_k: int = 5) -> SearchResult:
    """메시지 검색"""
    return search(query, source_types=["message"], project=project, top_k=top_k)


def search_all(query: str, project: Optional[str] = None, top_k: int = 5) -> SearchResult:
    """전체 검색 (project가 지정되면 해당 프로젝트만)"""
    return search(query, source_types=None, project=project, top_k=top_k)


def search_by_agent(query: str, agent: str, project: Optional[str] = None, top_k: int = 5) -> SearchResult:
    """v2.5: 에이전트별 검색 (coder, pm, qa 등)"""
    return search(query, source_types=None, project=project, agent_filter=agent, top_k=top_k)


# =============================================================================
# Context Building
# =============================================================================

def build_context(
    query: str,
    project: Optional[str] = None,
    agent_filter: Optional[str] = None,
    top_k: int = 3,
    use_gemini: bool = True,
    language: str = "ko",
    session_id: Optional[str] = None
) -> str:
    """
    쿼리 관련 컨텍스트 구성 (에이전트 시스템 프롬프트에 주입용)
    conversation 타입이면 DB에서 상세 정보를 가져와 풍부한 컨텍스트 제공
    Gemini 요약 활성화 시, 검색된 문서들을 쿼리 관점에서 요약

    Args:
        query: 검색 쿼리
        project: 프로젝트 ID (특정 프로젝트만 검색)
        agent_filter: 에이전트 필터 ('coder', 'pm', 'qa' 등) - v2.5
        top_k: 반환할 문서 수
        use_gemini: Gemini 요약 사용 여부 (기본 True)
        language: 출력 언어 ('ko' 또는 'en')
        session_id: 세션 ID (로깅용) - v2.5
    """
    result = search(query, project=project, agent_filter=agent_filter, top_k=top_k)

    if not result.documents:
        return ""

    # 문서 컨텍스트 수집
    doc_contents = []
    context_parts = ["## Related Context (from RAG)"]

    for i, doc in enumerate(result.documents, 1):
        source_type = doc.metadata.get("source_type", "unknown")
        score = f"{doc.score:.2f}"

        # conversation 타입이면 DB에서 상세 정보 조회
        if source_type == "conversation":
            conv_context = _build_conversation_context(doc, i, score)
            context_parts.append(conv_context)
            doc_contents.append(conv_context)
        else:
            # 일반 문서 (log 등)
            content = doc.content[:500]
            if len(doc.content) > 500:
                content += "..."
            doc_text = f"""
### [{i}] {source_type.upper()} (relevance: {score})
{content}
"""
            context_parts.append(doc_text)
            doc_contents.append(doc_text)

    # Gemini 요약 사용
    if use_gemini and GEMINI_AVAILABLE and doc_contents:
        summarized = summarize_with_gemini(query, doc_contents, language, session_id=session_id)
        if summarized:
            return f"""## Related Context (RAG + Gemini Summary)

{summarized}

---
_Based on {len(doc_contents)} documents (similarity: {result.documents[0].score:.2f} - {result.documents[-1].score:.2f})_
"""

    # Gemini 미사용 또는 실패 시 원본 반환
    return "\n".join(context_parts)


def _build_conversation_context(doc: Document, index: int, score: str) -> str:
    """conversation 문서의 상세 컨텍스트 구성"""
    session_id = doc.metadata.get("source_id") or doc.metadata.get("session_id")
    title = doc.metadata.get("title", "")

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT summary, tags, files_changed, content_json
            FROM conversations WHERE session_id = ?
        """, (session_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return f"\n### [{index}] CONVERSATION (relevance: {score})\n{title}\n{doc.content[:300]}"

        summary, tags_json, files_json, content_json = row
        parts = [f"\n### [{index}] CONVERSATION (relevance: {score})"]
        parts.append(f"**Session:** {session_id}")
        if title:
            parts.append(f"**Title:** {title}")
        if summary:
            parts.append(f"**Summary:** {summary[:300]}")

        # 변경된 파일
        try:
            files = json.loads(files_json) if files_json else []
            if files:
                parts.append(f"**Files Changed:** {', '.join(str(f) for f in files[:5])}")
        except:
            pass

        # content_json에서 핵심 정보 추출
        try:
            data = json.loads(content_json) if content_json else {}

            # lessons_learned
            if 'lessons_learned' in data and isinstance(data['lessons_learned'], list):
                parts.append("**Lessons Learned:**")
                for lesson in data['lessons_learned'][:3]:
                    parts.append(f"  - {str(lesson)[:100]}")

            # critical fix
            if 'changes' in data and isinstance(data['changes'], dict):
                for file_info in data['changes'].get('files_modified', [])[:2]:
                    if isinstance(file_info, dict) and file_info.get('critical_fix'):
                        parts.append(f"**Critical Fix:** {file_info.get('bug_description', '')[:150]}")

            # remaining_tasks
            if 'remaining_tasks' in data and isinstance(data['remaining_tasks'], list):
                parts.append("**Pending Tasks:**")
                for task in data['remaining_tasks'][:2]:
                    task_text = task.get('task', str(task)) if isinstance(task, dict) else str(task)
                    parts.append(f"  - {task_text[:80]}")

            # verification
            if 'verification' in data:
                parts.append("**Verified:** Yes")
        except:
            pass

        return "\n".join(parts)

    except Exception:
        return f"\n### [{index}] CONVERSATION (relevance: {score})\n{title}\n{doc.content[:300]}"


# =============================================================================
# Stats & Management
# =============================================================================

def get_stats(project: Optional[str] = None) -> Dict[str, Any]:
    """
    RAG 인덱스 통계

    Args:
        project: 특정 프로젝트 통계만 (None이면 전체)
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 프로젝트 필터
    if project:
        cursor.execute("""
            SELECT source_type, COUNT(*) as count
            FROM embeddings
            WHERE project = ?
            GROUP BY source_type
        """, (project,))
    else:
        cursor.execute("""
            SELECT source_type, COUNT(*) as count
            FROM embeddings
            GROUP BY source_type
        """)

    by_type = {row[0]: row[1] for row in cursor.fetchall()}

    if project:
        cursor.execute("SELECT COUNT(*) FROM embeddings WHERE project = ?", (project,))
    else:
        cursor.execute("SELECT COUNT(*) FROM embeddings")
    total = cursor.fetchone()[0]

    # 프로젝트별 카운트
    cursor.execute("""
        SELECT project, COUNT(*) as count
        FROM embeddings
        GROUP BY project
    """)
    by_project = {row[0] or "(none)": row[1] for row in cursor.fetchall()}

    conn.close()

    return {
        "total_documents": total,
        "by_type": by_type,
        "by_project": by_project,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM
    }


def clear_index(source_type: str = None) -> int:
    """인덱스 삭제"""
    conn = get_connection()
    cursor = conn.cursor()

    if source_type:
        cursor.execute("DELETE FROM embeddings WHERE source_type = ?", (source_type,))
    else:
        cursor.execute("DELETE FROM embeddings")

    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted


# =============================================================================
# Conversations Import
# =============================================================================

def init_conversations_table():
    """conversations 테이블 생성"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'conversations')
        CREATE TABLE conversations (
            id INT IDENTITY(1,1) PRIMARY KEY,
            session_id NVARCHAR(200) UNIQUE,
            project NVARCHAR(100),
            date_path NVARCHAR(50),
            title NVARCHAR(500),
            summary NVARCHAR(MAX),
            tags NVARCHAR(MAX),
            files_changed NVARCHAR(MAX),
            content_json NVARCHAR(MAX),
            created_at DATETIME2 DEFAULT GETDATE()
        )
    """)

    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_conversations_project')
        CREATE INDEX IX_conversations_project ON conversations(project, date_path)
    """)

    conn.commit()
    conn.close()


def import_conversation_file(file_path: str, project: str = "wpcn") -> Optional[str]:
    """단일 conversation JSON 파일 임포트"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 세션 ID 추출 (파일에서 또는 파일명에서)
        session_id = data.get('session_id') or data.get('id') or Path(file_path).stem

        # 이미 존재하는지 체크
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE session_id = ?", (session_id,))
        if cursor.fetchone():
            conn.close()
            return None  # 이미 존재

        # 메타데이터 추출
        title = data.get('title', '')

        # summary 처리 (dict 또는 string)
        summary_data = data.get('summary', '')
        if isinstance(summary_data, dict):
            summary = summary_data.get('description', '') or json.dumps(summary_data, ensure_ascii=False)
        else:
            summary = str(summary_data)

        tags = json.dumps(data.get('tags', []), ensure_ascii=False)

        # files_changed 추출
        changes = data.get('changes', {})
        files_changed = changes.get('files_modified', []) if isinstance(changes, dict) else []
        if isinstance(files_changed, list) and files_changed:
            files_changed = [f.get('path', f) if isinstance(f, dict) else f for f in files_changed]
        files_changed_json = json.dumps(files_changed, ensure_ascii=False)

        # date_path 추출 (파일 경로에서)
        path_parts = Path(file_path).parts
        date_path = ""
        for i, part in enumerate(path_parts):
            if part == "daily" and i + 3 < len(path_parts):
                date_path = f"{path_parts[i+1]}/{path_parts[i+2]}/{path_parts[i+3]}"
                break

        # 저장
        cursor.execute("""
            INSERT INTO conversations
            (session_id, project, date_path, title, summary, tags, files_changed, content_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            project,
            date_path,
            title,
            summary,
            tags,
            files_changed_json,
            json.dumps(data, ensure_ascii=False)
        ))

        conn.commit()
        conn.close()

        return session_id
    except Exception as e:
        print(f"Failed to import {file_path}: {e}")
        return None


def import_conversations_from_folder(folder_path: str, project: str = "wpcn") -> int:
    """폴더에서 모든 conversation JSON 파일 임포트"""
    init_conversations_table()

    imported = 0
    folder = Path(folder_path)

    for json_file in folder.rglob("*.json"):
        # index.json, README.json 등 제외
        if json_file.name in ['index.json', 'README.json', 'BACKUP_GUIDE.json',
                               'EXECUTION_GUIDE.json', 'PROJECT_STRUCTURE.json']:
            continue

        result = import_conversation_file(str(json_file), project)
        if result:
            imported += 1
            print(f"  Imported: {result}")

    return imported


def index_conversations_for_rag(limit: int = 100) -> int:
    """conversations 테이블에서 RAG 인덱싱"""
    conn = get_connection()
    cursor = conn.cursor()

    # 아직 인덱싱 안 된 conversation 조회
    cursor.execute("""
        SELECT c.id, c.session_id, c.project, c.title, c.summary, c.tags, c.content_json
        FROM conversations c
        LEFT JOIN embeddings e ON e.source_id = c.session_id AND e.source_type = 'conversation'
        WHERE e.id IS NULL
        ORDER BY c.created_at DESC
        OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY
    """, (limit,))

    conversations = cursor.fetchall()
    conn.close()

    indexed = 0
    for conv in conversations:
        conv_id, session_id, project, title, summary, tags_json, content_json = conv

        # 인덱싱할 콘텐츠 구성
        content = f"[{project}] {title}\n\n{summary}"

        # content_json에서 추가 정보 추출
        try:
            data = json.loads(content_json) if content_json else {}

            # lessons_learned, key_decisions 등 추가
            if 'lessons_learned' in data:
                lessons = data['lessons_learned']
                if isinstance(lessons, list):
                    content += "\n\nLessons Learned:\n" + "\n".join(f"- {l}" for l in lessons)

            if 'remaining_tasks' in data:
                tasks = data['remaining_tasks']
                if isinstance(tasks, list):
                    task_texts = []
                    for t in tasks:
                        if isinstance(t, dict):
                            task_texts.append(t.get('task', str(t)))
                        else:
                            task_texts.append(str(t))
                    content += "\n\nRemaining Tasks:\n" + "\n".join(f"- {t}" for t in task_texts)

            if 'technical_details' in data:
                content += "\n\nTechnical Details: " + json.dumps(data['technical_details'], ensure_ascii=False)[:500]
        except:
            pass

        metadata = {
            "session_id": session_id,
            "project": project,
            "title": title,
            "tags": tags_json
        }

        try:
            index_document("conversation", session_id, content, metadata, project=project, source="claude_code")
            indexed += 1
        except Exception as e:
            print(f"Failed to index conversation {session_id}: {e}")

    return indexed


# =============================================================================
# Translation Layer (Agent Communication)
# =============================================================================

def translate_message(
    text: str,
    target_lang: str = "en",
    source_lang: str = "auto"
) -> str:
    """
    Gemini를 사용한 에이전트 간 메시지 번역

    Args:
        text: 번역할 텍스트
        target_lang: 목표 언어 ('en', 'ko')
        source_lang: 원본 언어 ('auto', 'en', 'ko')

    Returns:
        번역된 텍스트 (실패 시 원본 반환)
    """
    if not GEMINI_AVAILABLE:
        return text

    if not text or len(text.strip()) < 5:
        return text

    try:
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        lang_map = {"en": "English", "ko": "Korean"}
        target = lang_map.get(target_lang, "English")

        prompt = f"""Translate the following text to {target}.

RULES:
1. Keep code blocks, YAML, JSON exactly as-is (do not translate code)
2. Keep technical terms in English even in Korean output
3. Keep markdown formatting intact
4. If text is already in {target}, return it unchanged
5. Return ONLY the translated text, no explanations

TEXT:
{text}"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        return response.text.strip()

    except Exception as e:
        print(f"[Translate] Failed: {e}")
        return text


def translate_for_agent(text: str) -> str:
    """
    에이전트 간 통신용 번역 (한국어 → 영어)
    내부 에이전트끼리는 영어로 통신
    """
    return translate_message(text, target_lang="en")


def translate_for_ceo(text: str) -> str:
    """
    CEO 출력용 번역 (영어 → 한국어)
    CEO에게 보여주는 최종 결과는 한국어
    """
    return translate_message(text, target_lang="ko")


def is_korean(text: str) -> bool:
    """텍스트가 한국어인지 확인"""
    if not text:
        return False
    # 한글 유니코드 범위 체크
    korean_count = sum(1 for c in text if '\uAC00' <= c <= '\uD7A3' or '\u3130' <= c <= '\u318F')
    return korean_count > len(text) * 0.1  # 10% 이상이 한글이면 한국어


# =============================================================================
# Initialize
# =============================================================================

def init():
    """RAG 시스템 초기화"""
    init_vector_table()
    init_conversations_table()
    print("[RAG] Vector tables initialized")


if __name__ == "__main__":
    init()
    print("\n[RAG] Indexing logs...")
    log_count = index_logs_from_db(limit=100)
    print(f"[RAG] Indexed {log_count} logs")

    print("\n[RAG] Indexing messages...")
    msg_count = index_messages_from_db(limit=100)
    print(f"[RAG] Indexed {msg_count} messages")

    print("\n[RAG] Stats:")
    print(get_stats())
