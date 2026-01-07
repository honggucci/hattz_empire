"""
Hattz Empire - Prometheus Metrics Endpoint
에이전트 모니터링용 메트릭 수집

메트릭:
- hattz_jobs_total: 작업 처리량 (agent, status)
- hattz_llm_cost_total: LLM 비용 (agent, model)
- hattz_tokens_total: 토큰 사용량 (agent, type)
- hattz_circuit_breaker_trips_total: Circuit Breaker 발동
- hattz_review_verdicts_total: 리뷰 결과 분포
- hattz_job_duration_seconds: 작업 소요 시간
- hattz_embedding_queue_size: 임베딩 큐 크기
"""
from flask import Blueprint, Response
from functools import lru_cache
import time

metrics_bp = Blueprint('metrics', __name__, url_prefix='/metrics')

# 메트릭 저장소 (싱글톤)
_metrics = {
    'jobs_total': {},           # {(agent, status): count}
    'llm_cost_total': {},       # {(agent, model): cost}
    'tokens_total': {},         # {(agent, type): count}
    'circuit_breaker_trips': {},# {agent: count}
    'review_verdicts': {},      # {verdict: count}
    'job_durations': {},        # {agent: [durations]}
    'embedding_queue_size': 0,
}


def inc_jobs(agent: str, status: str):
    """작업 카운터 증가"""
    key = (agent, status)
    _metrics['jobs_total'][key] = _metrics['jobs_total'].get(key, 0) + 1


def inc_cost(agent: str, model: str, cost: float):
    """LLM 비용 추가"""
    key = (agent, model)
    _metrics['llm_cost_total'][key] = _metrics['llm_cost_total'].get(key, 0) + cost


def inc_tokens(agent: str, token_type: str, count: int):
    """토큰 카운터 증가"""
    key = (agent, token_type)
    _metrics['tokens_total'][key] = _metrics['tokens_total'].get(key, 0) + count


def inc_circuit_breaker(agent: str):
    """Circuit Breaker 발동 카운터"""
    _metrics['circuit_breaker_trips'][agent] = \
        _metrics['circuit_breaker_trips'].get(agent, 0) + 1


def inc_verdict(verdict: str):
    """리뷰 결과 카운터"""
    _metrics['review_verdicts'][verdict] = \
        _metrics['review_verdicts'].get(verdict, 0) + 1


def observe_job_duration(agent: str, duration: float):
    """작업 소요 시간 기록"""
    if agent not in _metrics['job_durations']:
        _metrics['job_durations'][agent] = []
    _metrics['job_durations'][agent].append(duration)
    # 최근 100개만 유지
    if len(_metrics['job_durations'][agent]) > 100:
        _metrics['job_durations'][agent] = _metrics['job_durations'][agent][-100:]


def set_embedding_queue_size(size: int):
    """임베딩 큐 크기 설정"""
    _metrics['embedding_queue_size'] = size


def _generate_prometheus_output() -> str:
    """Prometheus 텍스트 포맷 생성"""
    lines = []

    # hattz_jobs_total
    lines.append('# HELP hattz_jobs_total Total number of jobs processed')
    lines.append('# TYPE hattz_jobs_total counter')
    for (agent, status), count in _metrics['jobs_total'].items():
        lines.append(f'hattz_jobs_total{{agent="{agent}",status="{status}"}} {count}')

    # hattz_llm_cost_total
    lines.append('# HELP hattz_llm_cost_total Total LLM cost in USD')
    lines.append('# TYPE hattz_llm_cost_total counter')
    for (agent, model), cost in _metrics['llm_cost_total'].items():
        lines.append(f'hattz_llm_cost_total{{agent="{agent}",model="{model}"}} {cost:.6f}')

    # hattz_tokens_total
    lines.append('# HELP hattz_tokens_total Total tokens used')
    lines.append('# TYPE hattz_tokens_total counter')
    for (agent, token_type), count in _metrics['tokens_total'].items():
        lines.append(f'hattz_tokens_total{{agent="{agent}",type="{token_type}"}} {count}')

    # hattz_circuit_breaker_trips_total
    lines.append('# HELP hattz_circuit_breaker_trips_total Circuit breaker trip count')
    lines.append('# TYPE hattz_circuit_breaker_trips_total counter')
    for agent, count in _metrics['circuit_breaker_trips'].items():
        lines.append(f'hattz_circuit_breaker_trips_total{{agent="{agent}"}} {count}')

    # hattz_review_verdicts_total
    lines.append('# HELP hattz_review_verdicts_total Review verdict counts')
    lines.append('# TYPE hattz_review_verdicts_total counter')
    for verdict, count in _metrics['review_verdicts'].items():
        lines.append(f'hattz_review_verdicts_total{{verdict="{verdict}"}} {count}')

    # hattz_job_duration_seconds (평균)
    lines.append('# HELP hattz_job_duration_seconds Average job duration')
    lines.append('# TYPE hattz_job_duration_seconds gauge')
    for agent, durations in _metrics['job_durations'].items():
        if durations:
            avg = sum(durations) / len(durations)
            lines.append(f'hattz_job_duration_seconds{{agent="{agent}"}} {avg:.3f}')

    # hattz_embedding_queue_size
    lines.append('# HELP hattz_embedding_queue_size Current embedding queue size')
    lines.append('# TYPE hattz_embedding_queue_size gauge')
    lines.append(f'hattz_embedding_queue_size {_metrics["embedding_queue_size"]}')

    return '\n'.join(lines) + '\n'


@metrics_bp.route('')
def prometheus_metrics():
    """Prometheus 메트릭 엔드포인트"""
    # 임베딩 큐 크기 업데이트
    try:
        from src.services.embedding_queue import get_embedding_queue
        eq = get_embedding_queue()
        stats = eq.get_stats()
        set_embedding_queue_size(stats.get('queue_size', 0))
    except Exception:
        pass

    output = _generate_prometheus_output()
    return Response(output, mimetype='text/plain; charset=utf-8')


@metrics_bp.route('/json')
def json_metrics():
    """JSON 형식 메트릭 (디버깅용)"""
    from flask import jsonify
    return jsonify({
        'jobs_total': {f"{k[0]}:{k[1]}": v for k, v in _metrics['jobs_total'].items()},
        'llm_cost_total': {f"{k[0]}:{k[1]}": v for k, v in _metrics['llm_cost_total'].items()},
        'tokens_total': {f"{k[0]}:{k[1]}": v for k, v in _metrics['tokens_total'].items()},
        'circuit_breaker_trips': _metrics['circuit_breaker_trips'],
        'review_verdicts': _metrics['review_verdicts'],
        'job_durations_avg': {
            agent: sum(d)/len(d) if d else 0
            for agent, d in _metrics['job_durations'].items()
        },
        'embedding_queue_size': _metrics['embedding_queue_size'],
    })
