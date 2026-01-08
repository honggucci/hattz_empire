"""
Hattz Empire - API Blueprints
Flask Blueprint 기반 API 라우트
"""
from flask import Blueprint

# Blueprint 정의
auth_bp = Blueprint('auth', __name__, url_prefix='')
chat_bp = Blueprint('chat', __name__, url_prefix='/api')
session_bp = Blueprint('session', __name__, url_prefix='/api/sessions')
execute_bp = Blueprint('execute', __name__, url_prefix='/api/execute')
rag_bp = Blueprint('rag', __name__, url_prefix='/api/rag')
score_bp = Blueprint('score', __name__, url_prefix='/api')
router_bp = Blueprint('router', __name__, url_prefix='/api/router')
task_bp = Blueprint('task', __name__, url_prefix='/api')
breaker_bp = Blueprint('breaker', __name__, url_prefix='/api/breaker')
council_bp = Blueprint('council', __name__, url_prefix='/api/council')
health_bp = Blueprint('health', __name__, url_prefix='/api/health')
cost_bp = Blueprint('cost', __name__, url_prefix='/costs')
monitor_bp = Blueprint('monitor', __name__, url_prefix='/api/monitor')
events_bp = Blueprint('events', __name__, url_prefix='/api/events')
metrics_bp = Blueprint('metrics', __name__, url_prefix='/metrics')
analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


def register_blueprints(app):
    """모든 Blueprint를 앱에 등록"""
    from . import auth, chat, sessions, execute, rag_api, scores, router_api, tasks, breaker, council_api, health, costs, monitor, events, metrics, analytics
    from .wpcn import wpcn_bp  # WPCN API
    from .rules import rules_bp  # Session Rules API
    from .flow_quality import flow_bp  # v2.6.1 Flow Quality API

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(execute_bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(score_bp)
    app.register_blueprint(router_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(breaker_bp)
    app.register_blueprint(council_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(cost_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(events_bp)  # SSE Events
    app.register_blueprint(metrics_bp)  # Prometheus Metrics
    app.register_blueprint(wpcn_bp)  # WPCN API
    app.register_blueprint(rules_bp)  # Session Rules API
    app.register_blueprint(analytics_bp)  # v2.6 Analytics API
    app.register_blueprint(flow_bp)  # v2.6.1 Flow Quality API
