"""Экспериментальное исследование: сравнение методов обнаружения аномалий и влияния групп признаков.

Запуск: python -m app.ml.experiments --out experiments/results

Протокол:
* данные генерируются симулятором (истинная разметка известна), несколько независимых seed;
* хронологическое разбиение 65% / 15% / 20% (обучение / валидация / тест), профили клиентов
  накапливаются последовательно, как в эксплуатации;
* неконтролируемые методы обучаются на обучающей части БЕЗ меток (в ней есть аномалии, как в реальных данных);
* параметры подбираются по PR-AUC на валидационной части;
* пороги: (а) «без меток» — квантиль 98% оценок обучающей части, (б) «по валидации» — порог максимального F1
  на валидационной части; итоговые метрики считаются на тестовой части.
"""
import argparse
import itertools
import json
import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.covariance import EllipticEnvelope
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

from app.domain.features import CONTEXT_FREE_FEATURES, FEATURE_GROUPS, FEATURE_NAMES
from app.ml.dataset import build_feature_frame, time_split
from app.ml.metrics import best_f1_threshold, evaluate
from app.simulation.generator import generate_transactions

log = logging.getLogger("experiments")

LABEL_FREE_QUANTILE = 0.98
UNSUPERVISED_SUBSAMPLE = {"lof": 15000, "ocsvm": 8000}


@dataclass
class Fitted:
    name: str
    supervised: bool
    score: Callable[[np.ndarray], np.ndarray]  # X -> оценки (больше = аномальнее)
    params: dict
    fit_seconds: float


def _pr_auc(y, s) -> float:
    return float(average_precision_score(y, s))


def _subsample(X: np.ndarray, size: int, seed: int) -> np.ndarray:
    if len(X) <= size:
        return X
    rng = np.random.default_rng(seed)
    return X[rng.choice(len(X), size=size, replace=False)]


# ---------------------------------------------------------------- модели
def fit_isolation_forest(Xtr, Xva, yva, seed, cols_name="IsolationForest", grid=None) -> Fitted:
    grid = grid or {"n_estimators": [100, 200, 400], "max_samples": [256, 512, 1024], "max_features": [0.6, 1.0]}
    t0 = time.perf_counter()
    best, best_params = -1.0, None
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid, combo))
        model = IsolationForest(random_state=seed, n_jobs=-1, **params).fit(Xtr)
        value = _pr_auc(yva, -model.score_samples(Xva))
        if value > best:
            best, best_params = value, params
    model = IsolationForest(random_state=seed, n_jobs=-1, **best_params).fit(Xtr)
    return Fitted(cols_name, False, lambda X: -model.score_samples(X), best_params, time.perf_counter() - t0)


def fit_fixed_isolation_forest(Xtr, seed, params, name) -> Fitted:
    t0 = time.perf_counter()
    model = IsolationForest(random_state=seed, n_jobs=-1, **params).fit(Xtr)
    return Fitted(name, False, lambda X: -model.score_samples(X), params, time.perf_counter() - t0)


def fit_lof(Xtr, Xva, yva, seed) -> Fitted:
    t0 = time.perf_counter()
    scaler = StandardScaler().fit(Xtr)
    sample = scaler.transform(_subsample(Xtr, UNSUPERVISED_SUBSAMPLE["lof"], seed))
    best, best_model, best_k = -1.0, None, None
    for k in (20, 50):
        model = LocalOutlierFactor(n_neighbors=k, novelty=True, n_jobs=-1).fit(sample)
        value = _pr_auc(yva, -model.score_samples(scaler.transform(Xva)))
        if value > best:
            best, best_model, best_k = value, model, k
    return Fitted("LOF", False, lambda X: -best_model.score_samples(scaler.transform(X)),
                  {"n_neighbors": best_k, "train_subsample": len(sample)}, time.perf_counter() - t0)


