"""
Hattz Empire - Cost Tracker Service
API 호출 비용 추적 및 분석
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from . import database as db


# 모델별 가격 (per 1M tokens: input/output USD)
MODEL_PRICING = {
    # Anthropic
    'claude-opus-4-5-20250514': (15.0, 75.0),
    'claude-sonnet-4-20250514': (3.0, 15.0),
    'claude-3-5-sonnet-20241022': (3.0, 15.0),
    'claude-3-5-haiku-20241022': (0.80, 4.0),

    # OpenAI
    'gpt-4o': (2.50, 10.0),
    'gpt-5-mini': (0.30, 1.25),
    'gpt-5.2': (2.50, 10.0),
    'o1': (15.0, 60.0),
    'o1-mini': (3.0, 12.0),
    'o3-mini': (1.10, 4.40),

    # Google
    'gemini-3-flash': (0.10, 0.40),
    'gemini-2.0-flash': (0.10, 0.40),
    'gemini-2.0-flash-lite': (0.075, 0.30),
    'gemini-1.5-pro': (1.25, 5.0),
    'gemini-1.5-flash': (0.075, 0.30),

    # Perplexity
    'sonar': (1.0, 1.0),
    'sonar-pro': (3.0, 15.0),
    'sonar-reasoning': (1.0, 5.0),
}

# 모델 티어 매핑
MODEL_TIERS = {
    'budget': ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gpt-5-mini', 'claude-3-5-haiku-20241022'],
    'standard': ['claude-sonnet-4-20250514', 'claude-3-5-sonnet-20241022', 'gpt-4o', 'gemini-1.5-pro'],
    'premium': ['claude-opus-4-5-20250514', 'o1', 'o1-mini'],
    'thinking': ['o3-mini', 'o1'],
    'research': ['sonar', 'sonar-pro', 'sonar-reasoning'],
}


@dataclass
class CostRecord:
    """비용 기록"""
    id: Optional[int] = None
    session_id: str = ""
    agent_role: str = ""
    model_id: str = ""
    model_tier: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    created_at: Optional[datetime] = None


def create_cost_table() -> bool:
    """비용 추적 테이블 생성"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'api_costs')
                BEGIN
                    CREATE TABLE api_costs (
                        id INT IDENTITY(1,1) PRIMARY KEY,
                        session_id VARCHAR(50),
                        agent_role VARCHAR(30),
                        model_id VARCHAR(100),
                        model_tier VARCHAR(30),
                        input_tokens INT DEFAULT 0,
                        output_tokens INT DEFAULT 0,
                        cost_usd DECIMAL(10, 6) DEFAULT 0,
                        created_at DATETIME DEFAULT GETDATE()
                    );
                    CREATE INDEX idx_costs_session ON api_costs(session_id);
                    CREATE INDEX idx_costs_model ON api_costs(model_id);
                    CREATE INDEX idx_costs_created ON api_costs(created_at);
                    CREATE INDEX idx_costs_tier ON api_costs(model_tier);
                END
            """)
            conn.commit()
            print("[CostTracker] Table created/verified")
            return True
    except Exception as e:
        print(f"[CostTracker] Table creation error: {e}")
        return False


def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """토큰 수로 비용 계산"""
    # 모델 ID에서 정확한 가격 찾기
    pricing = None
    for model_key, prices in MODEL_PRICING.items():
        if model_key in model_id or model_id in model_key:
            pricing = prices
            break

    if not pricing:
        # 기본값: 중간 정도 가격
        pricing = (1.0, 5.0)

    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]

    return input_cost + output_cost


def get_model_tier(model_id: str) -> str:
    """모델 ID로 티어 찾기"""
    for tier, models in MODEL_TIERS.items():
        for model in models:
            if model in model_id or model_id in model:
                return tier
    return "standard"


def record_api_call(
    session_id: str,
    agent_role: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int
) -> Optional[int]:
    """API 호출 비용 기록"""
    try:
        cost = calculate_cost(model_id, input_tokens, output_tokens)
        tier = get_model_tier(model_id)

        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO api_costs (
                    session_id, agent_role, model_id, model_tier,
                    input_tokens, output_tokens, cost_usd
                )
                OUTPUT INSERTED.id
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (session_id, agent_role, model_id, tier, input_tokens, output_tokens, cost))

            row = cursor.fetchone()
            conn.commit()

            return row[0] if row else None
    except Exception as e:
        print(f"[CostTracker] Record error: {e}")
        return None


def get_daily_costs(days: int = 7) -> List[Dict[str, Any]]:
    """일별 비용 조회"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    CAST(created_at AS DATE) as date,
                    COUNT(*) as call_count,
                    SUM(input_tokens) as total_input,
                    SUM(output_tokens) as total_output,
                    SUM(cost_usd) as total_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY CAST(created_at AS DATE)
                ORDER BY date DESC
            """, (-days,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "date": row.date.isoformat() if row.date else None,
                    "call_count": row.call_count,
                    "total_input": row.total_input or 0,
                    "total_output": row.total_output or 0,
                    "total_cost": float(row.total_cost or 0)
                })
            return results
    except Exception as e:
        print(f"[CostTracker] Daily costs error: {e}")
        return []


def get_model_breakdown(days: int = 30) -> List[Dict[str, Any]]:
    """모델별 비용 분석"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    model_id,
                    model_tier,
                    COUNT(*) as call_count,
                    SUM(input_tokens) as total_input,
                    SUM(output_tokens) as total_output,
                    SUM(cost_usd) as total_cost,
                    AVG(cost_usd) as avg_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY model_id, model_tier
                ORDER BY total_cost DESC
            """, (-days,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "model_id": row.model_id,
                    "model_tier": row.model_tier,
                    "call_count": row.call_count,
                    "total_input": row.total_input or 0,
                    "total_output": row.total_output or 0,
                    "total_cost": float(row.total_cost or 0),
                    "avg_cost": float(row.avg_cost or 0)
                })
            return results
    except Exception as e:
        print(f"[CostTracker] Model breakdown error: {e}")
        return []


def get_agent_breakdown(days: int = 30) -> List[Dict[str, Any]]:
    """에이전트별 비용 분석"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    agent_role,
                    COUNT(*) as call_count,
                    SUM(input_tokens) as total_input,
                    SUM(output_tokens) as total_output,
                    SUM(cost_usd) as total_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY agent_role
                ORDER BY total_cost DESC
            """, (-days,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "agent_role": row.agent_role,
                    "call_count": row.call_count,
                    "total_input": row.total_input or 0,
                    "total_output": row.total_output or 0,
                    "total_cost": float(row.total_cost or 0)
                })
            return results
    except Exception as e:
        print(f"[CostTracker] Agent breakdown error: {e}")
        return []


def get_tier_breakdown(days: int = 30) -> List[Dict[str, Any]]:
    """티어별 비용 분석"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    model_tier,
                    COUNT(*) as call_count,
                    SUM(cost_usd) as total_cost,
                    AVG(cost_usd) as avg_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY model_tier
                ORDER BY total_cost DESC
            """, (-days,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "tier": row.model_tier,
                    "call_count": row.call_count,
                    "total_cost": float(row.total_cost or 0),
                    "avg_cost": float(row.avg_cost or 0)
                })
            return results
    except Exception as e:
        print(f"[CostTracker] Tier breakdown error: {e}")
        return []


def get_summary(days: int = 30) -> Dict[str, Any]:
    """전체 비용 요약"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(input_tokens) as total_input,
                    SUM(output_tokens) as total_output,
                    SUM(cost_usd) as total_cost,
                    AVG(cost_usd) as avg_cost_per_call,
                    MIN(created_at) as first_call,
                    MAX(created_at) as last_call
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
            """, (-days,))

            row = cursor.fetchone()
            if row:
                return {
                    "total_calls": row.total_calls or 0,
                    "total_input_tokens": row.total_input or 0,
                    "total_output_tokens": row.total_output or 0,
                    "total_cost_usd": float(row.total_cost or 0),
                    "avg_cost_per_call": float(row.avg_cost_per_call or 0),
                    "period_days": days,
                    "first_call": row.first_call.isoformat() if row.first_call else None,
                    "last_call": row.last_call.isoformat() if row.last_call else None
                }
    except Exception as e:
        print(f"[CostTracker] Summary error: {e}")

    return {
        "total_calls": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "avg_cost_per_call": 0.0,
        "period_days": days
    }


def get_hourly_distribution(days: int = 7) -> List[Dict[str, Any]]:
    """시간대별 호출 분포"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    DATEPART(hour, created_at) as hour,
                    COUNT(*) as call_count,
                    SUM(cost_usd) as total_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY DATEPART(hour, created_at)
                ORDER BY hour
            """, (-days,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "hour": row.hour,
                    "call_count": row.call_count,
                    "total_cost": float(row.total_cost or 0)
                })
            return results
    except Exception as e:
        print(f"[CostTracker] Hourly distribution error: {e}")
        return []


def get_model_call_stats(days: int = 30) -> Dict[str, Any]:
    """모델별 호출 통계 및 쏠림 현상 분석"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 모델별 호출 횟수
            cursor.execute("""
                SELECT
                    model_id,
                    model_tier,
                    COUNT(*) as call_count,
                    SUM(cost_usd) as total_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY model_id, model_tier
                ORDER BY call_count DESC
            """, (-days,))

            models = []
            total_calls = 0
            for row in cursor.fetchall():
                models.append({
                    "model_id": row.model_id,
                    "tier": row.model_tier,
                    "calls": row.call_count,
                    "cost": float(row.total_cost or 0)
                })
                total_calls += row.call_count

            # 비율 계산 및 쏠림 분석
            for m in models:
                m["percentage"] = round((m["calls"] / total_calls * 100), 1) if total_calls > 0 else 0

            # 쏠림 지수 계산 (Gini-like coefficient)
            # 완전 균등 분배 = 0, 완전 쏠림 = 1
            if len(models) > 1 and total_calls > 0:
                n = len(models)
                percentages = sorted([m["percentage"] for m in models])
                cumulative = 0
                gini_sum = 0
                for i, p in enumerate(percentages):
                    cumulative += p
                    gini_sum += cumulative
                gini = 1 - (2 * gini_sum / (n * 100))
                concentration_index = max(0, min(1, gini))
            else:
                concentration_index = 0

            # 가장 많이 사용된 모델
            top_model = models[0] if models else None

            # 쏠림 경고 판단
            concentration_warning = None
            if top_model and top_model["percentage"] > 70:
                concentration_warning = f"경고: {top_model['model_id']}에 {top_model['percentage']}% 쏠림 발생"
            elif top_model and top_model["percentage"] > 50:
                concentration_warning = f"주의: {top_model['model_id']}에 {top_model['percentage']}% 집중"

            return {
                "models": models,
                "total_calls": total_calls,
                "model_count": len(models),
                "concentration_index": round(concentration_index, 2),
                "top_model": top_model,
                "concentration_warning": concentration_warning,
                "period_days": days
            }
    except Exception as e:
        print(f"[CostTracker] Model stats error: {e}")
        return {"models": [], "total_calls": 0, "model_count": 0}


