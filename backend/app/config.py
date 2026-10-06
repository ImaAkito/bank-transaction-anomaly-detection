"""Настройки приложения. Значения читаются из переменных окружения и файла .env."""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Курсы к белорусскому рублю (BYN) для пересчёта сумм в базовую валюту. Значения приблизительные
# и предназначены для демонстрации; в эксплуатации их следует загружать из актуального источника курсов.
DEFAULT_CURRENCY_RATES: dict[str, float] = {
    "BYN": 1.0,
    "USD": 3.0,
    "EUR": 3.4,
    "RUB": 0.037,
    "PLN": 0.8,
    "CNY": 0.42,
    "KZT": 0.006,
    "TRY": 0.09,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"
    db_migrate: bool = True  # True: схема создаётся миграциями Alembic, False: create_all (тесты)

    model_path: str = "models/model.joblib"
    experiments_summary_path: str = "experiments/results/summary.json"
    experiments_dir: str = "experiments"

    queue_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "transactions:incoming"
    queue_processing_name: str = "transactions:processing"
    queue_failed_name: str = "transactions:failed"
    events_channel: str = "transactions:results"

    # Пороги риска. Если не заданы, берутся из артефакта модели.
    risk_medium: float | None = None
    risk_high: float | None = None

    min_history_for_profile: int = Field(default=5, ge=1)
    base_currency: str = "BYN"
    currency_rates: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_CURRENCY_RATES))

    explain_shap: bool = True
    default_timezone: str = "UTC"

    # Аутентификация. При auth_enabled=False (разработка, тесты) все запросы выполняются от имени администратора.
    auth_enabled: bool = False
    auth_secret: str = "change-me-in-production"
    auth_token_ttl_minutes: int = 720
    admin_username: str = "admin"
    admin_password: str = "admin"
    ingest_api_key: str | None = None

    # Очередь: число партиций (порядок операций одного клиента сохраняется внутри партиции)
    queue_partitions: int = Field(default=1, ge=1, le=64)
    worker_index: int = 0
    worker_count: int = 1

    # Мониторинг дрейфа и автоматическое переобучение
    drift_window: int = 5000
    drift_psi_warning: float = 0.1
    drift_psi_alert: float = 0.25
    retrain_interval_hours: float = 24.0
    retrain_min_transactions: int = 2000
    retrain_max_transactions: int = 200000
    model_reload_check_seconds: float = 10.0

    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: str = "*"
    worker_metrics_port: int = 9100


@lru_cache
def get_settings() -> Settings:
    return Settings()
