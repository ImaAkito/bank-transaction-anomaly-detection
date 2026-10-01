"""Полный объём IBM Credit Card Transactions (~24 млн операций) без загрузки файла в память целиком.

1. Файл читается частями; строки раскладываются по партициям по клиенту (все операции клиента в одной
   партиции) во временный каталог. Попутно собираются моменты времени для хронологических границ.
2. Границы обучение/валидация/тест — квантили 65% и 80% по времени всех операций.
3. Популяционные частоты считаются по операциям обучающего периода (без меток).
4. Признаки считаются параллельно по партициям (профили клиентов независимы) и хранятся в float32.
5. Чтобы выборка помещалась в память, в обучающем и валидационном периодах сохраняются все мошеннические
   операции и доля negative_rate обычных; тестовый период сохраняется полностью, метрики на тесте честные.
   Прореживание выполняется после расчёта признаков, поэтому профили клиентов строятся по всем операциям.
"""
import hashlib
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from app.domain.features import FEATURE_NAMES, fit_population
from app.ml.ibm_loader import iter_ibm

log = logging.getLogger(__name__)

TRAIN_Q, VAL_Q = 0.65, 0.80


def _ns(series: pd.Series) -> np.ndarray:
    """Моменты времени в наносекундах (в pandas 3 единица хранения может быть иной, поэтому явно)."""
    return pd.to_datetime(series, utc=True).dt.as_unit("ns").astype("int64").to_numpy()


def _keep_hash(transaction_ids: pd.Series, rate: float) -> np.ndarray:
    """Детерминированная выборка по идентификатору операции."""
    threshold = int(rate * 10_000)
    return np.array([int(hashlib.md5(t.encode()).hexdigest()[:8], 16) % 10_000 < threshold for t in transaction_ids])


def partition_file(path: str | Path, workdir: str | Path, parts: int, user_fraction: float = 1.0,
                   from_year: int = 0, seed: int = 42, chunksize: int = 1_000_000) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for old in workdir.glob("part_*.csv"):
        old.unlink()
    stamps: list[np.ndarray] = []
    rows = dropped = frauds = 0
    for chunk, refunds in iter_ibm(path, user_fraction, from_year, seed, chunksize):
        dropped += refunds
        if chunk.empty:
            continue
        rows += len(chunk)
        frauds += int(chunk["is_anomaly"].sum())
        stamps.append(_ns(chunk["timestamp"]))
        part_of = chunk["client_id"].map(lambda c: int(hashlib.md5(c.encode()).hexdigest()[:8], 16) % parts)
        for k, group in chunk.groupby(part_of):
            target = workdir / f"part_{k:03d}.csv"
            group.to_csv(target, mode="a", header=not target.exists(), index=False)
        log.info("Разложено строк: %s", rows)
    all_stamps = np.concatenate(stamps) if stamps else np.array([], dtype="int64")
    train_cut, val_cut = (np.quantile(all_stamps, [TRAIN_Q, VAL_Q]).astype("int64") if len(all_stamps) else (0, 0))
    return {"rows": rows, "frauds": frauds, "dropped_refunds": dropped,
            "train_cut": int(train_cut), "val_cut": int(val_cut), "parts": parts}


def _read_part(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"client_id": str, "recipient_id": str, "recipient_category": str,
                                  "anomaly_type": str}, keep_default_na=False)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["is_anomaly"] = df["is_anomaly"].astype(str).str.lower().eq("true")
    df["anomaly_type"] = df["anomaly_type"].fillna("")
    return df


def population_from_parts(workdir: str | Path, train_cut: int) -> dict:
    total: dict = {"n": 0, "categories": {}, "channels": {}, "recipient_categories": {}, "recipient_categories_n": 0}
    for path in sorted(Path(workdir).glob("part_*.csv")):
        df = _read_part(path)
        train = df[_ns(df["timestamp"]) < train_cut]
        pop = fit_population(train)
        total["n"] += pop["n"]
        total["recipient_categories_n"] += pop["recipient_categories_n"]
        for key in ("categories", "channels", "recipient_categories"):
            for value, count in pop[key].items():
                total[key][value] = total[key].get(value, 0) + count
    return total


def _features_for_part(args) -> pd.DataFrame:
    path, population, val_cut, negative_rate = args
    from app.ml.dataset import build_feature_frame

    df = _read_part(Path(path))
    stem = Path(path).stem
    df.insert(0, "transaction_id", [f"{stem}-{i}" for i in range(len(df))])
    frame = build_feature_frame(df, population=population)
    before_test = _ns(frame["timestamp"]) < val_cut
    if negative_rate < 1.0:
        keep = frame["is_anomaly"].to_numpy() | ~before_test | _keep_hash(frame["transaction_id"], negative_rate)
        frame = frame[keep]
    frame[FEATURE_NAMES] = frame[FEATURE_NAMES].astype("float32")
    return frame


def build_large_frame(path: str | Path, workdir: str | Path, parts: int = 32, workers: int | None = None,
                      negative_rate: float = 0.2, user_fraction: float = 1.0, from_year: int = 0,
                      seed: int = 42) -> tuple[pd.DataFrame, dict]:
    info = partition_file(path, workdir, parts, user_fraction, from_year, seed)
    log.info("Строк: %s, мошеннических: %s; расчёт популяционных частот", info["rows"], info["frauds"])
    population = population_from_parts(workdir, info["train_cut"])
    files = sorted(Path(workdir).glob("part_*.csv"))
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    log.info("Признаки: %s партиций, %s процессов, доля обычных операций в обучении %.2f", len(files), workers, negative_rate)
    tasks = [(str(f), population, info["val_cut"], negative_rate) for f in files]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        frames = list(pool.map(_features_for_part, tasks))
    frame = pd.concat(frames, ignore_index=True).sort_values("timestamp", kind="stable").reset_index(drop=True)
    info.update({"population": population, "negative_rate": negative_rate, "kept_rows": len(frame)})
    return frame, info


def split_by_cutoffs(frame: pd.DataFrame, info: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stamps = _ns(frame["timestamp"])
    train = frame[stamps < info["train_cut"]].copy()
    val = frame[(stamps >= info["train_cut"]) & (stamps < info["val_cut"])].copy()
    test = frame[stamps >= info["val_cut"]].copy()
    return train, val, test
