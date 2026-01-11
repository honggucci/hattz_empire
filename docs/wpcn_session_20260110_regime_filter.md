# WPCN Session Backup - 2026-01-10
# Regime Filter & Bull-Guard 최적화

## 세션 개요
- **프로젝트**: wpcn-backtester-cli-noflask (와이코프 패턴 선물 백테스터)
- **주제**: Regime Filter 최적화 (Bear/Range/Rally 필터, Bull-Guard v3/v4)
- **결론**: E (v3 G1+G2, 12bar) 채택, 평균 -6.45% (베이스라인 대비 +6.21%p 개선)

---

## 1. 핵심 실험 결과

### 1.1 Range Short 전면 금지 효과
- `range_short_size_mult=0.0` 적용
- Range Short 진입 0건 달성
- 2022년: -17.35% → 개선 확인

### 1.2 Multi-Year Backtest (2021-2024) 기준선
| Year | BTC | A (Baseline) | Bear Short PnL |
|------|-----|--------------|----------------|
| 2021 | +59.5% | -25.78% | +1,205 |
| 2022 | -64.3% | -17.04% | +3,847 |
| 2023 | +155.7% | -5.13% | +1,124 |
| 2024 | +120.7% | -2.69% | +876 |
| **AVG** | | **-12.66%** | **+7,052** |

**핵심 발견**: Bear Short는 4/4년 플러스 (PF 3-25), 하지만 레짐 전환 손실이 엣지를 상쇄

### 1.3 Soft/Hard Bear v2 테스트 (C: 12bar)
| Year | BTC | C (12bar) | KILL |
|------|-----|-----------|------|
| 2021 | +59.5% | -14.92% | 5 |
| 2022 | -64.3% | -4.85% | 18 |
| 2023 | +155.7% | -3.21% | 4 |
| 2024 | +120.7% | -6.39% | 6 |
| **AVG** | | **-7.34%** | 33 |

### 1.4 Bull-Guard v3 테스트 (E: G1+G2)
| Year | E (G1+G2) | KILL |
|------|-----------|------|
| 2021 | -13.62% | 1 |
| 2022 | -5.57% | 7 |
| 2023 | -2.32% | 3 |
| 2024 | -4.31% | 5 |
| **AVG** | **-6.45%** | 16 |

**E가 최선**: 평균 -6.45%, KILL 50% 감소

### 1.5 Bull-Guard v4 테스트 (실패)
- F (Maturity만): E와 동일 (성숙도 무효과)
- G (Full v4): -7.75% (오히려 악화)
- **원인**: Bear-Override가 KILL 스팸, 부분감속이 손실분할로 전락

### 1.6 Bear Short Only 테스트 (실패)
| | E (v3) | BSO |
|---|--------|-----|
| AVG | -6.45% | -12.66% |
| Long PnL | -2,532 | -4,660 |
| Short PnL | +124 | -33 |

**원인**: 롱 차단 실패 + Bull-Guard 없이 숏 필터도 없어서 악화

---

## 2. 최종 권장 설정 (E: v3)

```python
FuturesConfigV3(
    leverage=3.0,

    # Rally Filter
    rally_detector_enabled=True,
    rally_short_disable=True,

    # Bear Filter
    bear_filter_enabled=True,
    bear_long_disable=True,
    bear_long_size_mult=0.0,
    bear_entry_kill_longs=False,  # KILL OFF (역효과 확인됨)

    # Range Filter
    range_short_accum_disable=True,
    range_short_size_mult=0.0,  # Range Short 전면 금지

    # Soft/Hard Bear v2
    soft_hard_bear_enabled=True,
    soft_bear_reduce_pct=0.5,
    hard_bear_confirm_bars=12,  # 12 bars 연속 필요
    hard_bear_kill=True,

    # Bull-Guard v3
    bull_guard_enabled=True,
    bull_guard_g1_enabled=True,   # G1: EMA50 > EMA200
    bull_guard_g2_enabled=True,   # G2: ret_90d > 20%
    bull_guard_g2_threshold=0.20,
    bull_guard_maturity_bars=1,   # 즉시 적용
    bear_override_enabled=False,  # Override OFF
    partial_derisk_enabled=False, # 부분감속 OFF
)
```

---

## 3. 핵심 교훈

### 3.1 v4 실패 원인 3가지
1. **Maturity**: 느린 신호(EMA50>EMA200)에 느린 필터 → 장식
2. **Bear-Override**: 빈도 제어 없이 → KILL 스팸
3. **Partial De-risk**: 재평가 규칙 없이 → 손실 분할

### 3.2 Bear Short Only 실패 원인
- 현재 설정으로 롱 완전 차단 불가
- E의 복잡한 필터들이 실제로 손실을 줄이고 있었음
- "단순화"가 오히려 악화를 야기

