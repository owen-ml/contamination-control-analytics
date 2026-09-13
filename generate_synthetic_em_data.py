"""
generate_synthetic_em_data.py

Generates a realistic-looking (but entirely synthetic) Environmental
Monitoring dataset for a multi-room aseptic facility, and loads it into a
SQLite database matching schema.sql.

This file is provided complete and runnable. Read it end to end anyway --
the three contamination "mechanism" functions (glove_breach, mechanical_
friction, hvac_drift) are lifted directly from the Methods section of your
own paper, so this dataset can later be reused, unchanged, as the training
data for Module 2's shapelet classifier and Bayesian localization engine.

Usage:
    pip install numpy pandas --break-system-packages
    python generate_synthetic_em_data.py

Outputs:
    em_readings.csv   -- flat file, one row per reading
    em_data.db        -- SQLite database matching schema.sql
"""

import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

rng = np.random.default_rng(seed=42)  # reproducible, same seed convention as your paper

# ----------------------------------------------------------------------------
# 1. Facility layout
# ----------------------------------------------------------------------------
ROOMS = [
    # (room_id, room_name, iso_grade, area_type)
    (1, "Fill Suite 1", "A", "Fill Line"),
    (2, "Fill Suite 1 Background", "B", "Fill Line Background"),
    (3, "Compounding Room", "C", "Compounding"),
    (4, "Gowning Room", "D", "Gowning"),
]

# Each location gets an (x, y) position for future Module 2 spatial work.
LOCATIONS = [
    # (location_id, room_id, location_name, sample_type, x, y)
    (1, 1, "Sensor 1 - Fill Needle", "nonviable_particle", 0.0, 0.0),
    (2, 1, "Sensor 2 - Stopper Bowl", "nonviable_particle", 1.5, 0.0),
    (3, 1, "Sensor 3 - Capping Head", "nonviable_particle", 3.0, 0.0),
    (4, 2, "Sensor 4 - Background Grille", "nonviable_particle", 0.0, 2.0),
    (5, 3, "Sensor 5 - Compounding Vessel", "nonviable_particle", 5.0, 2.0),
    (6, 4, "Sensor 6 - Gowning Bench", "nonviable_particle", 5.0, 4.0),
    (7, 1, "Viable Air - Fill Line", "viable_air", 1.0, 0.5),
    (8, 3, "Viable Air - Compounding", "viable_air", 5.0, 1.5),
]

# Baseline Poisson rate (particles/interval) by ISO grade -- lower grade
# letter = tighter environment = lower baseline count.
BASELINE_LAMBDA = {"A": 1.2, "B": 2.0, "C": 4.5, "D": 9.0}

# Regulatory alert/action limits by grade, nonviable 0.5um particle counts
# (illustrative, simplified from ISO 14644-1 style tables -- NOT to be used
# as actual validated limits for a real site).
LIMITS = {
    "A": {"alert": 15, "action": 20},
    "B": {"alert": 25, "action": 35},
    "C": {"alert": 50, "action": 70},
    "D": {"alert": 90, "action": 120},
}

VIABLE_LIMITS = {"A": {"alert": 1, "action": 3}, "C": {"alert": 10, "action": 25}}

N_DAYS = 180
SAMPLES_PER_DAY = 4  # every 6 hours, per nonviable location
EVENT_STEPS = 60      # length of an injected excursion event, in sample steps
N_EVENTS = 90          # total injected excursion events across the whole run


# ----------------------------------------------------------------------------
# 2. Contamination mechanism functions (from the paper's Methodology section)
# ----------------------------------------------------------------------------
def glove_breach(t: np.ndarray) -> np.ndarray:
    """Sharp-onset, exponentially decaying spike (aerosol dispersal)."""
    return 18 * np.exp(-0.10 * t)


def mechanical_friction(t: np.ndarray) -> np.ndarray:
    """Periodic dual-frequency oscillation (equipment vibration)."""
    return 6 + 4 * np.sin(2 * np.pi * t / 8) + 2 * np.sin(2 * np.pi * t / 4)


def hvac_drift(t: np.ndarray) -> np.ndarray:
    """Gradual, monotonic baseline ramp (filter degradation / airflow loss)."""
    return 0.20 * t


MECHANISMS = {
    "glove_breach": glove_breach,
    "mechanical_friction": mechanical_friction,
    "hvac_drift": hvac_drift,
}


