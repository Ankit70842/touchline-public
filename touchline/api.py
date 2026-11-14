"""Small, local-first API serving the model and the scouting interface."""
from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import unicodedata
from typing import Literal
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator, ConfigDict
from touchline.features import FEATURES, LEAGUES
from touchline.valuation import predict_update

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Touchline", version="1.0.0")


@lru_cache
def data():
    # Publication mode never discovers/loads private local data or pickles.
    from touchline.demo import build_demo
    return build_demo()


class Stats(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: Literal['stats_only', 'valuation_aware'] = 'stats_only'
    age: float = Field(ge=16, le=42)
    position: str
    league: str
    minutes: int = Field(ge=180, le=10000)
    appearances: int = Field(ge=1, le=120)
    goals: int = Field(ge=0, le=150)
    assists: int = Field(ge=0, le=150)
    yellow_cards: int = Field(ge=0, le=60)
    red_cards: int = Field(ge=0, le=20)
    recent_minutes: int = Field(ge=0, le=4000)
    recent_goals: int = Field(ge=0, le=80)
    recent_assists: int = Field(ge=0, le=80)
    stats_as_of: date
    stats_through: date | None = None
    previous_value: float | None = Field(default=None, gt=0, le=10_000_000_000)
    previous_value_date: date | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.position not in {"Attack", "Midfield", "Defender", "Goalkeeper"} or self.league not in LEAGUES:
            raise ValueError("Select a supported position and league.")
        if self.stats_as_of > date.today():
            raise ValueError("Stats date cannot be in the future.")
        if (self.previous_value is None) != (self.previous_value_date is None):
            raise ValueError('Supply both previous value and its date, or neither for stats-only fallback.')
        if self.previous_value_date and self.previous_value_date >= self.stats_as_of:
            raise ValueError('Previous valuation must be strictly before the estimate date.')
        if self.stats_through and self.stats_through >= self.stats_as_of:
            raise ValueError('Performance data must be strictly before the estimate date.')
        if any(getattr(self, a) > getattr(self, b) for a, b in [
            ("recent_minutes", "minutes"), ("recent_goals", "goals"), ("recent_assists", "assists")]):
            raise ValueError("90-day totals cannot exceed 365-day totals.")
        if self.minutes > self.appearances * 130:
            raise ValueError("Minutes exceed a plausible total for the number of appearances.")
        if self.recent_minutes == 0 and (self.recent_goals or self.recent_assists):
            raise ValueError('Recent goals and assists require recent playing time.')
        return self


def matrix(stats):
    row = stats.model_dump()
    row["goals_per90"] = round(stats.goals * 90 / stats.minutes, 4)
    row["assists_per90"] = round(stats.assists * 90 / stats.minutes, 4)
    return pd.DataFrame([row])[FEATURES]


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


@app.get("/api/metadata")
def metadata():
    return data()["metadata"] | {'valuation_update': data()['evaluation'], 'pitchapi_pilot':pitchapi_status()}


@app.get('/api/sources/pitchapi')
def pitchapi_status():
    fallback = {'provider':'PitchAPI','pilot_league':'Premier League','status':'unavailable',
        'pilot_passed':False,'ready_for_training':False,'continuously_live':False,
        'estimate_source_changed':False,'other_leagues_enabled':False,
        'blockers':['Provider exports and learned models are not distributed; synthetic demo only.']}
    return fallback


@app.get('/api/sources/pitchapi/mappings')
def pitchapi_mappings(status: Literal['verified','needs_review','unmatched','ambiguous','conflict','out_of_scope'] | None = None):
    return []


def pitchapi_audit_file(name):
    if name=='review_queue.json':
        return []
    return {'status':'not_distributed','ready_for_training':False,'continuously_live':False,
            'network_requests_this_audit':0,'note':'Private research exports withheld pending redistribution rights.'}


@app.get('/api/sources/pitchapi/quality')
def pitchapi_quality():
    return pitchapi_audit_file('quality_readiness.json')


@app.get('/api/sources/pitchapi/review-queue')
def pitchapi_review_queue():
    return pitchapi_audit_file('review_queue.json')


@app.get('/api/sources/pitchapi/arsenal')
def pitchapi_arsenal():
    return pitchapi_audit_file('arsenal_pilot.json')


@app.get('/api/models')
def models():
    return {'default_api_model': 'stats_only', 'models': [
        {'id': 'stats_only', 'label': 'Stats-only estimate', 'uses_previous_value': False},
        {'id': 'valuation_aware', 'label': 'Valuation-aware update', 'uses_previous_value': True,
         'selected_method': data()['update_bundle']['selected']['name'],
         'description': 'Demo retains a previous value; illustrative stats rule fallback. No demo model evaluation.'}]}


@app.get("/api/players")
def players(q: str = Query("", max_length=100), league: str = "", position: str = ""):
    items = data()["players"]
    if q:
        query = normalize(q)
        items = [p for p in items if query in normalize(p["name"] + " " + p["club"])]
    if league:
        items = [p for p in items if p["league"] == league]
    if position:
        items = [p for p in items if p["position"] == position]
    return sorted(items, key=lambda p: p["actual_value"], reverse=True)


@app.get("/api/players/{player_id}")
def player(player_id: int):
    selected = next((p for p in data()["players"] if p["player_id"] == player_id), None)
    if selected is None:
        raise HTTPException(404, "Player not included in this snapshot.")
    peers = [p for p in data()["players"] if p["position"] == selected["position"] and p["player_id"] != player_id]
    # Transparent similarity: standardized age, minutes, goals/90, assists/90.
    fields = ["age", "minutes", "goals_per90", "assists_per90"]
    scales = [5, 1500, .4, .3]
    peers.sort(key=lambda p: sum(((p[f] - selected[f]) / s) ** 2 for f, s in zip(fields, scales)))
    return {**selected, "history": data()["history"].get(str(player_id), []), "peers": peers[:4]}


@app.post("/api/predict")
def predict(stats: Stats):
    bundle = data()["bundle"]
    def estimate(inputs):
        stats_value = max(0, float(np.expm1(bundle['model'].predict(matrix(inputs))[0])))
        radius, method = bundle['radius'], 'stats_only'
        value = stats_value
        if inputs.model == 'valuation_aware':
            update = data()['update_bundle']
            rows = pd.DataFrame([{'previous_value': inputs.previous_value,
                'previous_value_age_days': (inputs.stats_as_of-inputs.previous_value_date).days if inputs.previous_value_date else None}])
            values, fallback = predict_update(update['selected'], rows, [stats_value])
            value = float(values[0])
            method = 'stats_only_fallback' if fallback[0] else update['selected']['name']
            if not fallback[0]:
                radius = update['radius']
        return value, radius, method
    value, radius, method = estimate(stats)
    log_value = np.log1p(value)
    # One-feature-at-a-time sensitivities, not causal attributions.
    variants = [
        ("One year older", {"age": min(42, stats.age + 1)}),
        ("Five more goals", {"goals": min(150, stats.goals + 5)}),
        ("Five more assists", {"assists": min(150, stats.assists + 5)}),
    ]
    sensitivity = []
    for label, changes in variants:
        changed = Stats(**(stats.model_dump() | changes))
        changed_value, _, _ = estimate(changed)
        sensitivity.append({"label": label, "difference_eur": round(changed_value - value)})
    source_date = data()["metadata"]["source"]["appearances_through"]
    return {"predicted_value": round(value), 'model': stats.model, 'method': method,
            'synthetic_demo':True,'interval_calibrated':False,
            'previous_value': stats.previous_value,
            'previous_value_date': stats.previous_value_date.isoformat() if stats.previous_value_date else None,
            'previous_value_age_days': (stats.stats_as_of-stats.previous_value_date).days if stats.previous_value_date else None,
            'stats_through': stats.stats_through.isoformat() if stats.stats_through else None,
            "lower": max(0, round(float(np.expm1(log_value - radius)))),
            "upper": round(float(np.expm1(log_value + radius))),
            "stats_as_of": stats.stats_as_of.isoformat(), "sensitivities": sensitivity,
            "warning": "Synthetic demonstration with an illustrative arithmetic rule; not trained or evaluated. Bands are uncalibrated. No live data. " +
                ('Previous-value baseline retains the dated input price; changing performance does not change this estimate.' if method == 'previous_value' else
                 'Stats-only fallback used because no previous dated price was supplied.' if method == 'stats_only_fallback' else 'Performance-based estimate; no previous price is used.'),
            "source_training_stats_through": source_date}


@app.get("/")
def index():
    return FileResponse(ROOT / "web/index.html")


app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")
