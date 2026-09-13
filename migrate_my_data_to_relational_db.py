"""
migrate_my_data_to_relational_db.py

Takes YOUR flat em_records_raw.csv (the one you built in Colab, with columns:
date, room_id, room_class, monitoring_type, result_value, alert_limit,
action_limit, exceedance_flag, exceedance_type, analyst_id, batch_id)
and loads it into the 5-table relational schema (schema_v2.sql).

Run this in the same Colab session where your CSV already lives:

    python migrate_my_data_to_relational_db.py \
        --csv "/content/drive/MyDrive/Pharma_EM_Trend_Tracker/em_records_raw.csv" \
        --schema schema_v2.sql \
        --out em_data.db

If you're running locally instead of Colab, just point --csv at wherever the
file actually is.

ASSUMPTIONS YOU SHOULD VERIFY (search for "ASSUMPTION" below):
  - The unit assigned to each monitoring_type (e.g. is 'surface' really
    CFU/plate, or CFU per some other area in your generator?). Fix
    MONITORING_UNIT_MAP if it doesn't match how you built the limits.
  - area_type on each room is set to 'Unspecified' because your CSV doesn't
    carry that info. If you know which rooms are fill lines vs gowning vs
    corridors, it's worth updating the `rooms` table after loading.
"""

import argparse
import sqlite3
import pandas as pd

# ASSUMPTION: adjust this if your synthetic data used different units per
# monitoring type. This only affects display/labeling, not the numbers.
MONITORING_UNIT_MAP = {
    "viable_air": "CFU/m3",
    "surface": "CFU/plate",
    "particle_count": "counts/m3",
    "non_viable_air": "counts/m3",
}


def migrate(csv_path: str, schema_path: str, db_path: str):
    df = pd.read_csv(csv_path, parse_dates=["date"])
    print(f"Loaded {len(df)} rows from {csv_path}")

    # --- rooms -----------------------------------------------------------
    room_combos = df[["room_id", "room_class"]].drop_duplicates().reset_index(drop=True)
    room_combos["room_pk"] = room_combos.index + 1
    rooms_df = pd.DataFrame({
        "room_id": room_combos["room_pk"],
        "room_name": room_combos["room_id"],
        "iso_grade": room_combos["room_class"],
        "area_type": "Unspecified",
    })

    # --- sampling_locations ------------------------------------------------
    loc_combos = df[["room_id", "monitoring_type"]].drop_duplicates().reset_index(drop=True)
    loc_combos["location_pk"] = loc_combos.index + 1
    loc_combos = loc_combos.merge(
        room_combos[["room_id", "room_pk"]], on="room_id", how="left"
    )
    locations_df = pd.DataFrame({
        "location_id": loc_combos["location_pk"],
        "room_id": loc_combos["room_pk"],
        "location_name": loc_combos["room_id"] + " - " + loc_combos["monitoring_type"],
        "sample_type": loc_combos["monitoring_type"],
        "x_position": None,
        "y_position": None,
    })

    # --- limits_reference ----------------------------------------------------
    limit_combos = (
        df[["room_class", "monitoring_type", "alert_limit", "action_limit"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    limit_combos["limit_pk"] = limit_combos.index + 1
    limits_df = pd.DataFrame({
        "limit_id": limit_combos["limit_pk"],
        "iso_grade": limit_combos["room_class"],
        "sample_type": limit_combos["monitoring_type"],
        "particle_size_bin": None,
        "alert_limit": limit_combos["alert_limit"],
        "action_limit": limit_combos["action_limit"],
        "unit": limit_combos["monitoring_type"].map(MONITORING_UNIT_MAP),
        "effective_date": df["date"].min().date().isoformat(),
    })

    # --- personnel -----------------------------------------------------------
    analyst_ids = df["analyst_id"].drop_duplicates().reset_index(drop=True)
    personnel_df = pd.DataFrame({
        "operator_id": range(1, len(analyst_ids) + 1),
        "external_id": analyst_ids,
        "role": "Analyst",
    })

    # --- em_readings -----------------------------------------------------------
    working = df.merge(
        loc_combos[["room_id", "monitoring_type", "location_pk"]],
        on=["room_id", "monitoring_type"], how="left"
    ).merge(
        personnel_df[["operator_id", "external_id"]],
        left_on="analyst_id", right_on="external_id", how="left"
    )

    readings_df = pd.DataFrame({
        "reading_id": range(1, len(working) + 1),
        "location_id": working["location_pk"],
        "sample_datetime": working["date"],
        "shift": None,
        "operator_id": working["operator_id"],
        "batch_id": working["batch_id"],
        "particle_size_bin": None,
        "raw_count": working["result_value"],
        "unit": working["monitoring_type"].map(MONITORING_UNIT_MAP),
        "alert_limit": working["alert_limit"],
        "action_limit": working["action_limit"],
        "is_alert_breach": (working["result_value"] >= working["alert_limit"]).astype(int),
        "is_action_breach": (working["result_value"] >= working["action_limit"]).astype(int),
        "mechanism_label": None,
    })

    # --- excursion_events (seed one per breached reading) -----------------------
    breached = readings_df[readings_df["is_alert_breach"] == 1].copy()
    events_df = pd.DataFrame({
        "event_id": range(1, len(breached) + 1),
        "reading_id": breached["reading_id"].values,
        "detected_datetime": breached["sample_datetime"].values,
        "mechanism_hypothesis": None,
        "investigation_status": "Open",
        "root_cause": None,
        "capa_reference": None,
    })

    # --- write everything to SQLite --------------------------------------------
    conn = sqlite3.connect(db_path)
    with open(schema_path) as f:
        conn.executescript(f.read())

    rooms_df.to_sql("rooms", conn, if_exists="append", index=False)
    locations_df.to_sql("sampling_locations", conn, if_exists="append", index=False)
    limits_df.to_sql("limits_reference", conn, if_exists="append", index=False)
    personnel_df[["operator_id", "external_id", "role"]].to_sql(
        "personnel", conn, if_exists="append", index=False
    )
    readings_df.to_sql("em_readings", conn, if_exists="append", index=False)
    events_df.to_sql("excursion_events", conn, if_exists="append", index=False)
    conn.commit()

    # --- sanity checks -----------------------------------------------------------
    cur = conn.cursor()
    for table in ["rooms", "sampling_locations", "limits_reference",
                  "personnel", "em_readings", "excursion_events"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {cur.fetchone()[0]} rows")

    cur.execute("""
        SELECT COUNT(*) FROM em_readings r
        LEFT JOIN sampling_locations l ON r.location_id = l.location_id
        WHERE l.location_id IS NULL
    """)
    orphans = cur.fetchone()[0]
    if orphans:
        print(f"  WARNING: {orphans} readings have no matching sampling_location")
    else:
        print("  No orphaned foreign keys -- migration looks clean.")

    conn.close()
    print(f"\nDone. Database written to {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to your em_records_raw.csv")
    parser.add_argument("--schema", default="schema_v2.sql")
    parser.add_argument("--out", default="em_data.db")
    args = parser.parse_args()
    migrate(args.csv, args.schema, args.out)
