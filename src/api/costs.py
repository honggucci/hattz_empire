"""
Hattz Empire - Cost Management API
비용 관리 및 분석 API
"""
from flask import request, jsonify, render_template
from flask_login import login_required

from . import cost_bp
from src.services import cost_tracker as ct


@cost_bp.route('/')
@login_required
def dashboard():
    """비용 대시보드 페이지"""
    return render_template('costs.html')


@cost_bp.route('/summary')
def get_summary():
    """비용 요약 조회"""
    days = request.args.get('days', 30, type=int)
    return jsonify(ct.get_summary(days))


@cost_bp.route('/daily')
def get_daily():
    """일별 비용 조회"""
    days = request.args.get('days', 7, type=int)
    return jsonify(ct.get_daily_costs(days))


@cost_bp.route('/models')
def get_models():
    """모델별 비용 분석"""
    days = request.args.get('days', 30, type=int)
    return jsonify(ct.get_model_breakdown(days))


@cost_bp.route('/models/stats')
def get_model_stats():
    """모델별 호출 통계 및 쏠림 분석"""
    days = request.args.get('days', 30, type=int)
    return jsonify(ct.get_model_call_stats(days))


@cost_bp.route('/agents')
def get_agents():
    """에이전트별 비용 분석"""
    days = request.args.get('days', 30, type=int)
    return jsonify(ct.get_agent_breakdown(days))


@cost_bp.route('/tiers')
def get_tiers():
    """티어별 비용 분석"""
    days = request.args.get('days', 30, type=int)
    return jsonify(ct.get_tier_breakdown(days))


@cost_bp.route('/hourly')
def get_hourly():
    """시간대별 호출 분포"""
    days = request.args.get('days', 7, type=int)
    return jsonify(ct.get_hourly_distribution(days))


@cost_bp.route('/trends')
def get_trends():
    """사용량 트렌드"""
    days = request.args.get('days', 14, type=int)
    return jsonify(ct.get_usage_trends(days))


@cost_bp.route('/efficiency')
def get_efficiency():
    """비용 효율성 지표"""
    days = request.args.get('days', 30, type=int)
    return jsonify(ct.get_efficiency_metrics(days))


@cost_bp.route('/all')
def get_all():
    """모든 비용 데이터 한번에 조회"""
    days = request.args.get('days', 30, type=int)

    return jsonify({
        "summary": ct.get_summary(days),
        "daily": ct.get_daily_costs(min(days, 14)),
        "models": ct.get_model_breakdown(days),
        "model_stats": ct.get_model_call_stats(days),
        "agents": ct.get_agent_breakdown(days),
        "tiers": ct.get_tier_breakdown(days),
        "hourly": ct.get_hourly_distribution(min(days, 7)),
        "trends": ct.get_usage_trends(min(days, 14)),
        "efficiency": ct.get_efficiency_metrics(days)
    })
