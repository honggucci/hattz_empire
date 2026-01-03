"""비용 효율 분석"""

# 모델별 가격 (per 1M tokens: input/output)
models = {
    # v1.0 (이전)
    'GPT-5.2 Thinking': (10.0, 40.0),
    'Claude Opus 4.5': (5.0, 25.0),
    'Gemini 3 Pro': (3.0, 15.0),

    # v2.0 (현재)
    'Gemini 2.0 Flash': (0.10, 0.40),
    'Claude Sonnet 4': (3.0, 15.0),
    'Perplexity Sonar': (3.0, 15.0),
}

# 일반적인 작업 분포 가정 (1000 requests)
v1_distribution = {
    'GPT-5.2 Thinking': 400,  # PM, 전략
    'Claude Opus 4.5': 400,   # 코더, QA
    'Gemini 3 Pro': 200,      # Analyst
}

v2_distribution = {
    'Gemini 2.0 Flash': 800,  # PM, Analyst, 일반
    'Claude Sonnet 4': 120,   # Coder, QA
    'Claude Opus 4.5': 30,    # 고위험만
    'GPT-5.2 Thinking': 20,   # 추론만
    'Perplexity Sonar': 30,   # 검색
}

# 평균 토큰 사용량 (per request)
avg_input = 500
avg_output = 1000

def calc_cost(distribution, avg_in, avg_out):
    total = 0
    for model, count in distribution.items():
        if model in models:
            in_price, out_price = models[model]
            cost = count * ((avg_in / 1_000_000) * in_price + (avg_out / 1_000_000) * out_price)
            total += cost
    return total

v1_cost = calc_cost(v1_distribution, avg_input, avg_output)
v2_cost = calc_cost(v2_distribution, avg_input, avg_output)

print('=' * 60)
print('HattzRouter 비용 효율 분석 (1000 requests 기준)')
print('=' * 60)
print()
print('[v1.0 - 기존 배치]')
print('  PM/전략: GPT-5.2 Thinking (400건)')
print('  Coder/QA: Claude Opus 4.5 (400건)')
print('  Analyst: Gemini 3 Pro (200건)')
print(f'  총 비용: ${v1_cost:.2f}')
print()
print('[v2.0 - 비용 최적화]')
print('  Budget (PM/Analyst): Gemini Flash (800건)')
print('  Standard (Coder/QA): Sonnet 4 (120건)')
print('  VIP (고위험): Opus 4.5 (30건)')
print('  Thinking (추론): GPT-4o (20건)')
print('  Research (검색): Perplexity (30건)')
print(f'  총 비용: ${v2_cost:.2f}')
print()
print('=' * 60)
savings = ((v1_cost - v2_cost) / v1_cost) * 100
print(f'절감액: ${v1_cost - v2_cost:.2f}')
print(f'절감률: {savings:.1f}%')
print('=' * 60)
print()
print('[품질 vs 비용 트레이드오프]')
print()
print('  작업 유형       v1.0 모델          v2.0 모델          품질')
print('  -------------   ----------------   ----------------   ------')
print('  PM 일반         GPT-5 Thinking     Gemini Flash       약간 하락')
print('  코드 수정       Opus 4.5           Sonnet 4           약간 하락')
print('  고위험 코드     Opus 4.5           Opus 4.5           동일')
print('  버그 원인분석   (없음)             GPT Thinking       향상')
print('  실시간 검색     (없음)             Perplexity         신규')
