"""Метрики мониторинга (Prometheus)."""
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

TX_PROCESSED = Counter(
    "anomaly_transactions_processed_total", "Обработанные транзакции", ["risk_level"], registry=REGISTRY
)
TX_DUPLICATES = Counter(
    "anomaly_transactions_duplicates_total", "Повторно полученные транзакции", registry=REGISTRY
)
TX_ERRORS = Counter("anomaly_transactions_errors_total", "Ошибки обработки", ["stage"], registry=REGISTRY)
TX_LATENCY = Histogram(
    "anomaly_processing_seconds",
    "Время обработки транзакции",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge("anomaly_queue_depth", "Длина очереди входящих транзакций", registry=REGISTRY)
WS_CLIENTS = Gauge("anomaly_websocket_clients", "Подключения WebSocket", registry=REGISTRY)
DRIFT_MAX_PSI = Gauge("anomaly_drift_max_psi", "Максимальный PSI признаков относительно обучения", registry=REGISTRY)
