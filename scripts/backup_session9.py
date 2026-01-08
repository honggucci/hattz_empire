"""Session 9 RAG Embedding Script"""
import sys
sys.path.insert(0, "c:\\Users\\hahonggu\\Desktop\\coin_master\\hattz_empire")

from src.services.rag import index_messages_from_db, search_messages

# 최근 메시지 임베딩 (DB에서 자동 로드)
print("Indexing recent messages from DB...")
indexed = index_messages_from_db(limit=50, project='hattz_empire')
print(f'Indexed {indexed} messages for RAG')

# 검증: FlowMonitor 검색
print('\nSearching for FlowMonitor related content...')
results = search_messages('FlowMonitor 부트로더 원칙 준수', project='hattz_empire', top_k=3)
print(f'Search results: {len(results.documents)} found')
for doc in results.documents[:3]:
    content = doc.content[:80] if doc.content else ""
    print(f'  - {content}...')

print('\nRAG embedding complete.')
