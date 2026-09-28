import json
import threading

import fakeredis

from app.services.queueing import RedisQueue


def make_queue():
    client = fakeredis.FakeRedis(decode_responses=True)
    return client, RedisQueue(client, "q", "q:processing", "q:failed")


def test_message_is_acknowledged_after_success():
    client, queue = make_queue()
    seen = []
    queue.enqueue({"transaction_id": "a"})
    queue.enqueue({"transaction_id": "b"})
    assert queue.depth() == 2
    assert queue.consume_one(seen.append, timeout=1) and queue.consume_one(seen.append, timeout=1)
    assert [m["transaction_id"] for m in seen] == ["a", "b"]  # порядок сохраняется
    assert queue.depth() == 0 and client.llen("q:processing") == 0
    assert queue.consume_one(seen.append, timeout=1) is False


def test_failed_message_goes_to_dead_letter_list():
    client, queue = make_queue()
    queue.enqueue({"transaction_id": "bad"})

    def boom(_):
        raise RuntimeError("сбой")

    assert queue.consume_one(boom, timeout=1)
    assert client.llen("q:processing") == 0 and queue.failed_depth() == 1
    record = json.loads(client.lindex("q:failed", 0))
    assert "сбой" in record["error"] and json.loads(record["message"])["transaction_id"] == "bad"


def test_stale_messages_are_requeued():
    client, queue = make_queue()
    client.lpush("q:processing", json.dumps({"transaction_id": "stale"}))
    assert queue.requeue_stale() == 1
    assert queue.depth() == 1 and client.llen("q:processing") == 0


def test_consume_forever_stops_on_event():
    _, queue = make_queue()
    stop = threading.Event()
    seen = []
    queue.enqueue({"transaction_id": "x"})
    thread = threading.Thread(target=queue.consume_forever, args=(seen.append, stop))
    thread.start()
    for _ in range(50):
        if seen:
            break
        threading.Event().wait(0.1)
    stop.set()
    thread.join(timeout=5)
    assert seen and not thread.is_alive()
