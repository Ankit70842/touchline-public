"""Date-aligned football features. Prices never enter the feature matrix."""
import numpy as np
import pandas as pd

LEAGUES = {"GB1": "Premier League", "ES1": "La Liga", "L1": "Bundesliga", "IT1": "Serie A", "FR1": "Ligue 1"}
NUMERIC = ["age", "minutes", "appearances", "goals", "assists", "goals_per90", "assists_per90",
           "yellow_cards", "red_cards", "recent_minutes", "recent_goals", "recent_assists"]
CATEGORICAL = ["position", "league"]
FEATURES = NUMERIC + CATEGORICAL
STATS = ["minutes_played", "goals", "assists", "yellow_cards", "red_cards"]


def window_totals(matches, dates, days):
    """Exclude the valuation day and all future matches; include the left boundary."""
    match_dates = matches.date.to_numpy(dtype="datetime64[ns]")
    query = np.asarray(dates, dtype="datetime64[ns]")
    values = matches[STATS].fillna(0).to_numpy(float)
    prefix = np.vstack([np.zeros(len(STATS)), values.cumsum(axis=0)])
    right = np.searchsorted(match_dates, query, side="left")
    left = np.searchsorted(match_dates, query - np.timedelta64(days, "D"), side="left")
    return prefix[right] - prefix[left], right - left, right


def build_snapshots(players, appearances, valuations):
    players = players.copy()
    players["date_of_birth"] = pd.to_datetime(players.date_of_birth, errors="coerce")
    appearances = appearances.copy()
    appearances["date"] = pd.to_datetime(appearances.date)
    valuations = valuations.copy()
    valuations["date"] = pd.to_datetime(valuations.date)
    valuations = valuations[valuations.market_value_in_eur > 0]
    valuations["year"] = valuations.date.dt.year
    # One observation per player/year prevents frequently valued stars dominating.
    selected = valuations[valuations.date >= '2015-01-01'].sort_values("date").groupby(["player_id", "year"]).tail(1)
    profile = players.set_index("player_id")
    match_groups = {pid: rows.sort_values("date") for pid, rows in appearances.groupby("player_id")}
    rows = []
    for pid, targets in selected.groupby("player_id"):
        if pid not in profile.index or pid not in match_groups:
            continue
        person = profile.loc[pid]
        matches = match_groups[pid]
        targets = targets.sort_values("date")
        totals, counts, right = window_totals(matches, targets.date, 365)
        recent, _, _ = window_totals(matches, targets.date, 90)
        history = valuations[valuations.player_id == pid].sort_values("date")
        for i, target in enumerate(targets.itertuples()):
            if not right[i] or totals[i, 0] < 180:
                continue
            previous_matches = matches.iloc[:right[i]]
            domestic = previous_matches[previous_matches.competition_id.isin(LEAGUES)]
            if domestic.empty or (target.date - domestic.date.iloc[-1]).days > 180:
                continue
            # League and club come from the match at that time, not today's club.
            league = domestic.competition_id.iloc[-1]
            age = (target.date - person.date_of_birth).days / 365.25
            if pd.isna(age) or not 16 <= age <= 42:
                continue
            prior = history[history.date < target.date]
            minute, goals, assists, yellow, red = totals[i]
            rows.append(dict(
                player_id=int(pid), name=person["name"], date=target.date.date().isoformat(),
                year=target.year, age=round(age, 2), position=str(person.position), league=league,
                club_id=int(domestic.player_club_id.iloc[-1]),
                minutes=int(minute), appearances=int(counts[i]), goals=int(goals), assists=int(assists),
                yellow_cards=int(yellow), red_cards=int(red),
                recent_minutes=int(recent[i, 0]), recent_goals=int(recent[i, 1]), recent_assists=int(recent[i, 2]),
                goals_per90=round(goals * 90 / minute, 4), assists_per90=round(assists * 90 / minute, 4),
                actual_value=int(target.market_value_in_eur),
                previous_value=None if prior.empty else int(prior.market_value_in_eur.iloc[-1]),
                previous_value_date=None if prior.empty else prior.date.iloc[-1].date().isoformat(),
                previous_value_age_days=None if prior.empty else (target.date - prior.date.iloc[-1]).days,
                stats_through=previous_matches.date.iloc[-1].date().isoformat(),
            ))
    return pd.DataFrame(rows)
