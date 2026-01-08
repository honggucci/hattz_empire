"""
Hattz Empire - Analytics API (v2.6)
운영 분석 + 비용 알림 시스템

Level 1: Operations Optimization
- Daily Report: 에이전트별 비용/호출/성공률
- Cost Alert: 일일 한도 초과 시 경고
- Failure Rate: 에이전트별 실패율 모니터링

agent_logs 테이블 스키마:
- role (varchar): 에이전트 역할 (pm, coder, qa 등)
- model (varchar): 모델 ID
- result (varchar): success, error, pending, timeout
- cost_usd (decimal): 호출 비용
- latency_ms (int): 응답 시간
- input_tokens, output_tokens (int): 토큰 수
"""
from flask import request, jsonify, render_template
from flask_login import login_required
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from . import analytics_bp
from src.services import database as db


# 설정
DAILY_COST_LIMIT_USD = 5.0  # 일일 비용 한도
FAILURE_RATE_THRESHOLD = 0.30  # 실패율 경고 임계치 (30%)
LATENCY_P95_THRESHOLD_SEC = 30  # P95 레이턴시 경고 임계치


@analytics_bp.route('/')
@login_required
def dashboard():
    """Analytics 대시보드 페이지"""
    return render_template('analytics.html')


@analytics_bp.route('/daily')
@login_required
def daily_report():
    """일일 운영 보고서

    Returns:
        - date: 보고서 날짜
        - summary: 전체 요약 (비용, 호출 수, 성공률)
        - by_agent: 에이전트별 상세
        - by_model: 모델별 상세
        - alerts: 경고 목록
    """
    # 날짜 파라미터 (기본: 어제)
    date_str = request.args.get('date')
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400
    else:
        target_date = (datetime.now() - timedelta(days=1)).date()

    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 1. 전체 요약
            cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(cost_usd) as total_cost,
                    SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN result = 'error' THEN 1 ELSE 0 END) as error_count,
                    AVG(latency_ms) as avg_latency,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens
                FROM agent_logs
                WHERE CAST(created_at AS DATE) = ?
            """, (target_date,))

            row = cursor.fetchone()
            total_calls = row.total_calls or 0
            total_cost = float(row.total_cost or 0)
            success_count = row.success_count or 0
            error_count = row.error_count or 0
            success_rate = (success_count / total_calls * 100) if total_calls > 0 else 0

            summary = {
                "total_calls": total_calls,
                "total_cost_usd": round(total_cost, 4),
                "success_count": success_count,
                "error_count": error_count,
                "success_rate_pct": round(success_rate, 1),
                "avg_latency_ms": int(row.avg_latency or 0),
                "total_input_tokens": row.total_input_tokens or 0,
                "total_output_tokens": row.total_output_tokens or 0,
            }

            # 2. 에이전트별 분석 (role 컬럼 사용)
            cursor.execute("""
                SELECT
                    role,
                    COUNT(*) as calls,
                    SUM(cost_usd) as cost,
                    SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END) as successes,
                    AVG(latency_ms) as avg_latency,
                    MAX(latency_ms) as max_latency
                FROM agent_logs
                WHERE CAST(created_at AS DATE) = ?
                GROUP BY role
                ORDER BY cost DESC
            """, (target_date,))

            by_agent = []
            for r in cursor.fetchall():
                agent_calls = r.calls or 0
                agent_successes = r.successes or 0
                rate = (agent_successes / agent_calls * 100) if agent_calls > 0 else 0
                by_agent.append({
                    "agent": r.role,
                    "calls": agent_calls,
                    "cost_usd": round(float(r.cost or 0), 4),
                    "success_rate_pct": round(rate, 1),
                    "avg_latency_ms": int(r.avg_latency or 0),
                    "max_latency_ms": int(r.max_latency or 0),
                })

            # 3. 모델별 분석 (model 컬럼 사용)
            cursor.execute("""
                SELECT
                    model,
                    COUNT(*) as calls,
                    SUM(cost_usd) as cost,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens
                FROM agent_logs
                WHERE CAST(created_at AS DATE) = ?
                  AND model IS NOT NULL
                GROUP BY model
                ORDER BY cost DESC
            """, (target_date,))

            by_model = []
            for r in cursor.fetchall():
                by_model.append({
                    "model": r.model,
                    "calls": r.calls,
                    "cost_usd": round(float(r.cost or 0), 4),
                    "input_tokens": r.input_tokens or 0,
                    "output_tokens": r.output_tokens or 0,
                })

            # 4. result_code별 분포 (error_message 대신)
            cursor.execute("""
                SELECT
                    result_code,
                    COUNT(*) as count
                FROM agent_logs
                WHERE CAST(created_at AS DATE) = ?
                  AND result = 'error'
                  AND result_code IS NOT NULL
                GROUP BY result_code
                ORDER BY count DESC
            """, (target_date,))

            error_codes = []
            for r in cursor.fetchall():
                error_codes.append({
                    "code": r.result_code,
                    "count": r.count
                })

            # 5. 알림 생성
            alerts = []

            # 5-1. 비용 한도 초과
            if total_cost > DAILY_COST_LIMIT_USD:
                alerts.append({
                    "type": "cost_exceeded",
                    "severity": "critical",
                    "message": f"일일 비용 ${total_cost:.2f}가 한도 ${DAILY_COST_LIMIT_USD:.2f}를 초과했습니다"
                })
            elif total_cost > DAILY_COST_LIMIT_USD * 0.8:
                alerts.append({
                    "type": "cost_warning",
                    "severity": "warning",
                    "message": f"일일 비용 ${total_cost:.2f}가 한도의 80%에 도달했습니다"
                })

            # 5-2. 에이전트별 실패율 경고
            for agent in by_agent:
                if agent["calls"] >= 5:  # 최소 5회 이상 호출된 에이전트만
                    failure_rate = 1 - (agent["success_rate_pct"] / 100)
                    if failure_rate > FAILURE_RATE_THRESHOLD:
                        alerts.append({
                            "type": "high_failure_rate",
                            "severity": "warning",
                            "message": f"{agent['agent']} 에이전트 실패율 {failure_rate*100:.1f}% (임계치: {FAILURE_RATE_THRESHOLD*100:.0f}%)"
                        })

            # 5-3. P95 레이턴시 경고 (PERCENTILE_CONT 대신 간단한 방식)
            if total_calls > 0:
                cursor.execute("""
                    SELECT TOP 1 latency_ms
                    FROM (
                        SELECT latency_ms,
                               ROW_NUMBER() OVER (ORDER BY latency_ms) as rn,
                               COUNT(*) OVER () as total
                        FROM agent_logs
                        WHERE CAST(created_at AS DATE) = ?
                          AND latency_ms IS NOT NULL
                    ) t
                    WHERE rn >= total * 0.95
                    ORDER BY rn
                """, (target_date,))

                p95_row = cursor.fetchone()
                p95_latency = float(p95_row.latency_ms or 0) if p95_row else 0

                if p95_latency > LATENCY_P95_THRESHOLD_SEC * 1000:
                    alerts.append({
                        "type": "high_latency",
                        "severity": "warning",
                        "message": f"P95 레이턴시 {p95_latency/1000:.1f}초가 임계치 {LATENCY_P95_THRESHOLD_SEC}초를 초과했습니다"
                    })

            return jsonify({
                "date": target_date.isoformat(),
                "generated_at": datetime.now().isoformat(),
                "summary": summary,
                "by_agent": by_agent,
                "by_model": by_model,
                "error_codes": error_codes,
                "alerts": alerts,
                "thresholds": {
                    "daily_cost_limit_usd": DAILY_COST_LIMIT_USD,
                    "failure_rate_threshold": FAILURE_RATE_THRESHOLD,
                    "latency_p95_threshold_sec": LATENCY_P95_THRESHOLD_SEC
                }
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route('/alerts')
@login_required
def get_alerts():
    """현재 활성화된 알림 조회

    오늘 + 어제 데이터 기준으로 알림 생성
    """
    alerts = []

    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 오늘 비용
            cursor.execute("""
                SELECT SUM(cost_usd) as today_cost
                FROM agent_logs
                WHERE CAST(created_at AS DATE) = CAST(GETDATE() AS DATE)
            """)
            row = cursor.fetchone()
            today_cost = float(row.today_cost or 0)

            if today_cost > DAILY_COST_LIMIT_USD:
                alerts.append({
                    "id": "cost_exceeded_today",
                    "type": "cost_exceeded",
                    "severity": "critical",
                    "message": f"오늘 비용 ${today_cost:.2f}가 한도 ${DAILY_COST_LIMIT_USD:.2f}를 초과했습니다",
                    "value": today_cost,
                    "threshold": DAILY_COST_LIMIT_USD
                })
            elif today_cost > DAILY_COST_LIMIT_USD * 0.8:
                alerts.append({
                    "id": "cost_warning_today",
                    "type": "cost_warning",
                    "severity": "warning",
                    "message": f"오늘 비용 ${today_cost:.2f}가 한도의 80%에 도달했습니다",
                    "value": today_cost,
                    "threshold": DAILY_COST_LIMIT_USD
                })

            # 지난 1시간 실패율 (role 컬럼 사용)
            cursor.execute("""
                SELECT
                    role,
                    COUNT(*) as calls,
                    SUM(CASE WHEN result = 'error' THEN 1 ELSE 0 END) as errors
                FROM agent_logs
                WHERE created_at >= DATEADD(hour, -1, GETDATE())
                GROUP BY role
                HAVING COUNT(*) >= 3
            """)

            for row in cursor.fetchall():
                if row.calls > 0:
                    failure_rate = row.errors / row.calls
                    if failure_rate > FAILURE_RATE_THRESHOLD:
                        alerts.append({
                            "id": f"failure_rate_{row.role}",
                            "type": "high_failure_rate",
                            "severity": "warning",
                            "message": f"{row.role} 에이전트 1시간 내 실패율 {failure_rate*100:.1f}%",
                            "value": failure_rate,
                            "threshold": FAILURE_RATE_THRESHOLD
                        })

            return jsonify({
                "alerts": alerts,
                "count": len(alerts),
                "checked_at": datetime.now().isoformat()
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route('/trends')
@login_required
def get_trends():
    """비용/호출 트렌드 (최근 7일)"""
    days = request.args.get('days', 7, type=int)
    days = min(days, 30)  # 최대 30일

    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    CAST(created_at AS DATE) as date,
                    COUNT(*) as calls,
                    SUM(cost_usd) as cost,
                    SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END) as successes,
                    AVG(latency_ms) as avg_latency
                FROM agent_logs
                WHERE created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY CAST(created_at AS DATE)
                ORDER BY date
            """, (-days,))

            daily = []
            for r in cursor.fetchall():
                calls = r.calls or 0
                successes = r.successes or 0
                daily.append({
                    "date": r.date.isoformat() if r.date else None,
                    "calls": calls,
                    "cost_usd": round(float(r.cost or 0), 4),
                    "success_rate_pct": round((successes / calls * 100) if calls > 0 else 0, 1),
                    "avg_latency_ms": int(r.avg_latency or 0)
                })

            # 전일 대비 변화율
            if len(daily) >= 2:
                recent = daily[-1]
                previous = daily[-2]

                cost_change = ((recent["cost_usd"] - previous["cost_usd"]) / previous["cost_usd"] * 100) if previous["cost_usd"] > 0 else 0
                calls_change = ((recent["calls"] - previous["calls"]) / previous["calls"] * 100) if previous["calls"] > 0 else 0
            else:
                cost_change = 0
                calls_change = 0

            return jsonify({
                "daily": daily,
                "day_over_day": {
                    "cost_change_pct": round(cost_change, 1),
                    "calls_change_pct": round(calls_change, 1)
                },
                "period_days": days
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route('/agent/<agent_role>')
@login_required
def agent_detail(agent_role: str):
    """특정 에이전트 상세 분석"""
    days = request.args.get('days', 7, type=int)

    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()

            # 기본 통계 (role 컬럼 사용)
            cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(cost_usd) as total_cost,
                    SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END) as successes,
                    AVG(latency_ms) as avg_latency,
                    MIN(latency_ms) as min_latency,
                    MAX(latency_ms) as max_latency,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens
                FROM agent_logs
                WHERE role = ?
                  AND created_at >= DATEADD(day, ?, GETDATE())
            """, (agent_role, -days))

            row = cursor.fetchone()
            if not row or not row.total_calls:
                return jsonify({"error": f"No data for agent: {agent_role}"}), 404

            total_calls = row.total_calls
            successes = row.successes or 0

            stats = {
                "agent_role": agent_role,
                "total_calls": total_calls,
                "total_cost_usd": round(float(row.total_cost or 0), 4),
                "success_rate_pct": round((successes / total_calls * 100), 1),
                "avg_latency_ms": int(row.avg_latency or 0),
                "min_latency_ms": int(row.min_latency or 0),
                "max_latency_ms": int(row.max_latency or 0),
                "total_input_tokens": row.input_tokens or 0,
                "total_output_tokens": row.output_tokens or 0,
            }

            # 일별 추이
            cursor.execute("""
                SELECT
                    CAST(created_at AS DATE) as date,
                    COUNT(*) as calls,
                    SUM(cost_usd) as cost
                FROM agent_logs
                WHERE role = ?
                  AND created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY CAST(created_at AS DATE)
                ORDER BY date
            """, (agent_role, -days))

            daily = []
            for r in cursor.fetchall():
                daily.append({
                    "date": r.date.isoformat() if r.date else None,
                    "calls": r.calls,
                    "cost_usd": round(float(r.cost or 0), 4)
                })

            # result_code별 에러 분포
            cursor.execute("""
                SELECT
                    result_code,
                    COUNT(*) as count
                FROM agent_logs
                WHERE role = ?
                  AND result = 'error'
                  AND result_code IS NOT NULL
                  AND created_at >= DATEADD(day, ?, GETDATE())
                GROUP BY result_code
                ORDER BY count DESC
            """, (agent_role, -days))

            error_codes = []
            for r in cursor.fetchall():
                error_codes.append({
                    "code": r.result_code,
                    "count": r.count
                })

            return jsonify({
                "stats": stats,
                "daily": daily,
                "error_codes": error_codes,
                "period_days": days
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@analytics_bp.route('/health')
def analytics_health():
    """Analytics API 상태 확인"""
    try:
        with db.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM agent_logs")
            count = cursor.fetchone()[0]

            return jsonify({
                "status": "ok",
                "agent_logs_count": count,
                "thresholds": {
                    "daily_cost_limit_usd": DAILY_COST_LIMIT_USD,
                    "failure_rate_threshold": FAILURE_RATE_THRESHOLD,
                    "latency_p95_threshold_sec": LATENCY_P95_THRESHOLD_SEC
                }
            })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
