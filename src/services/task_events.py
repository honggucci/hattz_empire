"""
Hattz Empire - Task Events (SSE Broadcaster)

Cross-device progress synchronization via Server-Sent Events.
Allows mobile app to see progress bar when task runs on web.

Usage:
    from src.services.task_events import get_event_broadcaster, emit_progress

    # Emit progress event
    emit_progress(session_id, stage='thinking', agent='pm', progress=15)

    # Subscribe to events (in API endpoint)
    def sse_endpoint():
        broadcaster = get_event_broadcaster()
        for event in broadcaster.subscribe(session_id):
            yield f"data: {event}\n\n"
"""
import json
import threading
import queue
import time
from datetime import datetime
from typing import Optional, Generator
from dataclasses import dataclass, asdict


@dataclass
class ProgressEvent:
    """Progress event data"""
    event_type: str  # 'progress', 'stage_change', 'complete', 'error'
    session_id: str
    stage: str  # 'thinking', 'responding', 'delegating', 'calling', etc.
    agent: str
    progress: int  # 0-100
    sub_agent: Optional[str] = None
    total_agents: Optional[int] = None
    message: Optional[str] = None
    model_info: Optional[dict] = None
    timestamp: str = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class EventBroadcaster:
    """
    SSE Event Broadcaster

    Manages multiple subscribers and broadcasts events to all connected clients.
    Uses a queue-based system for reliable message delivery.
    """

    def __init__(self):
        self._subscribers: dict[str, list[queue.Queue]] = {}  # session_id -> list of queues
        self._lock = threading.Lock()
        self._cleanup_interval = 60  # seconds
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """Start background thread to cleanup stale subscribers"""
        def cleanup():
            while True:
                time.sleep(self._cleanup_interval)
                self._cleanup_stale_subscribers()

        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()

    def _cleanup_stale_subscribers(self):
        """Remove subscribers that haven't been active"""
        with self._lock:
            for session_id in list(self._subscribers.keys()):
                # Remove empty queues
                self._subscribers[session_id] = [
                    q for q in self._subscribers[session_id]
                    if not q.empty() or q.qsize() >= 0  # Keep all active queues
                ]
                # Remove session if no subscribers
                if not self._subscribers[session_id]:
                    del self._subscribers[session_id]

    def subscribe(self, session_id: str) -> Generator[str, None, None]:
        """
        Subscribe to events for a session.

        Yields:
            JSON string events for SSE
        """
        subscriber_queue = queue.Queue()

        with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            self._subscribers[session_id].append(subscriber_queue)

        try:
            # Send initial connection event
            initial_event = ProgressEvent(
                event_type='connected',
                session_id=session_id,
                stage='idle',
                agent='system',
                progress=0,
                message='Connected to progress stream'
            )
            yield initial_event.to_json()

            # Wait for events
            while True:
                try:
                    # Block with timeout to allow for client disconnection detection
                    event = subscriber_queue.get(timeout=30)
                    yield event

                    # Check for disconnect signal
                    if event == '__disconnect__':
                        break

                except queue.Empty:
                    # Send heartbeat to keep connection alive
                    heartbeat = ProgressEvent(
                        event_type='heartbeat',
                        session_id=session_id,
                        stage='idle',
                        agent='system',
                        progress=0
                    )
                    yield heartbeat.to_json()

        finally:
            # Cleanup on disconnect
            with self._lock:
                if session_id in self._subscribers:
                    try:
                        self._subscribers[session_id].remove(subscriber_queue)
                    except ValueError:
                        pass  # Already removed

    def broadcast(self, session_id: str, event: ProgressEvent):
        """
        Broadcast event to all subscribers of a session.

        Args:
            session_id: Target session
            event: Event to broadcast
        """
        with self._lock:
            if session_id not in self._subscribers:
                return

            event_json = event.to_json()
            for subscriber_queue in self._subscribers[session_id]:
                try:
                    subscriber_queue.put_nowait(event_json)
                except queue.Full:
                    pass  # Skip if queue is full

    def broadcast_all(self, event: ProgressEvent):
        """Broadcast to all sessions (for system-wide events)"""
        with self._lock:
            for session_id in self._subscribers:
                event_json = event.to_json()
                for subscriber_queue in self._subscribers[session_id]:
                    try:
                        subscriber_queue.put_nowait(event_json)
                    except queue.Full:
                        pass

    def disconnect(self, session_id: str):
        """Disconnect all subscribers for a session"""
        with self._lock:
            if session_id in self._subscribers:
                for subscriber_queue in self._subscribers[session_id]:
                    try:
                        subscriber_queue.put_nowait('__disconnect__')
                    except queue.Full:
                        pass
                del self._subscribers[session_id]

    def get_subscriber_count(self, session_id: str = None) -> int:
        """Get number of active subscribers"""
        with self._lock:
            if session_id:
                return len(self._subscribers.get(session_id, []))
            return sum(len(subs) for subs in self._subscribers.values())


# =============================================================================
# Singleton
# =============================================================================

_broadcaster: Optional[EventBroadcaster] = None


def get_event_broadcaster() -> EventBroadcaster:
    """Get singleton EventBroadcaster instance"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = EventBroadcaster()
    return _broadcaster


# =============================================================================
# Helper Functions
# =============================================================================

def emit_progress(
    session_id: str,
    stage: str,
    agent: str = 'pm',
    progress: int = 0,
    sub_agent: str = None,
    total_agents: int = None,
    message: str = None,
    model_info: dict = None
):
    """
    Emit a progress event (convenience function).

    Args:
        session_id: Session ID
        stage: Current stage (thinking, responding, delegating, calling, etc.)
        agent: Main agent (default: pm)
        progress: Progress percentage (0-100)
        sub_agent: Sub-agent being called (optional)
        total_agents: Total number of sub-agents (optional)
        message: Additional message (optional)
        model_info: Model information (optional)
    """
    event = ProgressEvent(
        event_type='progress',
        session_id=session_id,
        stage=stage,
        agent=agent,
        progress=progress,
        sub_agent=sub_agent,
        total_agents=total_agents,
        message=message,
        model_info=model_info
    )
    get_event_broadcaster().broadcast(session_id, event)


def emit_stage_change(session_id: str, stage: str, agent: str = 'pm', sub_agent: str = None):
    """Emit stage change event"""
    progress_map = {
        'thinking': 15,
        'responding': 30,
        'delegating': 35,
        'calling': 50,
        'sub_agent_done': 70,
        'summarizing': 80,
        'final_response': 90,
        'complete': 100,
        'error': 0
    }
    emit_progress(
        session_id=session_id,
        stage=stage,
        agent=agent,
        progress=progress_map.get(stage, 50),
        sub_agent=sub_agent
    )


def emit_complete(session_id: str, agent: str = 'pm', model_info: dict = None):
    """Emit completion event"""
    event = ProgressEvent(
        event_type='complete',
        session_id=session_id,
        stage='complete',
        agent=agent,
        progress=100,
        model_info=model_info
    )
    get_event_broadcaster().broadcast(session_id, event)


def emit_error(session_id: str, error_message: str, agent: str = 'pm'):
    """Emit error event"""
    event = ProgressEvent(
        event_type='error',
        session_id=session_id,
        stage='error',
        agent=agent,
        progress=0,
        message=error_message
    )
    get_event_broadcaster().broadcast(session_id, event)