# ----------------------------------------------------------------------------
# 3. Generate the reading stream
# ----------------------------------------------------------------------------
def build_nonviable_readings():
    rows = []
    reading_id = 1
    nonviable_locations = [loc for loc in LOCATIONS if loc[3] == "nonviable_particle"]
    room_lookup = {r[0]: r for r in ROOMS}

    start = datetime(2026, 1, 1)
    timestamps = [start + timedelta(hours=6 * i) for i in range(N_DAYS * SAMPLES_PER_DAY)]

    # baseline series for every location, before any events are injected
    series = {}
    for loc in nonviable_locations:
        grade = room_lookup[loc[1]][2]
        lam = BASELINE_LAMBDA[grade]
        series[loc[0]] = rng.poisson(lam=lam, size=len(timestamps)).astype(float)

    # inject N_EVENTS random excursion events, each affecting one "source"
    # location strongly and neighboring locations more weakly (distance decay,
    # same exponential-decay weighting function used in the paper)
    event_labels = {loc[0]: ["none"] * len(timestamps) for loc in nonviable_locations}
    mechanism_names = list(MECHANISMS.keys())

    for _ in range(N_EVENTS):
        mech_name = mechanism_names[rng.integers(0, len(mechanism_names))]
        mech_fn = MECHANISMS[mech_name]
        source_loc = nonviable_locations[rng.integers(0, len(nonviable_locations))]
        start_idx = rng.integers(0, len(timestamps) - EVENT_STEPS)
        alpha = rng.uniform(0.7, 1.3)  # airflow decay parameter, per paper
        strength = rng.uniform(0.9, 1.2)

        t = np.arange(EVENT_STEPS)
        signal = mech_fn(t) * strength

        for loc in nonviable_locations:
            dx = loc[4] - source_loc[4]
            dy = loc[5] - source_loc[5]
            dist = np.sqrt(dx**2 + dy**2)
            weight = np.exp(-dist / alpha)
            series[loc[0]][start_idx:start_idx + EVENT_STEPS] += signal * weight
            if loc[0] == source_loc[0]:
                for i in range(EVENT_STEPS):
                    event_labels[loc[0]][start_idx + i] = mech_name

    # assemble rows
    for loc in nonviable_locations:
        grade = room_lookup[loc[1]][2]
        limits = LIMITS[grade]
        for i, ts in enumerate(timestamps):
            count = max(0, series[loc[0]][i])
            rows.append({
                "reading_id": reading_id,
                "location_id": loc[0],
                "sample_datetime": ts,
                "shift": ["Day", "Evening", "Night", "Night"][i % 4],
                "operator_id": int(rng.integers(1, 9)),
                "particle_size_bin": "0.5um",
                "raw_count": round(float(count), 2),
                "unit": "counts/m3",
                "alert_limit": limits["alert"],
                "action_limit": limits["action"],
                "is_alert_breach": int(count >= limits["alert"]),
                "is_action_breach": int(count >= limits["action"]),
                "mechanism_label": event_labels[loc[0]][i],
            })
            reading_id += 1

    return pd.DataFrame(rows), reading_id


def build_viable_readings(start_reading_id):
    rows = []
    reading_id = start_reading_id
    room_lookup = {r[0]: r for r in ROOMS}
    viable_locations = [loc for loc in LOCATIONS if loc[3] == "viable_air"]
    start = datetime(2026, 1, 1)
    weekly_timestamps = [start + timedelta(days=7 * i) for i in range(N_DAYS // 7)]

    for loc in viable_locations:
        grade = room_lookup[loc[1]][2]
        limits = VIABLE_LIMITS.get(grade, {"alert": 5, "action": 15})
        lam = 0.15 if grade == "A" else 3.0
        for ts in weekly_timestamps:
            cfu = rng.poisson(lam=lam)
            rows.append({
                "reading_id": reading_id,
                "location_id": loc[0],
                "sample_datetime": ts,
                "shift": "Day",
                "operator_id": int(rng.integers(1, 9)),
                "particle_size_bin": None,
                "raw_count": float(cfu),
                "unit": "CFU/plate",
                "alert_limit": limits["alert"],
                "action_limit": limits["action"],
                "is_alert_breach": int(cfu >= limits["alert"]),
                "is_action_breach": int(cfu >= limits["action"]),
                "mechanism_label": "none",
            })
            reading_id += 1

    return pd.DataFrame(rows)


def main():
    nonviable_df, next_id = build_nonviable_readings()
    viable_df = build_viable_readings(next_id)
    full_df = pd.concat([nonviable_df, viable_df], ignore_index=True)
    full_df.to_csv("em_readings.csv", index=False)
    print(f"Wrote em_readings.csv with {len(full_df)} rows")

    # load into SQLite matching schema.sql
    conn = sqlite3.connect("em_data.db")
    with open("schema.sql") as f:
        conn.executescript(f.read())

    conn.executemany(
        "INSERT INTO rooms VALUES (?,?,?,?)", ROOMS
    )
    conn.executemany(
        "INSERT INTO sampling_locations VALUES (?,?,?,?,?,?)", LOCATIONS
    )
    conn.executemany(
        "INSERT INTO personnel VALUES (?,?)",
        [(i, "Operator") for i in range(1, 9)]
    )
    full_df.to_sql("em_readings", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()
    print("Loaded em_data.db")


if __name__ == "__main__":
    main()
