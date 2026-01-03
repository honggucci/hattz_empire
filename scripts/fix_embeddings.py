"""
Hattz Empire - Embeddings NULL 값 수정 스크립트
기존 NULL인 project, source 컬럼을 채웁니다.

실행: python scripts/fix_embeddings.py
"""
import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.rag import backfill_embeddings_null_values, get_stats


def main():
    print("=" * 60)
    print("Hattz Empire - Embeddings NULL 값 수정")
    print("=" * 60)

    # 현재 상태 확인
    print("\n[BEFORE] 현재 상태:")
    stats = get_stats()
    print(f"  총 문서: {stats['total_documents']}")
    print(f"  프로젝트별: {stats['by_project']}")

    # NULL 값 채우기
    print("\n[FIXING] NULL 값 채우는 중...")
    result = backfill_embeddings_null_values("hattz_empire")

    print(f"  project 업데이트: {result['project_updated']}개")
    print(f"  source 업데이트: {result['source_updated']}개")

    # 수정 후 상태
    print("\n[AFTER] 수정 후 상태:")
    stats = get_stats()
    print(f"  총 문서: {stats['total_documents']}")
    print(f"  프로젝트별: {stats['by_project']}")

    print("\n" + "=" * 60)
    print("완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
