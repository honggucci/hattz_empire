"""
Hattz Empire - Events API (SSE)

Server-Sent Events endpoint for cross-device progress synchronization.
Mobile app can subscribe to this endpoint to see progress bar when task runs on web.

Usage:
    JavaScript:
        const eventSource = new EventSource('/api/events/progress?session_id=xxx');
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            updateProgressBar(data.stage, data.progress);
        };
"""
from flask import Response, request, jsonify

from . import events_bp
from src.services.task_events import get_event_broadcaster


@events_bp.route('/progress', methods=['GET'])
def progress_stream():
    """
    SSE endpoint for progress updates.

    Query params:
        session_id: Session ID to subscribe to (optional, subscribes to all if not provided)

    Returns:
        text/event-stream with progress events
    """
    session_id = request.args.get('session_id', 'global')

    def generate():
        broadcaster = get_event_broadcaster()
        for event in broadcaster.subscribe(session_id):
            yield f"data: {event}\n\n"

    response = Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Access-Control-Allow-Origin': '*'  # CORS for mobile
        }
    )
    return response


@events_bp.route('/status', methods=['GET'])
def events_status():
    """Get SSE subscriber status"""
    broadcaster = get_event_broadcaster()
    session_id = request.args.get('session_id')

    return jsonify({
        'total_subscribers': broadcaster.get_subscriber_count(),
        'session_subscribers': broadcaster.get_subscriber_count(session_id) if session_id else None
    })