def fit_ocsvm(Xtr, Xva, yva, seed) -> Fitted:
    t0 = time.perf_counter()
    scaler = StandardScaler().fit(Xtr)
    sample = scaler.transform(_subsample(Xtr, UNSUPERVISED_SUBSAMPLE["ocsvm"], seed))
    best, best_model, best_nu = -1.0, None, None
    for nu in (0.01, 0.05):
        model = OneClassSVM(kernel="rbf", gamma="scale", nu=nu).fit(sample)
        value = _pr_auc(yva, -model.decision_function(scaler.transform(Xva)))
        if value > best:
            best, best_model, best_nu = value, model, nu
    return Fitted("One-Class SVM", False, lambda X: -best_model.decision_function(scaler.transform(X)),
                  {"nu": best_nu, "gamma": "scale", "train_subsample": len(sample)}, time.perf_counter() - t0)


def fit_elliptic(Xtr, seed) -> Fitted:
    t0 = time.perf_counter()
    scaler = StandardScaler().fit(Xtr)
    model = EllipticEnvelope(contamination=0.02, support_fraction=0.9, random_state=seed).fit(scaler.transform(Xtr))
    return Fitted("Elliptic Envelope", False, lambda X: -model.score_samples(scaler.transform(X)),
                  {"contamination": 0.02, "support_fraction": 0.9}, time.perf_counter() - t0)


def fit_zscore_rule(Xtr, columns) -> Fitted:
    """Правило-эталон: оценка = z-оценка суммы относительно профиля клиента, без обучения."""
    idx = columns.index("amount_zscore")
    return Fitted("Правило: z-оценка суммы", False, lambda X: X[:, idx], {}, 0.0)


def fit_logreg(Xtr, ytr, seed) -> Fitted:
    t0 = time.perf_counter()
    scaler = StandardScaler().fit(Xtr)
    model = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed).fit(scaler.transform(Xtr), ytr)
    return Fitted("Логистическая регрессия", True, lambda X: model.predict_proba(scaler.transform(X))[:, 1],
                  {"class_weight": "balanced"}, time.perf_counter() - t0)


def fit_xgboost(Xtr, ytr, Xva, yva, seed) -> Fitted:
    import xgboost as xgb

    t0 = time.perf_counter()
    pos = max(int(ytr.sum()), 1)
    params = {"n_estimators": 400, "learning_rate": 0.05, "max_depth": 5, "subsample": 0.8, "colsample_bytree": 0.8,
              "scale_pos_weight": float((len(ytr) - pos) / pos)}
    model = xgb.XGBClassifier(**params, random_state=seed, n_jobs=-1, eval_metric="aucpr", early_stopping_rounds=30)
    model.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    params["best_iteration"] = int(model.best_iteration)
    return Fitted("XGBoost", True, lambda X: model.predict_proba(X)[:, 1], params, time.perf_counter() - t0)


def fit_lightgbm(Xtr, ytr, Xva, yva, seed) -> Fitted:
    import lightgbm as lgb

    t0 = time.perf_counter()
    pos = max(int(ytr.sum()), 1)
    params = {"n_estimators": 400, "learning_rate": 0.05, "num_leaves": 31, "subsample": 0.8, "subsample_freq": 1,
              "colsample_bytree": 0.8, "scale_pos_weight": float((len(ytr) - pos) / pos)}
    model = lgb.LGBMClassifier(**params, random_state=seed, verbose=-1, n_jobs=-1)
    model.fit(Xtr, ytr, eval_set=[(Xva, yva)], callbacks=[lgb.early_stopping(30, verbose=False)])
    params["best_iteration"] = int(model.best_iteration_)
    return Fitted("LightGBM", True, lambda X: model.predict_proba(X)[:, 1], params, time.perf_counter() - t0)


# ---------------------------------------------------------------- оценка
def assess(fitted: Fitted, Xtr, Xva, yva, Xte, yte, test_types) -> dict:
    s_tr, s_va = fitted.score(Xtr), fitted.score(Xva)
    t0 = time.perf_counter()
    s_te = fitted.score(Xte)
    score_ms_per_1k = (time.perf_counter() - t0) / max(len(Xte), 1) * 1000 * 1000

    thr_val = best_f1_threshold(yva, s_va)
    result = {
        "roc_auc": float(roc_auc_score(yte, s_te)),
        "pr_auc": _pr_auc(yte, s_te),
        "val_threshold": evaluate(yte, s_te, thr_val),
        "fit_seconds": fitted.fit_seconds,
        "score_ms_per_1k": score_ms_per_1k,
        "params": fitted.params,
    }
    if not fitted.supervised:
        thr_free = float(np.quantile(s_tr, LABEL_FREE_QUANTILE))
        result["label_free_threshold"] = evaluate(yte, s_te, thr_free)
        flagged = s_te >= thr_free
        result["recall_by_type"] = {
            t: float(flagged[(test_types == t)].mean()) for t in sorted(set(test_types)) if t and (test_types == t).any()
        }
    result["_scores"] = s_te
    return result


