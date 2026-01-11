"""
세션 백업 파일을 분할해서 RAG 임베딩

사용법:
    python scripts/embed_session_backup.py <backup_file_path>
"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.rag import index_document


def split_content_by_tokens(content: str, max_tokens: int = 6000) -> list[str]:
    """
    컨텐츠를 토큰 제한에 맞게 분할
    간단한 휴리스틱: 1 토큰 ≈ 4 chars (영어 기준), 한글은 ≈ 2 chars
    """
    max_chars = max_tokens * 2  # 보수적으로 추정
    chunks = []

    # "## [" 패턴으로 메시지 단위 분할
    lines = content.split('\n')
    current_chunk = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1  # +1 for newline

        # 새 메시지 시작 && 현재 청크가 max를 넘으면 저장
        if line.startswith("## [") and current_size + line_size > max_chars:
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_size = 0

        current_chunk.append(line)
        current_size += line_size

    # 마지막 청크
    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    return chunks


def embed_backup_file(backup_path: str):
    """백업 파일을 분할해서 RAG 임베딩"""
    backup_file = Path(backup_path)

    if not backup_file.exists():
        raise ValueError(f"파일이 존재하지 않습니다: {backup_path}")

    print(f"[INFO] Backup file: {backup_file.name}")

    # 파일 읽기
    with open(backup_file, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"[INFO] File size: {len(content):,} bytes")

    # 메타데이터 추출 (파일명에서)
    # session_backup_20260107_628DFF71-1FFB-497A-ADB7-6601D4C67EDA.md
    filename = backup_file.stem
    parts = filename.split('_')
    if len(parts) >= 3:
        date_str = parts[2]  # 20260107
        session_id = '_'.join(parts[3:])  # 628DFF71-1FFB-497A-ADB7-6601D4C67EDA
    else:
        date_str = "unknown"
        session_id = filename

    # 분할 (보수적으로 4000 토큰)
    chunks = split_content_by_tokens(content, max_tokens=4000)
    print(f"[INFO] Split into {len(chunks)} chunks")

    # 임베딩
    doc_ids = []
    for i, chunk in enumerate(chunks, 1):
        print(f"\n[RAG] Embedding chunk {i}/{len(chunks)} ({len(chunk):,} bytes)...")

        try:
            doc_id = index_document(
                source_type="session_backup_chunk",
                source_id=f"{session_id}_chunk_{i}",
                content=chunk,
                metadata={
                    "session_id": session_id,
                    "project": "hattz_empire",
                    "backup_date": date_str,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "backup_file": backup_file.name,
                },
                project="hattz_empire",
                source="session_backup",
                agent="analyst"  # analyst agent filter
            )

            print(f"[RAG] OK Chunk {i} embedded (doc_id: {doc_id})")
            doc_ids.append(doc_id)

        except Exception as e:
            print(f"[RAG] FAILED Chunk {i}: {e}")

    # 요약
    print("\n" + "="*60)
    print("RAG Embedding Complete!")
    print("="*60)
    print(f"Session ID: {session_id}")
    print(f"Backup File: {backup_file.name}")
    print(f"Total Chunks: {len(chunks)}")
    print(f"Embedded: {len(doc_ids)}/{len(chunks)}")
    print("="*60)

    return doc_ids


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/embed_session_backup.py <backup_file_path>")
        sys.exit(1)

    backup_path = sys.argv[1]
    embed_backup_file(backup_path)


if __name__ == "__main__":
    main()
