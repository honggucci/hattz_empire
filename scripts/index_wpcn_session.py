"""
WPCN 세션 내용을 hattz_empire RAG에 임베딩
"""
import sys
import os

# hattz_empire 경로 추가
sys.path.insert(0, "c:/Users/hahonggu/Desktop/coin_master/hattz_empire")
os.chdir("c:/Users/hahonggu/Desktop/coin_master/hattz_empire")

from src.services.rag import index_document

# 세션 요약 문서 읽기
session_file = "docs/wpcn_session_20260110_regime_filter.md"
with open(session_file, "r", encoding="utf-8") as f:
    full_content = f.read()

print("=" * 60)
print("WPCN Session Embedding to hattz_empire RAG")
print("=" * 60)

# 섹션별로 분할하여 임베딩 (더 나은 검색을 위해)
sections = [
    ("세션 개요", "## 세션 개요", "## 1."),
    ("실험 결과 - Range Short", "### 1.1 Range Short", "### 1.2"),
    ("실험 결과 - Multi-Year Baseline", "### 1.2 Multi-Year", "### 1.3"),
    ("실험 결과 - Soft/Hard Bear v2", "### 1.3 Soft/Hard", "### 1.4"),
    ("실험 결과 - Bull-Guard v3", "### 1.4 Bull-Guard v3", "### 1.5"),
    ("실험 결과 - Bull-Guard v4 실패", "### 1.5 Bull-Guard v4", "### 1.6"),
    ("실험 결과 - Bear Short Only 실패", "### 1.6 Bear Short Only", "## 2."),
    ("최종 권장 설정 E v3", "## 2. 최종 권장 설정", "## 3."),
    ("핵심 교훈", "## 3. 핵심 교훈", "## 4."),
    ("다음 단계", "## 4. 다음 단계", "## 5."),
]

# 전체 문서 임베딩
print("\n[1] Indexing full document...")
doc_id = index_document(
    source_type="conversation",
    source_id="wpcn_session_20260110_full",
    content=full_content,
    metadata={
        "date": "2026-01-10",
        "topic": "Regime Filter & Bull-Guard 최적화",
        "conclusion": "E (v3 G1+G2, 12bar) 채택",
        "avg_return": "-6.45%",
    },
    project="wpcn",
    source="claude_code",
    agent="researcher"
)
print(f"  Full doc indexed: {doc_id}")

# 핵심 결론만 별도 임베딩
print("\n[2] Indexing key conclusions...")

key_conclusions = """
# WPCN Regime Filter 최적화 결론 (2026-01-10)

## 최종 채택: E (v3 G1+G2, 12bar Hard Bear)
- 평균 수익률: -6.45% (베이스라인 -12.66% 대비 +6.21%p 개선)
- KILL count: 16회 (기존 33회 대비 50% 감소)

## Bear Short = 유일한 엣지
- 4/4년 플러스 (총 +7,052)
- PF 3-25 (매우 강한 엣지)

## v4 실패 원인 3가지
1. Maturity: 느린 신호에 느린 필터 = 장식
2. Bear-Override: 빈도 제어 없이 = KILL 스팸
3. Partial De-risk: 재평가 규칙 없이 = 손실 분할

## Bear Short Only 실패
- 단순화 시도했으나 -12.66%로 악화
- 원인: 롱 완전 차단 불가 + 필터 없이 더 나빠짐

## 핵심 설정값
- hard_bear_confirm_bars=12
- bull_guard_g1_enabled=True (EMA50 > EMA200)
- bull_guard_g2_enabled=True (ret_90d > 20%)
- bear_override_enabled=False
- partial_derisk_enabled=False
"""

doc_id2 = index_document(
    source_type="conversation",
    source_id="wpcn_session_20260110_conclusions",
    content=key_conclusions,
    metadata={
        "date": "2026-01-10",
        "type": "conclusions",
        "importance": "high",
    },
    project="wpcn",
    source="claude_code",
    agent="researcher"
)
print(f"  Conclusions indexed: {doc_id2}")

# 실패 교훈 별도 임베딩 (나중에 같은 실수 방지용)
print("\n[3] Indexing lessons learned...")

lessons = """
# WPCN 실패 교훈 (2026-01-10)

## v4 Bull-Guard 실패
- 복잡성만 늘리고 성과 악화
- Maturity(성숙도): 이미 느린 신호(EMA50>EMA200)에 또 느린 필터를 붙이면 의미 없음
- Bear-Override: 쿨다운/1회성/락 없이 조건만 있으면 스팸 발동
- Partial De-risk: "감속 → 재평가 → 재확대/종료" 세트가 없으면 손실만 분할됨

## Bear Short Only 실패
- 현재 구조로는 롱 완전 차단 불가 (bear_long_disable은 Bear 레짐에서만 작동)
- E의 Bull-Guard가 롱 손실을 -2,532로 줄이고 있었음 (없으면 -4,660)
- 필터 없이 날것 전략은 오히려 악화

## 일반 교훈
- "더 똑똑해 보이는 규칙"이 항상 더 좋은 건 아님
- 숫자로 검증 없이 감으로 추가하면 안 됨
- 단순화도 검증 필요 (단순 != 더 좋음)
"""

doc_id3 = index_document(
    source_type="conversation",
    source_id="wpcn_session_20260110_lessons",
    content=lessons,
    metadata={
        "date": "2026-01-10",
        "type": "lessons_learned",
        "importance": "high",
    },
    project="wpcn",
    source="claude_code",
    agent="researcher"
)
print(f"  Lessons indexed: {doc_id3}")

print("\n" + "=" * 60)
print("DONE! 3 documents indexed to hattz_empire RAG with project='wpcn'")
print("=" * 60)