def run_seed(seed: int, source: Callable[[int], pd.DataFrame], tuned_params: dict | None) -> dict:
    log.info("=== seed %s: подготовка данных", seed)
    df = source(seed)
    frame = build_feature_frame(df)
    train, val, test = time_split(frame)
    ytr, yva, yte = (f["is_anomaly"].values.astype(int) for f in (train, val, test))
    test_types = test["anomaly_type"].values
    info = {
        "rows": len(frame),
        "anomaly_share": float(frame["is_anomaly"].mean()),
        "train_rows": len(train), "val_rows": len(val), "test_rows": len(test),
        "test_anomalies": int(yte.sum()),
    }

    def matrices(columns):
        return train[columns].values, val[columns].values, test[columns].values

    Xtr, Xva, Xte = matrices(FEATURE_NAMES)
    models: dict[str, dict] = {}

    def run(fitted: Fitted, columns=None, matrices_=None):
        a, b, c = matrices_ or (Xtr, Xva, Xte)
        log.info("seed %s: %s (%.1f с)", seed, fitted.name, fitted.fit_seconds)
        models[fitted.name] = assess(fitted, a, b, yva, c, yte, test_types)

    if tuned_params is None:
        forest = fit_isolation_forest(Xtr, Xva, yva, seed)
        tuned_params = forest.params
    else:
        forest = fit_fixed_isolation_forest(Xtr, seed, tuned_params, "IsolationForest")
    run(forest)
    run(fit_lof(Xtr, Xva, yva, seed))
    run(fit_ocsvm(Xtr, Xva, yva, seed))
    try:
        run(fit_elliptic(Xtr, seed))
    except Exception as exc:  # вырожденная ковариация допустима для отдельных наборов признаков
        log.warning("Elliptic Envelope пропущен: %s", exc)
    run(fit_zscore_rule(Xtr, FEATURE_NAMES))
    run(fit_logreg(Xtr, ytr, seed))
    run(fit_xgboost(Xtr, ytr, Xva, yva, seed))
    run(fit_lightgbm(Xtr, ytr, Xva, yva, seed))

    # Влияние групп признаков: Isolation Forest с фиксированными параметрами.
    ablation: dict[str, dict] = {}

    def ablate(label: str, columns: list[str]):
        m = matrices(columns)
        fitted = fit_fixed_isolation_forest(m[0], seed, tuned_params, label)
        r = assess(fitted, m[0], m[1], yva, m[2], yte, test_types)
        ablation[label] = {"n_features": len(columns), "roc_auc": r["roc_auc"], "pr_auc": r["pr_auc"],
                           "label_free_threshold": r["label_free_threshold"]}

    ablate("Все признаки", FEATURE_NAMES)
    for group, cols in FEATURE_GROUPS.items():
        ablate(f"Без группы «{group}»", [c for c in FEATURE_NAMES if c not in cols])
    for group, cols in FEATURE_GROUPS.items():
        if group != "history":
            ablate(f"Только «{group}» + сумма/время", sorted(set(cols) | set(CONTEXT_FREE_FEATURES),
                                                            key=FEATURE_NAMES.index))
    ablate("Без профиля клиента (сумма и время)", CONTEXT_FREE_FEATURES)

    curves = {name: r["_scores"] for name, r in models.items()}
    for r in models.values():
        r.pop("_scores")
    return {"seed": seed, "info": info, "models": models, "ablation": ablation, "tuned_if_params": tuned_params,
            "_curves": (yte, curves)}


