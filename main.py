"""GTA VI Trophy Rarity Forecast 01 - Entry (Pass 2)

Python 3.13, standard library only.
Forecasts trophy earn rates and quantiles at the target timestamp, handling both flat launch-night histories (with expected refresh dilution) and dynamic histories (with temporal trend extrapolation).
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

def clamp(x: float) -> float:
    return min(99.99, max(0.01, x))

def logit(pct: float) -> float:
    return math.log(clamp(pct) / (100 - clamp(pct)))

def inv_logit(lg: float) -> float:
    p = 100 / (1 + math.exp(-lg))
    return clamp(p)

def round4(x: float) -> float | int:
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value.is_integer() else value

def parse_iso(ts_str: str) -> float:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0

def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    history = case["history"]
    if not history:
        raise ValueError(f"{name} has no history")

    target_at = parse_iso(case["target"])
    horizon_minutes = case["horizon_minutes"]
    horizon_days = horizon_minutes / 1440.0
    horizon_seconds = horizon_minutes * 60.0

    last = history[-1]
    last_at = parse_iso(last["at"])
    last_players = last.get("players_tracked", 1000)

    # Check if history is flat (launch night pre-refresh)
    players_list = [h.get("players_tracked", 0) for h in history]
    is_flat = len(set(players_list)) <= 1

    trophies = case["trophies"]
    rows = []

    # If history has multiple distinct timestamps and changing player counts, fit trends
    times = [parse_iso(h["at"]) for h in history]
    
    # Calculate player growth slope if dynamic
    player_slope = 0.0
    if not is_flat and len(history) >= 2 and times[-1] > times[0]:
        dt_total = times[-1] - times[0]
        dp_total = players_list[-1] - players_list[0]
        if dt_total > 0:
            player_slope = dp_total / dt_total

    projected_players = max(100, last_players + player_slope * horizon_seconds)

    base_sigma = 0.9 if is_flat else 0.65
    spread = base_sigma * math.sqrt(horizon_days)

    for i, trophy in enumerate(trophies):
        rate = last["rates"][i]
        base_rate = rate if rate is not None else 0.1
        
        if is_flat:
            lg = logit(base_rate)
            tier = trophy.get("tier", "bronze")
            secret = trophy.get("secret", False)
            
            # Expect refresh dilution for launch-night flat histories
            adjustment = -0.15 if tier in ["platinum", "gold"] else -0.28
            if secret:
                adjustment -= 0.1
            lg += adjustment
        else:
            # Dynamic history: project holders and players
            rates_history = [h["rates"][i] if i < len(h.get("rates", [])) else None for h in history]
            valid_rates = [(t, r, p) for t, r, p in zip(times, rates_history, players_list) if r is not None and p > 0]
            
            if len(valid_rates) >= 2:
                # Estimate holders = rate * players
                holders_history = [r * p / 100.0 for _, r, p in valid_rates]
                t0, h0 = valid_rates[0][0], holders_history[0]
                t1, h1 = valid_rates[-1][0], holders_history[-1]
                
                holder_slope = 0.0
                if t1 > t0:
                    holder_slope = (h1 - h0) / (t1 - t0)
                
                projected_holders = max(0.0, (h1 + holder_slope * horizon_seconds))
                projected_rate = clamp((projected_holders * 100.0) / projected_players)
                lg = logit(projected_rate)
            else:
                lg = logit(base_rate)

        q_list = []
        for z in Z:
            q_lg = lg + z * spread
            q_pct = inv_logit(q_lg)
            q_list.append(round4(q_pct))

        # Ensure non-decreasing quantiles
        for j in range(1, len(q_list)):
            if q_list[j] < q_list[j-1]:
                q_list[j] = q_list[j-1]

        rows.append({"id": trophy["id"], "q": q_list})

    return {"trophies": rows}

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