### 3.3 전략 구조적 한계
- **Bear Short**: 유일한 진짜 엣지 (4/4년 플러스)
- **Long**: 구조적으로 손실 (-2,532 총계)
- **전체 마이너스 원인**: Bull/Rally에서 롱으로 돈 버는 모듈 부재

---

## 4. 다음 단계 (미완료)

### 4.1 방향 A: Bear Short 집중
- Bear에서만 트레이딩, 그 외 현금
- 목표: 연 5-15% 방어형 알파

### 4.2 방향 B: Bull Long 추세추종 추가
- Rally에서 롱은 트레일링 TP로 런 먹기
- Wyckoff 박스 기반 짧은 TP는 Rally에서 비활성화

---

## 5. 주요 파일 참조

- `futures_backtest_v3.py`: 메인 백테스터 (FuturesConfigV3, Bull-Guard v3/v4 로직)
- `run_multi_year_backtest.py`: 4개년 백테스트
- `run_soft_hard_bear_test.py`: C(12bar) 테스트
- `run_bull_guard_test.py`: E(v3 G1+G2) 테스트
- `run_bull_guard_v4_test.py`: F/G(v4) 테스트 (실패)
- `run_bear_short_only_test.py`: BSO 테스트 (실패)

---

## 6. 수치 요약

| 설정 | 평균 수익률 | 대비 개선 |
|------|------------|----------|
| A (Baseline) | -12.66% | 기준 |
| C (12bar) | -7.34% | +5.32%p |
| **E (v3 G1+G2)** | **-6.45%** | **+6.21%p** |
| G (v4 Full) | -7.75% | +4.91%p |
| BSO | -12.66% | 0%p |

**최종 채택: E (v3 G1+G2, 12bar Hard Bear)**

---

## 7. Step 1-2: Control 폭망 원인 분석 (2026-01-10 추가)

### 7.1 Step 1: Bear Short Benchmark (PASS)

| 전략 | Avg Return | Alpha vs Treatment |
|------|------------|-------------------|
| **Treatment (Wyckoff)** | **-0.51%** | 기준 |
| Control A (Hold Short) | -33.04% | -32.53%p |
| Control B (Momentum Short) | -62.13% | -61.62%p |

**결론**: Treatment가 4/4년 모두 Control 압도. **"언제 숏할지"보다 "언제 숏 안 할지"가 알파**

### 7.2 Step 1.1: Integrity Audit (PASS)

| 감사 항목 | 결과 |
|----------|------|
| 실행모델 공정성 | PASS (Control이 더 유리한 조건) |
| 포지션 사이징 | PASS (Control이 더 작은 노출) |
| Lookahead Bias | PASS (없음) |
| 오버트레이딩 | **Control B: 146x 더 많은 거래!** |

### 7.3 Step 2.0: Transition 유형 해부 (PASS)

| 지표 | 값 | 의미 |
|------|-----|------|
| bear<->range 전환 | **89.3%** | 거의 모든 전환이 bear-range 왔다갔다 |
| Whipsaw 비율 | **75.0%** | 6시간 내 되돌아오는 전환 |
| Seizure 비율 | **30.3%** | 15분 이내 레짐 (발작) |
| 마이크로 발작 | 1,092건 | 5분짜리 레짐 전환 |

**핵심 발견**: 레짐 분류기가 발작을 일으켜 Control이 노이즈를 따라가며 폭망

### 7.4 Step 2.1: 레짐 분류기 안정화 (PASS)

**최적 설정**:
- `min_dwell = 96 bars` (8시간)
- `confirm_bars = 36 bars` (3시간)

| 지표 | Baseline | 안정화 | 개선 |
|------|----------|--------|------|
| Transitions/년 | 1,071 | **320** | **-70%** |
| Seizure | 8.7% | **0.0%** | **-100%** |
| Whipsaw | 63.3% | **0.0%** | **-100%** |

**결론**: 8시간 min_dwell + 3시간 confirm으로 발작/whipsaw 완전 제거

### 7.5 Step 2.2: 전환 진입 금지 (구현 완료)

- 기존 파라미터: `transition_cooldown_bars` (futures_backtest_v3.py)
- 전환 후 N bars 동안 신규 진입 차단
- Step 2.1 안정화와 함께 사용 권장

### 7.6 주요 스크립트 참조

- `run_step0_baseline.py`: E(v3) 진단 베이스라인
- `run_step1_bear_short_benchmark.py`: Control A/B vs Treatment 비교
- `run_step1_1_audit.py`: 무결성 감사 (6항목)
- `run_step2_0_transition_analysis.py`: 전환 유형/whipsaw/seizure 분석
- `run_step2_1_regime_stabilizer.py`: min_dwell/confirm_bars 최적화
- `run_step2_2_transition_entry_ban.py`: 전환 쿨다운 테스트

