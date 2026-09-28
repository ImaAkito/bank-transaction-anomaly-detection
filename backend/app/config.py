"""Настройки приложения. Значения читаются из переменных окружения и файла .env."""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CURRENCY_RATES: dict[str, float] = {
    "RUB": 1.0,
    "USD": 90.0,
    "EUR": 100.0,
    "CNY": 12.5,
    "KZT": 0.2,
    "TRY": 3.0,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/app.db"

    model_path: str = "models/model.joblib"
    experiments_summary_path: str = "experiments/results/summary.json"

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
    base_currency: str = "RUB"
    currency_rates: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_CURRENCY_RATES))

    explain_shap: bool = True

    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: str = "*"
    worker_metrics_port: int = 9100


@lru_cache
def get_settings() -> Settings:
    return Settings()
