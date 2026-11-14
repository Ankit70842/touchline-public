"""Reproducible chronological training, calibration, evaluation, and app export."""
import json
import hashlib
import math
from pathlib import Path
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_log_error, r2_score
from sklearn.inspection import permutation_importance
from touchline.features import FEATURES, NUMERIC, CATEGORICAL, LEAGUES, build_snapshots

ROOT = Path(__file__).resolve().parents[1]


def metrics(actual, prediction):
    prediction = np.maximum(prediction, 0)
    return {"mae_eur": round(mean_absolute_error(actual, prediction)),
            "rmsle": round(math.sqrt(mean_squared_log_error(actual, prediction)), 4),
            "r2": round(r2_score(actual, prediction), 4),
            "within_factor_two": round(float(np.mean(np.abs(np.log((prediction + 1) / (np.asarray(actual) + 1))) <= np.log(2))), 4)}


def interval(log_prediction, radius):
    return np.maximum(0, np.expm1(log_prediction - radius)), np.expm1(log_prediction + radius)


def main():
    raw = ROOT / "data/raw"
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    players = pd.read_csv(raw / "players.csv")
    appearances = pd.read_csv(raw / "appearances.csv")
    valuations = pd.read_csv(raw / "player_valuations.csv")
    clubs = pd.read_csv(raw / "clubs.csv").set_index("club_id")["name"].to_dict()
    print("Building date-aligned annual player snapshots...", flush=True)
    snapshots = build_snapshots(players, appearances, valuations)
    if len(snapshots) < 1000:
        raise ValueError("Insufficient source data: need at least 1,000 valid snapshots.")
    test_year = int(snapshots.year.max())
    calibration_year = test_year - 1
    train = snapshots[snapshots.year < calibration_year]
    calibration = snapshots[snapshots.year == calibration_year]
    test = snapshots[snapshots.year == test_year]
    if min(len(train), len(calibration), len(test)) < 100:
        raise ValueError("Each chronological partition needs at least 100 observations.")
    preprocessor = ColumnTransformer([
        ("numeric", SimpleImputer(strategy="median"), NUMERIC),
        ("category", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
    ])
    model = make_pipeline(preprocessor, HistGradientBoostingRegressor(
        max_iter=220, max_leaf_nodes=23, l2_regularization=10, learning_rate=.07,
        early_stopping=False, random_state=42))
    model.fit(train[FEATURES], np.log1p(train.actual_value))
    calibration_residuals = np.abs(np.log1p(calibration.actual_value) - model.predict(calibration[FEATURES]))
    # Finite-sample split conformal quantile for a nominal 80% interval.
    quantile = min(1, math.ceil((len(calibration) + 1) * .8) / len(calibration))
    radius = float(np.quantile(calibration_residuals, quantile, method="higher"))
    test_log = model.predict(test[FEATURES])
    low, high = interval(test_log, radius)
    result = metrics(test.actual_value, np.expm1(test_log))
    median_baseline = metrics(test.actual_value, np.repeat(train.actual_value.median(), len(test)))
    persistence = test.dropna(subset=["previous_value"])
    previous_baseline = metrics(persistence.actual_value, persistence.previous_value)
    fair_model = metrics(persistence.actual_value, np.expm1(model.predict(persistence[FEATURES])))
    importance = permutation_importance(model, test[FEATURES], np.log1p(test.actual_value),
                                        scoring="neg_mean_absolute_error", n_repeats=3, random_state=42)
    source = {"name": "David Cariboo / Transfermarkt datasets (Kaggle copy)",
              "url": "https://www.kaggle.com/datasets/davidcariboo/player-scores",
              "upstream": "https://github.com/dcaribou/transfermarkt-datasets",
              "status_url": "https://github.com/dcaribou/transfermarkt-datasets/discussions/383",
              "status": "Historical snapshot; upstream updates paused. Not live data.",
              "appearances_through": str(appearances.date.max()),
              "valuations_through": str(valuations.date.max()),
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "files": {name: hashlib.sha256((raw / name).read_bytes()).hexdigest()
                        for name in ["players.csv", "appearances.csv", "player_valuations.csv", "clubs.csv"]}}
    metadata = {"model": "Histogram gradient boosting on log market value",
                "target": "Transfermarkt estimated market value in EUR, not transfer fees",
                "features": FEATURES, "leagues": LEAGUES, "source": source,
                "train": {"start": str(train.date.min()), "end": str(train.date.max()), "rows": len(train)},
                "calibration": {"year": calibration_year, "rows": len(calibration)},
                "test": {"year": test_year, "rows": len(test), **result},
                "baseline_median": median_baseline,
                "baseline_previous_value": {"rows": len(persistence), **previous_baseline},
                "model_on_previous_value_subset": fair_model,
                "interval": {"nominal_coverage": .8, "log_radius": radius,
                             "test_coverage": float(np.mean((test.actual_value >= low) & (test.actual_value <= high)))},
                "feature_importance": sorted([{"feature": name, "importance": round(float(value), 5)}
                    for name, value in zip(FEATURES, importance.importances_mean)],
                    key=lambda x: x["importance"], reverse=True),
                "limitations": [
                    "No live 2026/27 feed is connected; all dates are visible.",
                    "No xG, xA, tackles, injury history, wages, or historical contract terms in this model.",
                    "Position is taken from the downloaded player profile and can change over time.",
                    "Players can appear in multiple years: this evaluates later dates, not unseen-player generalization.",
                    "Snapshots require 180 minutes in the previous 365 days and a top-five-league appearance in the last 180 days.",
                    "Calibration is temporal; nominal 80% coverage is not guaranteed under market drift.",
                    "League is the latest top-five domestic appearance before valuation; international and cup stats are also included.",
                    "Errors can be large for elite players. Estimates reproduce source valuations, not objective economic worth."
                ]}
    joblib.dump({"model": model, "radius": radius}, output / "model.joblib", compress=3)
    latest = snapshots.sort_values("date").groupby("player_id").tail(1)
    latest = latest[latest.year == test_year].copy()
    logs = model.predict(latest[FEATURES])
    lower, upper = interval(logs, radius)
    latest["predicted_value"] = np.expm1(logs).round().astype(int)
    latest["lower"] = lower.round().astype(int)
    latest["upper"] = upper.round().astype(int)
    latest["club"] = latest.club_id.map(clubs).fillna("Unknown club")
    latest["league_name"] = latest.league.map(LEAGUES)
    # Keep up to ten years of source valuations, with source date retained.
    ids = set(latest.player_id)
    histories = valuations[valuations.player_id.isin(ids) & (valuations.date >= f"{test_year-10}-01-01")]
    history_map = {str(pid): rows.sort_values("date")[["date", "market_value_in_eur"]].to_dict("records")
                   for pid, rows in histories.groupby("player_id")}
    (output / "players.json").write_text(latest.to_json(orient="records"), encoding="utf-8")
    (output / "history.json").write_text(json.dumps(history_map), encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"players": len(latest), "test": metadata["test"], "baseline": previous_baseline,
                      "interval_test_coverage": metadata["interval"]["test_coverage"]}, indent=2))


if __name__ == "__main__":
    main()