---

## 8. Step 3-4: Range Policy 검증 (2026-01-10 추가)

### 8.1 Step 3.0: Range Loss Anatomy

Exit Regime별 PnL 분석:
| Exit Regime | Total PnL | Trade Count |
|-------------|-----------|-------------|
| exit@bear | -47.21 USD | 57 |
| exit@range | -138.02 USD | 263 |
| exit@rally | -14.86 USD | 26 |

**핵심 발견**: Range에서 청산되는 거래가 가장 큰 손실원

### 8.2 Step 3.1: Range Policy Test (Naive - 폐기)

~~단순 PnL 제외 방식으로 계산:~~
| Policy | Return | (폐기됨) |
|--------|--------|----------|
| ~~A (Cash)~~ | ~~+58.92%~~ | **잘못된 계산** |
| ~~B (Hold)~~ | ~~-2.03%~~ | |
| ~~C (Reduce50)~~ | ~~+28.44%~~ | |

**경고**: 위 숫자는 "범주 빼기" 방식으로 계산된 것으로 **완전히 잘못됨**

### 8.3 Step 4.1: State Machine 기반 재검증 (정확)

**상태 머신** 기반으로 실제 Bear→Range 전환 시 청산 시뮬레이션:

| Policy | Return (State Machine) | Naive 오차 |
|--------|----------------------|-----------|
| **A (Cash)** | **-17.76%** | -76.68%p |
| **B (Hold)** | **-20.50%** | -18.47%p |
| **C (Reduce50)** | **-19.49%** | -47.93%p |

**개선폭**: Policy A vs B = **+2.74%p** (기존 주장 +60.95%가 아님!)

### 8.4 Step 4.2: PASS Gate v2 (G1-G5)

| Gate | 결과 | 설명 |
|------|------|------|
| G1 (Range Reduction) | PASS | +2.74%p 개선 |
| G2 (Strategy PnL) | PASS | 저하 없음 |
| G3 (Cost Scenarios) | PASS | Realistic/Conservative/PowerTail 모두 A>B |
| G4 (Risk Metrics) | PASS | MDD -12%, Ulcer -8% 개선 |
| **Overall** | **PASS (4/4)** | |

### 8.5 핵심 결론 (수정됨)

1. **Naive 시뮬레이션은 폐기**: +58.92% → -17.76%로 붕괴
2. **실제 개선폭**: +2.74%p (게임 체인저 아님, 미세 개선)
3. **모든 정책이 마이너스**: 문제의 근원은 필터가 아니라 전략 본체
4. **Policy A 채택 가치**: 있음 (작지만 일관된 우위)

### 8.6 운영 반영

**즉시 적용**:
- Policy A 활성화: Bear→Range 전환 시 전량 청산, Range 신규 금지
- 재진입 규칙: Range→Bear 복귀 시에만 BearShort 재개

**모니터링 KPI**:
- `ΔPnL_A_minus_B` (목표: 양(+) 유지)
- `MDD/Ulcer` (목표: 현행 이하)
- `forced_exit_pnl`, `reentry_count`

### 8.7 주요 스크립트 참조

- `run_step3_0_range_loss_anatomy.py`: Exit Regime별 손실 분석
- `run_step3_1_range_policy_test.py`: Naive 정책 비교 (폐기)
- `run_step4_0_standardized_trade_log.py`: 3-View 표준화 Trade 로그
- `run_step4_1_policy_a_state_machine.py`: 상태 머신 기반 Policy 시뮬레이터
- `run_step4_2_pass_gate_v2.py`: 수정된 G1-G5 PASS Gate

---

## 9. 본체 수익성 복구 로드맵

### 9.1 문제 정의
- 필터는 "덜 잃음"에 그침
- 모든 정책이 마이너스 → 전략 본체 개선 필요

### 9.2 방향 A: Range 수익화
- Event-only Range 엔진: Spring/UTAD 테스트에서만 진입
- Exit 스키마: 박스 TP 폐기 → ATR 트레일링 + 구조 붕괴(LL/LH)

### 9.3 방향 B: Rally 런 포착 (P2)
- `ret_30d > X%`에서만 Trend-Long 활성
- 추세 지속 지표: 스프레드·체류시간 기반 마크업 특화

### 9.4 방향 C: BearShort 회피 규칙 강화
- Strategy(BearShort) 뷰로 연도별 4/4 양수 회복 목표
- "언제 숏 안 치냐" 규칙 재강화

### 9.5 일반화 검증
- ETH, 대형 알트 2종 추가
- 2018-2020/2025 구간 추가
- Policy A의 서명(+) 유지 확인
