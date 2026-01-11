# HMM Risk Filter OOS Validation Session (2026-01-11)

## 최종 결론: 운영 가능한 리스크 오버레이 확정

### 검증 결과 요약

| 검증 항목 | 결과 | 상세 |
|-----------|------|------|
| Ablation Test | ✅ | Soft Sizing 81%, Cooldown 24%, 나머지 negligible |
| VaR Lookahead | ✅ 없음 | OOS(21-23) vs Original 차이 평균 0.39% |
| OOS Performance | ✅ | OOS VaR로 +45,031 (원본보다 10.6% 더 좋음) |
| Walk-Forward | ✅ | ALL 3 periods positive (+20.8% ~ +40.2%) |

---

## 1. Ablation Test 결과

```
Case                               Filter%    PnL Improve
-------------------------------------------------------
1. Baseline (No Filter)              0.0%         +0.00
2. Uncertainty Gate Only             0.0%         +0.00
3. Transition Cooldown Only          5.4%      +9668.02
4. Soft Sizing Only                  0.0%     +33264.83  ← 81% 기여
5. Markdown SHORT_ONLY Only          0.0%      +1277.10
6. ALL Rules Combined                5.5%     +41120.23
7. Cooldown + Sizing                 5.4%     +40719.29  ← 핵심 조합
```

**핵심 발견**:
- Soft Sizing이 전체 개선의 81% 담당 → 메인 엔진
- Transition Cooldown은 24% → 보조/안전벨트
- Uncertainty Gate = 0% → HMM이 너무 확신형으로 학습됨 (트리거 안 걸림)
- Markdown SHORT_ONLY = 3% → 거의 무의미

---

## 2. OOS VaR 검증

### VaR 비교 (Train: 2021-2023, Test: 2024)

| State | OOS VaR | Original VaR | Diff |
|-------|---------|--------------|------|
| accumulation | -5.56% | -5.80% | +0.24% |
| re_accumulation | -6.91% | -6.39% | -0.52% |
| distribution | -5.63% | -5.62% | -0.01% |
| re_distribution | -8.85% | -8.33% | -0.52% |
| markup | -7.16% | -6.48% | -0.68% |
| markdown | -10.52% | -10.16% | -0.36% |

**평균 절대 차이: 0.39%** → **Lookahead 없음 확인**

### 2024 적용 결과

| Method | Filtered PnL | Improvement |
|--------|--------------|-------------|
| OOS VaR (21-23 train) | -103,117 | **+45,031** |
| Original VaR | -107,429 | +40,719 |

**OOS VaR가 오히려 +4,312 (10.6%) 더 좋음!**

이유: OOS VaR가 더 보수적 → 사이즈 더 작게 → 손실 방어 효과

---

## 3. Walk-Forward Validation

```
Train                Test   Baseline     Filtered   Improve%
-------------------------------------------------------------
2021-2022            2023    -140,829      -84,234    +40.2%
2022-2023            2024    -148,149     -117,350    +20.8%
2021-2022-2023       2024    -148,149     -103,117    +30.4%

Average: +30.5%
Min: +20.8%
Max: +40.2%

[OK] ALL periods show improvement - strategy is ROBUST!
```

---

## 4. 최종 정책 (v3)

```python
# OOS VaR values (2021-2023 calibration)
VAR5_BY_STATE = {
    'accumulation': -5.56,
    're_accumulation': -6.91,
    'distribution': -5.63,
    're_distribution': -8.85,
    'markup': -7.16,
    'markdown': -10.52,
}

# Core policy
if transition_detected (delta > 0.20):
    return NO_TRADE, cooldown=2bars

expected_var = sum(p_i * abs(var_i))  # posterior-weighted
size_mult = clip(var_target / expected_var, 0.25, 1.25)
return ALLOW, size_mult
```

---

## 5. 운영 권장사항

### 확정 사항
- **HMM = 리스크 레짐 오버레이** (알파 예측기 아님)
- **핵심 엔진 = expected VaR 기반 Soft Sizing**
- **보조 = Transition Cooldown** (2 bars)

### 향후 고려 (옵션)
1. **Rolling VaR**: 분기별 재계산 + 스무딩 (0.7*old + 0.3*new)
2. **Lower bound 조정**: 0.25 → 0.20 (Max DD 기준으로 결정)
3. **CVaR**: 지금은 VaR로 충분, tail이 자주 터지면 전환 고려

---

## 6. 파일 목록

| 파일 | 설명 |
|------|------|
| `run_step9_hmm_risk_filter.py` | HMM Risk Filter v3 (OOS VaR 적용) |
| `test_hmm_ablation.py` | Ablation test 스크립트 |
| `test_oos_quick.py` | OOS VaR 검증 스크립트 |
| `test_walk_forward_quick.py` | Walk-forward validation 스크립트 |
| `test_hmm_filter_2024.py` | 2024 단일년도 테스트 |

---

## 7. 핵심 인사이트

> "확률적 상태 추정 → tail risk 예산 배분(사이징) 엔진"
>
> 이것이 HMM의 진짜 역할. 와이코프 패턴 탐지기가 아니라,
> 리스크 예산 관리 시스템으로 확정.
