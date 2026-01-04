"""
Hattz Empire - WPCN API
와이코프 매매봇 백테스트/최적화 API 엔드포인트
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required

from ..services import executor
from ..services import background_tasks as bg

wpcn_bp = Blueprint('wpcn', __name__, url_prefix='/api/wpcn')


@wpcn_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    """WPCN 시스템 상태 확인"""
    result = executor.run_wpcn_status()
    return jsonify({
        "success": result.success,
        "data": result.output,
        "error": result.error
    })


@wpcn_bp.route('/symbols', methods=['GET'])
@login_required
def get_symbols():
    """지원 심볼 목록"""
    result = executor.run_wpcn_symbols()
    return jsonify({
        "success": result.success,
        "data": result.output,
        "error": result.error
    })


@wpcn_bp.route('/backtest', methods=['POST'])
@login_required
def run_backtest():
    """
    현물 백테스트 실행

    Request JSON:
        symbol: str (default: BTC-USDT)
        timeframe: str (default: 15m)
        days: int (default: 90)
        background: bool (default: false) - true면 백그라운드 실행
    """
    data = request.get_json() or {}
    symbol = data.get('symbol', 'BTC-USDT')
    timeframe = data.get('timeframe', '15m')
    days = data.get('days', 90)
    background = data.get('background', False)
    session_id = data.get('session_id', 'default')

    if background:
        # 백그라운드 실행
        task_id = bg.start_wpcn_backtest(session_id, symbol, timeframe, days)
        return jsonify({
            "success": True,
            "task_id": task_id,
            "message": f"백테스트가 백그라운드에서 시작되었습니다. Task ID: {task_id}"
        })
    else:
        # 동기 실행
        result = executor.run_wpcn_backtest(symbol, timeframe, days)
        return jsonify({
            "success": result.success,
            "data": result.output,
            "error": result.error
        })


@wpcn_bp.route('/optimize', methods=['POST'])
@login_required
def run_optimize():
    """
    파라미터 최적화 실행

    Request JSON:
        symbol: str (default: BTC-USDT)
        timeframe: str (default: 15m)
        optimizer: str (default: optuna) - random, optuna, bayesian, grid
        background: bool (default: true) - 최적화는 오래 걸리므로 기본 백그라운드
    """
    data = request.get_json() or {}
    symbol = data.get('symbol', 'BTC-USDT')
    timeframe = data.get('timeframe', '15m')
    optimizer = data.get('optimizer', 'optuna')
    background = data.get('background', True)  # 최적화는 기본 백그라운드
    session_id = data.get('session_id', 'default')

    if background:
        # 백그라운드 실행
        task_id = bg.start_wpcn_optimize(session_id, symbol, timeframe, optimizer)
        return jsonify({
            "success": True,
            "task_id": task_id,
            "message": f"최적화가 백그라운드에서 시작되었습니다. Task ID: {task_id}"
        })
    else:
        # 동기 실행 (주의: 오래 걸림)
        result = executor.run_wpcn_optimize(symbol, timeframe, optimizer)
        return jsonify({
            "success": result.success,
            "data": result.output,
            "error": result.error
        })


@wpcn_bp.route('/exec', methods=['POST'])
@login_required
def exec_command():
    """
    WPCN 명령어 직접 실행

    Request JSON:
        command: str - backtest, optimize, status, symbols, help
        args: str - 명령어 인자 (예: "BTC-USDT:15m:90")
    """
    data = request.get_json() or {}
    command = data.get('command', 'help')
    args = data.get('args', '')

    target = f"{command}:{args}" if args else command
    result = executor.execute_wpcn_command(target)

    return jsonify({
        "success": result.success,
        "data": result.output,
        "error": result.error,
        "action": result.action,
        "target": result.target
    })


@wpcn_bp.route('/help', methods=['GET'])
@login_required
def get_help():
    """WPCN 도움말"""
    help_text = """
=== WPCN API 도움말 ===

## 엔드포인트

### GET /api/wpcn/status
시스템 상태 확인 (Optuna 설치, 데이터 확인)

### GET /api/wpcn/symbols
지원 심볼 목록

### POST /api/wpcn/backtest
현물 백테스트 실행
- symbol: 심볼 (기본: BTC-USDT)
- timeframe: 타임프레임 (기본: 15m)
- days: 기간 (기본: 90)
- background: 백그라운드 실행 (기본: false)

### POST /api/wpcn/optimize
파라미터 최적화
- symbol: 심볼 (기본: BTC-USDT)
- timeframe: 타임프레임 (기본: 15m)
- optimizer: 최적화 방식 (기본: optuna)
  - random: 랜덤 서치
  - optuna: Optuna TPE
  - bayesian: 베이지안
  - grid: 그리드 서치
- background: 백그라운드 실행 (기본: true)

### POST /api/wpcn/exec
명령어 직접 실행
- command: 명령어 (backtest, optimize, status, symbols, help)
- args: 인자 (예: "BTC-USDT:15m:90")

## PM 에이전트용 EXEC 태그

[EXEC:wpcn:backtest:BTC-USDT:15m:90]
[EXEC:wpcn:optimize:BTC-USDT:15m:optuna]
[EXEC:wpcn:status]
[EXEC:wpcn:symbols]
[EXEC:wpcn:help]
"""
    return jsonify({
        "success": True,
        "data": help_text
    })
