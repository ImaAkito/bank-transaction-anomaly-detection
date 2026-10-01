"""Очередь входящих транзакций: Redis (надёжная очередь с подтверждением) или в памяти процесса."""
import json
import logging
import queue
import threading
import zlib
from collections.abc import Callable
from typing import Any

from app.services import metrics

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]


class MemoryQueue:
    """Очередь внутри процесса API: для разработки и тестов без Redis."""

    def __init__(self, handler: Handler) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._handler = handler
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="memory-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def enqueue(self, payload: dict[str, Any]) -> None:
        self._queue.put(payload)

    def depth(self) -> int:
        return self._queue.qsize()

    def join(self) -> None:
        self._queue.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._handler(payload)
            except Exception:
                metrics.TX_ERRORS.labels(stage="queue").inc()
                log.exception("Ошибка обработки сообщения очереди: %s", payload.get("transaction_id"))
            finally:
                self._queue.task_done()


def partition_of(client_id: str, partitions: int) -> int:
    """Стабильный номер партиции клиента (не зависит от процесса, в отличие от встроенного hash)."""
    return zlib.crc32(str(client_id).encode()) % partitions


class RedisQueue:
    """Надёжная очередь на списках Redis с партиционированием по клиенту.

    Транзакции клиента всегда попадают в одну партицию, а каждая партиция обрабатывается ровно одним
    воркером (партиция k принадлежит воркеру k mod worker_count). Поэтому при нескольких воркерах операции
    одного клиента обрабатываются строго по порядку поступления, а разные клиенты — параллельно.

    Сообщение перекладывается из партиции в список «в обработке» (LMOVE/BLMOVE) и удаляется оттуда только
    после успешной обработки. Необработанные сообщения возвращаются в очередь при старте воркера,
    ошибочные попадают в список failed вместе с текстом ошибки.
    """

    def __init__(self, client, name: str, processing_name: str, failed_name: str,
                 partitions: int = 1, worker_index: int = 0, worker_count: int = 1) -> None:
        if worker_count < 1 or not 0 <= worker_index < worker_count:
            raise ValueError("Некорректные worker_index / worker_count")
        if partitions < worker_count:
            raise ValueError("Число партиций должно быть не меньше числа воркеров")
        self._client = client
        self.name = name
        self.processing_name = processing_name
        self.failed_name = failed_name
        self.partitions = partitions
        self.owned = [k for k in range(partitions) if k % worker_count == worker_index]

    def queue_key(self, partition: int) -> str:
        return self.name if self.partitions == 1 else f"{self.name}:{partition}"

    def processing_key(self, partition: int) -> str:
        return self.processing_name if self.partitions == 1 else f"{self.processing_name}:{partition}"

    def enqueue(self, payload: dict[str, Any]) -> None:
        partition = partition_of(payload.get("client_id", ""), self.partitions)
        self._client.lpush(self.queue_key(partition), json.dumps(payload, ensure_ascii=False, default=str))

    def depth(self) -> int:
        return int(sum(self._client.llen(self.queue_key(k)) for k in range(self.partitions)))

    def failed_depth(self) -> int:
        return int(self._client.llen(self.failed_name))

    def requeue_stale(self) -> int:
        """Возвращает в очередь сообщения своих партиций, не подтверждённые предыдущим экземпляром воркера."""
        moved = 0
        for k in self.owned:
            while self._client.lmove(self.processing_key(k), self.queue_key(k), "LEFT", "RIGHT") is not None:
                moved += 1
        if moved:
            log.warning("Возвращено в очередь необработанных сообщений: %s", moved)
        return moved

    def _handle(self, raw: str, partition: int, handler: Handler) -> None:
        try:
            handler(json.loads(raw))
        except Exception as exc:
            metrics.TX_ERRORS.labels(stage="queue").inc()
            log.exception("Ошибка обработки сообщения, оно перемещено в %s", self.failed_name)
            self._client.lpush(
                self.failed_name, json.dumps({"message": raw, "error": repr(exc)}, ensure_ascii=False)
            )
        finally:
            self._client.lrem(self.processing_key(partition), 1, raw)

    def consume_one(self, handler: Handler, timeout: int = 2) -> bool:
        """Обрабатывает одно сообщение. С одной партицией ждёт блокирующе, с несколькими — обходит их по кругу."""
        if len(self.owned) == 1:
            k = self.owned[0]
            raw = self._client.blmove(self.queue_key(k), self.processing_key(k), timeout, "RIGHT", "LEFT")
            if raw is None:
                return False
            self._handle(raw, k, handler)
            return True
        for k in self.owned:
            raw = self._client.lmove(self.queue_key(k), self.processing_key(k), "RIGHT", "LEFT")
            if raw is not None:
                self._handle(raw, k, handler)
                return True
        return False

    def consume_forever(self, handler: Handler, stop: threading.Event) -> None:
        self.requeue_stale()
        log.info("Партиции воркера: %s из %s", self.owned, self.partitions)
        while not stop.is_set():
            try:
                if not self.consume_one(handler) and len(self.owned) > 1:
                    stop.wait(0.05)
            except Exception:
                log.exception("Ошибка связи с Redis, повтор через 2 с")
                stop.wait(2)