def get_usage_trends(days: int = 14) -> Dict[str, Any]:
    """사용량 트렌드 분석"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 일별 호출 추이
            cursor.execute("""
                SELECT
                    CAST(created_at AS DATE) as date,
                    model_tier,
                    COUNT(*) as call_count,
                    SUM(cost_usd) as total_cost
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY CAST(created_at AS DATE), model_tier
                ORDER BY date
            """, (-days,))

            daily_by_tier = {}
            for row in cursor.fetchall():
                date_str = row.date.isoformat() if row.date else "unknown"
                if date_str not in daily_by_tier:
                    daily_by_tier[date_str] = {"date": date_str, "tiers": {}}
                daily_by_tier[date_str]["tiers"][row.model_tier] = {
                    "calls": row.call_count,
                    "cost": float(row.total_cost or 0)
                }

            # 전주 대비 변화율
            cursor.execute("""
                WITH ThisWeek AS (
                    SELECT COUNT(*) as calls, SUM(cost_usd) as cost
                    FROM api_costs
                    WHERE created_at >= DATEADD(day, -7, GETDATE())
                ),
                LastWeek AS (
                    SELECT COUNT(*) as calls, SUM(cost_usd) as cost
                    FROM api_costs
                    WHERE created_at >= DATEADD(day, -14, GETDATE())
                      AND created_at < DATEADD(day, -7, GETDATE())
                )
                SELECT
                    t.calls as this_week_calls,
                    t.cost as this_week_cost,
                    l.calls as last_week_calls,
                    l.cost as last_week_cost
                FROM ThisWeek t, LastWeek l
            """)

            row = cursor.fetchone()
            if row:
                this_calls = row.this_week_calls or 0
                last_calls = row.last_week_calls or 0
                this_cost = float(row.this_week_cost or 0)
                last_cost = float(row.last_week_cost or 0)

                calls_change = ((this_calls - last_calls) / last_calls * 100) if last_calls > 0 else 0
                cost_change = ((this_cost - last_cost) / last_cost * 100) if last_cost > 0 else 0
            else:
                calls_change = 0
                cost_change = 0

            return {
                "daily_by_tier": list(daily_by_tier.values()),
                "week_over_week": {
                    "calls_change_percent": round(calls_change, 1),
                    "cost_change_percent": round(cost_change, 1)
                },
                "period_days": days
            }
    except Exception as e:
        print(f"[CostTracker] Trends error: {e}")
        return {"daily_by_tier": [], "week_over_week": {}}


def get_efficiency_metrics(days: int = 30) -> Dict[str, Any]:
    """비용 효율성 지표"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 티어별 평균 비용 및 토큰 효율
            cursor.execute("""
                SELECT
                    model_tier,
                    AVG(cost_usd) as avg_cost,
                    AVG(CAST(input_tokens + output_tokens AS FLOAT) / NULLIF(cost_usd, 0)) as tokens_per_dollar,
                    COUNT(*) as call_count
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                  AND cost_usd > 0
                GROUP BY model_tier
            """, (-days,))

            tier_efficiency = []
            for row in cursor.fetchall():
                tier_efficiency.append({
                    "tier": row.model_tier,
                    "avg_cost": float(row.avg_cost or 0),
                    "tokens_per_dollar": int(row.tokens_per_dollar or 0),
                    "call_count": row.call_count
                })

            # 예상 월간 비용
            cursor.execute("""
                SELECT
                    SUM(cost_usd) as total_cost,
                    COUNT(*) as call_count,
                    DATEDIFF(day, MIN(created_at), GETDATE()) + 1 as active_days
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
            """, (-days,))

            row = cursor.fetchone()
            if row and row.active_days and row.active_days > 0:
                daily_avg = float(row.total_cost or 0) / row.active_days
                monthly_estimate = daily_avg * 30
                daily_calls = row.call_count / row.active_days
            else:
                daily_avg = 0
                monthly_estimate = 0
                daily_calls = 0

            # Budget 티어 사용 비율 (비용 최적화 지표)
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN model_tier = 'budget' THEN 1 ELSE 0 END) as budget_calls,
                    COUNT(*) as total_calls
                FROM api_costs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
            """, (-days,))

            row = cursor.fetchone()
            budget_ratio = 0
            if row and row.total_calls > 0:
                budget_ratio = round((row.budget_calls or 0) / row.total_calls * 100, 1)

            return {
                "tier_efficiency": tier_efficiency,
                "daily_avg_cost": round(daily_avg, 4),
                "monthly_estimate": round(monthly_estimate, 2),
                "daily_avg_calls": round(daily_calls, 1),
                "budget_tier_ratio": budget_ratio,
                "period_days": days
            }
    except Exception as e:
        print(f"[CostTracker] Efficiency error: {e}")
        return {}


# 테이블 생성 (모듈 로드 시)
create_cost_table()
