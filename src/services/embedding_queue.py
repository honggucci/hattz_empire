"""
Hattz Empire - Embedding Queue Service
비동기 임베딩 큐 시스템

메시지 저장 시 큐에 추가 → 백그라운드 워커가 처리
"""
import threading
import queue
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class EmbeddingTaskType(Enum):
    MESSAGE = "message"
    LOG = "log"
    FILE = "file"


@dataclass
class EmbeddingTask:
    """임베딩 작업 단위"""
    task_type: EmbeddingTaskType
    source_id: str
    content: str
    metadata: Dict[str, Any]
    project: str
    source: str = "web"
    retry_count: int = 0
    max_retries: int = 3


class EmbeddingQueue:
    """싱글톤 임베딩 큐 관리자"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._queue: queue.Queue[EmbeddingTask] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._stats = {
            "queued": 0,
            "processed": 0,
            "failed": 0,
            "retried": 0,
        }
        self._initialized = True
        logger.info("[EmbeddingQueue] Initialized")

    def start_worker(self):
        """워커 스레드 시작"""
        if self._running:
            logger.warning("[EmbeddingQueue] Worker already running")
            return

        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("[EmbeddingQueue] Worker started")

    def stop_worker(self):
        """워커 스레드 중지"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            logger.info("[EmbeddingQueue] Worker stopped")

    def enqueue(self, task: EmbeddingTask):
        """작업 큐에 추가"""
        self._queue.put(task)
        self._stats["queued"] += 1
        logger.debug(f"[EmbeddingQueue] Enqueued {task.task_type.value}:{task.source_id}")

    def enqueue_message(
        self,
        message_id: int,
        content: str,
        session_id: str,
        role: str,
        agent: str,
        project: str,
        source: str = "web"
    ):
        """메시지 임베딩 작업 추가 (편의 메서드)"""
        if not content or len(content) < 10:
            return  # 너무 짧은 내용은 스킵

        task = EmbeddingTask(
            task_type=EmbeddingTaskType.MESSAGE,
            source_id=str(message_id),
            content=content,
            metadata={
                "session_id": session_id,
                "role": role,
                "agent": agent,
            },
            project=project or "hattz_empire",
            source=source,
        )
        self.enqueue(task)

    def enqueue_log(
        self,
        log_id: str,
        content: str,
        from_agent: str,
        to_agent: str,
        msg_type: str,
        project: str,
        task_id: Optional[str] = None,
        source: str = "web"
    ):
        """로그 임베딩 작업 추가 (편의 메서드)"""
        if not content or len(content) < 10:
            return

        task = EmbeddingTask(
            task_type=EmbeddingTaskType.LOG,
            source_id=log_id,
            content=content,
            metadata={
                "from_agent": from_agent,
                "to_agent": to_agent,
                "msg_type": msg_type,
                "task_id": task_id,
            },
            project=project or "hattz_empire",
            source=source,
        )
        self.enqueue(task)

    def _worker_loop(self):
        """워커 메인 루프"""
        # RAG 임포트는 워커 내부에서 (순환 참조 방지)
        from src.services import rag

        logger.info("[EmbeddingQueue] Worker loop started")

        while self._running:
            try:
                # 0.5초 타임아웃으로 큐에서 작업 가져오기
                try:
                    task = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # 임베딩 처리
                try:
                    self._process_task(task, rag)
                    self._stats["processed"] += 1
                    logger.debug(f"[EmbeddingQueue] Processed {task.task_type.value}:{task.source_id}")
                except Exception as e:
                    logger.error(f"[EmbeddingQueue] Failed to process {task.source_id}: {e}")

                    # 재시도 로직
                    if task.retry_count < task.max_retries:
                        task.retry_count += 1
                        self._stats["retried"] += 1
                        self._queue.put(task)
                        logger.info(f"[EmbeddingQueue] Retry {task.retry_count}/{task.max_retries} for {task.source_id}")
                    else:
                        self._stats["failed"] += 1
                        logger.error(f"[EmbeddingQueue] Max retries exceeded for {task.source_id}")

                self._queue.task_done()

            except Exception as e:
                logger.error(f"[EmbeddingQueue] Worker error: {e}")
                time.sleep(1)  # 에러 시 잠시 대기

        logger.info("[EmbeddingQueue] Worker loop ended")

    def _process_task(self, task: EmbeddingTask, rag):
        """개별 작업 처리 (v2.5: agent 전달)"""
        rag.index_document(
            source_type=task.task_type.value,
            source_id=task.source_id,
            content=task.content,
            metadata=task.metadata,
            project=task.project,
            source=task.source,
            agent=task.metadata.get("agent") if task.metadata else None,
        )

    def get_stats(self) -> Dict[str, Any]:
        """큐 상태 조회"""
        return {
            **self._stats,
            "pending": self._queue.qsize(),
            "running": self._running,
        }

    def get_queue_size(self) -> int:
        """현재 대기 중인 작업 수"""
        return self._queue.qsize()

    def is_running(self) -> bool:
        """워커 실행 중 여부"""
        return self._running


# 전역 싱글톤 인스턴스
_embedding_queue: Optional[EmbeddingQueue] = None


def get_embedding_queue() -> EmbeddingQueue:
    """임베딩 큐 싱글톤 인스턴스 반환"""
    global _embedding_queue
    if _embedding_queue is None:
        _embedding_queue = EmbeddingQueue()
    return _embedding_queue


def init_embedding_worker():
    """앱 시작 시 워커 초기화"""
    eq = get_embedding_queue()
    if not eq.is_running():
        eq.start_worker()
    return eq


def shutdown_embedding_worker():
    """앱 종료 시 워커 정리"""
    eq = get_embedding_queue()
    eq.stop_worker()
