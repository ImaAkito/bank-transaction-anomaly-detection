import os
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="anomaly-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["MODEL_PATH"] = f"{_TMP}/model.joblib"
os.environ["QUEUE_BACKEND"] = "memory"
os.environ["DB_MIGRATE"] = "false"
os.environ["MODEL_RELOAD_CHECK_SECONDS"] = "0"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["LOG_JSON"] = "false"
os.environ["EXPERIMENTS_SUMMARY_PATH"] = f"{_TMP}/no-summary.json"


@pytest.fixture(scope="session")
def small_frame():
    """Небольшой набор данных для быстрых тестов: (сырые транзакции, матрица признаков)."""
    from app.ml.dataset import build_feature_frame
    from app.simulation.generator import generate_transactions

    df = generate_transactions(n_clients=60, days=40, seed=7)
    return df, build_feature_frame(df)


@pytest.fixture(scope="session")
def model_path(small_frame):
    from app.ml.model import save_bundle
    from app.ml.train import train_isolation_forest
    from app.ml.dataset import time_split

    _, frame = small_frame
    train, val, test = time_split(frame)
    bundle = train_isolation_forest(train, val, test, seed=1, tune=False)
    bundle.version = "test-model"
    path = Path(os.environ["MODEL_PATH"])
    save_bundle(bundle, path)
    return path


@pytest.fixture()
def client(model_path):
    from fastapi.testclient import TestClient

    from app import db
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    db.configure_engine(os.environ["DATABASE_URL"])
    db.Base.metadata.drop_all(db.get_engine())
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_client(model_path, monkeypatch):
    """Приложение с включённой аутентификацией: администратор admin/admin-pass, ключ приёма ingest-key."""
    from fastapi.testclient import TestClient

    from app import db
    from app.config import get_settings
    from app.main import app

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass")
    monkeypatch.setenv("INGEST_API_KEY", "ingest-key")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    get_settings.cache_clear()
    db.configure_engine(os.environ["DATABASE_URL"])
    db.Base.metadata.drop_all(db.get_engine())
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