# ---------------------------------------------------------------- агрегация и отчёт
def _agg(values: list[float]) -> dict:
    return {"mean": float(np.mean(values)), "std": float(np.std(values)), "values": [float(v) for v in values]}


def aggregate(runs: list[dict]) -> dict:
    names = list(runs[0]["models"])
    models = {}
    for name in names:
        rows = [r["models"][name] for r in runs if name in r["models"]]
        entry = {
            "supervised": "label_free_threshold" not in rows[0],
            "roc_auc": _agg([r["roc_auc"] for r in rows]),
            "pr_auc": _agg([r["pr_auc"] for r in rows]),
            "fit_seconds": _agg([r["fit_seconds"] for r in rows]),
            "score_ms_per_1k": _agg([r["score_ms_per_1k"] for r in rows]),
            "params": rows[0]["params"],
        }
        for key in ("val_threshold", "label_free_threshold"):
            if key in rows[0]:
                entry[key] = {m: _agg([r[key][m] for r in rows]) for m in ("precision", "recall", "f1", "flagged_share")}
        if "recall_by_type" in rows[0]:
            types = rows[0]["recall_by_type"]
            entry["recall_by_type"] = {t: _agg([r["recall_by_type"].get(t, np.nan) for r in rows]) for t in types}
        models[name] = entry
    ablation = {}
    for label in runs[0]["ablation"]:
        rows = [r["ablation"][label] for r in runs]
        ablation[label] = {
            "n_features": rows[0]["n_features"],
            "roc_auc": _agg([r["roc_auc"] for r in rows]),
            "pr_auc": _agg([r["pr_auc"] for r in rows]),
            "f1": _agg([r["label_free_threshold"]["f1"] for r in rows]),
        }
    return {
        "seeds": [r["seed"] for r in runs],
        "datasets": [r["info"] for r in runs],
        "tuned_isolation_forest_params": runs[0]["tuned_if_params"],
        "models": models,
        "ablation": ablation,
    }


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _pm(a: dict, digits=3) -> str:
    return f"{a['mean']:.{digits}f} ± {a['std']:.{digits}f}"


