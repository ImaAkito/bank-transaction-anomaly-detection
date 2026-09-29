"""Диагностика набора данных: где в данных лежит сигнал и насколько он устойчив во времени.

Запуск: python -m app.ml.diagnostics --dataset ibm --ibm-path файл.csv --out experiments/diagnostics_ibm.md

Отчёт содержит:
1. долю аномалий по годам, каналам, категориям и признаку «получатель в новом регионе/онлайн»;
2. концентрацию аномалий по клиентам;
3. одномерный ROC-AUC каждого признака на обучающей и тестовой частях (положительное значение: больший
   признак означает большую вероятность аномалии). Признаки, у которых знак или величина сильно различаются,
   нестабильны во времени, и обучение с учителем на них даёт дрейф.
"""
import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from app.domain.features import FEATURE_GROUPS, FEATURE_NAMES
from app.ml.dataset import build_feature_frame, time_split
from app.simulation.generator import generate_transactions

log = logging.getLogger("diagnostics")


def _md_table(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    sep = "|" + "|".join("---" for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(map(str, r)) + " |" for r in frame.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def rate_table(df: pd.DataFrame, by: pd.Series, name: str, top: int = 15) -> pd.DataFrame:
    grouped = df.groupby(by)["is_anomaly"].agg(["size", "sum"])
    grouped["rate, %"] = (grouped["sum"] / grouped["size"] * 100).round(3)
    grouped = grouped.sort_values("sum", ascending=False).head(top).reset_index()
    grouped.columns = [name, "операций", "аномалий", "доля, %"]
    return grouped


def univariate_auc(train: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    group_of = {f: g for g, cols in FEATURE_GROUPS.items() for f in cols}
    rows = []
    for name in FEATURE_NAMES:
        aucs = []
        for part in (train, test):
            y = part["is_anomaly"].values
            aucs.append(roc_auc_score(y, part[name].values) if 0 < y.sum() < len(y) and part[name].nunique() > 1 else np.nan)
        rows.append({"признак": name, "группа": group_of[name], "AUC train": round(aucs[0], 3), "AUC test": round(aucs[1], 3),
                     "устойчив": "н/д" if np.isnan(aucs[0] * aucs[1]) else ("да" if (aucs[0] - 0.5) * (aucs[1] - 0.5) > 0 else "НЕТ (знак меняется)")})
    result = pd.DataFrame(rows)
    result["сила"] = (result["AUC test"] - 0.5).abs()
    return result.sort_values("сила", ascending=False).drop(columns="сила")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", choices=["synthetic", "ibm"], default="ibm")
    parser.add_argument("--ibm-path")
    parser.add_argument("--ibm-user-fraction", type=float, default=0.05)
    parser.add_argument("--ibm-from-year", type=int, default=2010)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="experiments/diagnostics.md")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.dataset == "ibm":
        if not args.ibm_path:
            parser.error("для --dataset ibm нужен --ibm-path")
        from app.ml.ibm_loader import load_ibm

        df = load_ibm(args.ibm_path, args.ibm_user_fraction, args.ibm_from_year, args.seed)
    else:
        df = generate_transactions(300, 60, args.seed)
    log.info("Операций: %s, аномалий: %s", len(df), int(df["is_anomaly"].sum()))
    frame = build_feature_frame(df)
    train, val, test = time_split(frame)

    lines = ["# Диагностика набора данных", "",
             f"Операций: {len(df):,}; аномалий: {int(df['is_anomaly'].sum())} ({df['is_anomaly'].mean():.3%}); "
             f"клиентов: {df['client_id'].nunique()}.".replace(",", " "), "",
             "## Доля аномалий по частям хронологического разбиения", ""]
    lines.append(_md_table(pd.DataFrame({
        "часть": ["обучение", "валидация", "тест"],
        "операций": [len(p) for p in (train, val, test)],
        "аномалий": [int(p["is_anomaly"].sum()) for p in (train, val, test)],
        "доля, %": [round(p["is_anomaly"].mean() * 100, 3) for p in (train, val, test)],
        "период": [f"{p['timestamp'].min():%Y-%m-%d} — {p['timestamp'].max():%Y-%m-%d}" for p in (train, val, test)],
    })))
    stamp = pd.to_datetime(df["timestamp"], utc=True)
    lines += ["", "## По годам", "", _md_table(rate_table(df, stamp.dt.year, "год", 40).sort_values("год")),
              "", "## По каналам", "", _md_table(rate_table(df, df["channel"], "канал")),
              "", "## По категориям (топ по числу аномалий)", "", _md_table(rate_table(df, df["category"], "категория")),
              "", "## По региону получателя (топ)", "", _md_table(rate_table(df, df["recipient_category"], "регион")),
              ]
    per_client = df.groupby("client_id")["is_anomaly"].sum().sort_values(ascending=False)
    total = max(int(per_client.sum()), 1)
    lines += ["", "## Концентрация по клиентам", "",
              f"Клиентов с аномалиями: {int((per_client > 0).sum())} из {len(per_client)}; "
              f"на 10% клиентов с наибольшим числом аномалий приходится "
              f"{per_client.head(max(len(per_client) // 10, 1)).sum() / total:.1%} всех аномалий.", ""]
    normal_amount = df.loc[~df["is_anomaly"], "amount"].median()
    fraud_amount = df.loc[df["is_anomaly"], "amount"].median() if df["is_anomaly"].any() else float("nan")
    lines += [f"Медианная сумма: обычные {normal_amount:.2f}, аномальные {fraud_amount:.2f}.", "",
              "## Одномерный ROC-AUC признаков (0,5 — нет сигнала)", "", _md_table(univariate_auc(train, test)), ""]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("Отчёт: %s", out.resolve())


if __name__ == "__main__":
    main()