def write_report(summary: dict, path: Path) -> None:
    d0 = summary["datasets"][0]
    lines = [
        "# Результаты экспериментов",
        "",
        f"Независимых наборов данных (seed): {len(summary['seeds'])} ({', '.join(map(str, summary['seeds']))}). "
        f"Размер набора: около {_thousands(d0['rows'])} транзакций, доля аномалий {d0['anomaly_share']:.2%}. "
        "Хронологическое разбиение 65/15/20. "
        "Значения: среднее ± стандартное отклонение по наборам, метрики на тестовой части.",
        "",
        f"Параметры Isolation Forest, подобранные по PR-AUC на валидации: `{json.dumps(summary['tuned_isolation_forest_params'])}`.",
        "",
        "## 1. Сравнение методов (порог по максимуму F1 на валидации)",
        "",
        "| Метод | Тип | Precision | Recall | F1 | ROC-AUC | PR-AUC |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, m in summary["models"].items():
        t = m["val_threshold"]
        lines.append(f"| {name} | {'с учителем' if m['supervised'] else 'без учителя'} | {_pm(t['precision'])} | "
                     f"{_pm(t['recall'])} | {_pm(t['f1'])} | {_pm(m['roc_auc'])} | {_pm(m['pr_auc'])} |")
    lines += [
        "",
        f"## 2. Неконтролируемые методы: порог без меток (квантиль {LABEL_FREE_QUANTILE:.0%} оценок обучающей части)",
        "",
        "| Метод | Precision | Recall | F1 | Доля помеченных |",
        "|---|---|---|---|---|",
    ]
    for name, m in summary["models"].items():
        if "label_free_threshold" in m:
            t = m["label_free_threshold"]
            lines.append(f"| {name} | {_pm(t['precision'])} | {_pm(t['recall'])} | {_pm(t['f1'])} | {_pm(t['flagged_share'])} |")
    if "IsolationForest" in summary["models"] and "recall_by_type" in summary["models"]["IsolationForest"]:
        lines += ["", "## 3. Полнота Isolation Forest по типам аномалий (порог без меток)", "",
                  "| Тип аномалии | Recall |", "|---|---|"]
        for t, v in summary["models"]["IsolationForest"]["recall_by_type"].items():
            lines.append(f"| {t} | {_pm(v)} |")
    lines += ["", "## 4. Влияние групп признаков (Isolation Forest, параметры фиксированы)", "",
              "| Набор признаков | Число признаков | ROC-AUC | PR-AUC | F1 (порог без меток) |", "|---|---|---|---|---|"]
    for label, a in summary["ablation"].items():
        lines.append(f"| {label} | {a['n_features']} | {_pm(a['roc_auc'])} | {_pm(a['pr_auc'])} | {_pm(a['f1'])} |")
    lines += ["", "## 5. Вычислительные затраты", "", "| Метод | Обучение, с | Оценка 1000 транзакций, мс |", "|---|---|---|"]
    for name, m in summary["models"].items():
        lines.append(f"| {name} | {_pm(m['fit_seconds'], 1)} | {_pm(m['score_ms_per_1k'], 1)} |")
    lines += [
        "",
        "Время обучения Isolation Forest на первом наборе включает перебор сетки параметров (18 вариантов).",
        "",
        "Графики: `pr_curves.png`, `roc_curves.png`, `ablation.png`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_plots(out: Path, curves: tuple, summary: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y, scores = curves
    for kind, filename, xlabel, ylabel in (
        ("pr", "pr_curves.png", "Recall", "Precision"),
        ("roc", "roc_curves.png", "False positive rate", "True positive rate"),
    ):
        fig, ax = plt.subplots(figsize=(7, 5))
        for name, s in scores.items():
            if kind == "pr":
                p, r, _ = precision_recall_curve(y, s)
                ax.plot(r, p, label=f"{name} (AP={average_precision_score(y, s):.2f})")
            else:
                fpr, tpr, _ = roc_curve(y, s)
                ax.plot(fpr, tpr, label=f"{name} (AUC={roc_auc_score(y, s):.2f})")
        if kind == "roc":
            ax.plot([0, 1], [0, 1], "k--", linewidth=0.8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title("Кривые " + ("precision-recall" if kind == "pr" else "ROC") + " (тест, seed %d)" % summary["seeds"][0])
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / filename, dpi=140)
        plt.close(fig)

    labels = list(summary["ablation"])
    values = [summary["ablation"][k]["pr_auc"]["mean"] for k in labels]
    errors = [summary["ablation"][k]["pr_auc"]["std"] for k in labels]
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(labels)), values, xerr=errors, color="#4C78A8")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("PR-AUC (тест)")
    ax.set_title("Влияние групп признаков на качество Isolation Forest")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "ablation.png", dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="experiments/results")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--clients", type=int, default=300)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--dataset", choices=["synthetic", "ibm"], default="synthetic")
    parser.add_argument("--ibm-path", help="CSV-файл IBM Credit Card Transactions")
    parser.add_argument("--ibm-user-fraction", type=float, default=0.05)
    parser.add_argument("--ibm-from-year", type=int, default=2010)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    warnings.filterwarnings("ignore", category=RuntimeWarning, module="sklearn.covariance")
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.dataset == "ibm":
        if not args.ibm_path:
            parser.error("для --dataset ibm нужен --ibm-path")
        from app.ml.ibm_loader import load_ibm

        # Разные seed дают разные выборки пользователей.
        def source(seed: int) -> pd.DataFrame:
            return load_ibm(args.ibm_path, args.ibm_user_fraction, args.ibm_from_year, seed)
    else:
        def source(seed: int) -> pd.DataFrame:
            return generate_transactions(args.clients, args.days, seed)

    runs, tuned = [], None
    for seed in args.seeds:
        run = run_seed(seed, source, tuned)
        tuned = run["tuned_if_params"]  # подбор выполняется на первом наборе, далее параметры фиксируются
        runs.append(run)
    summary = aggregate(runs)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(summary, out / "report.md")
    write_plots(out, runs[0]["_curves"], summary)
    log.info("Готово: %s", out.resolve())


if __name__ == "__main__":
    main()
