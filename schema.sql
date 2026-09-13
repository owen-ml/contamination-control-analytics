-- ============================================================================
-- Environmental Monitoring (EM) Data Schema
-- ============================================================================
-- Design notes (read before writing queries):
--
-- 1. This is deliberately normalized (separate rooms / locations / limits
--    tables) rather than one flat CSV-style table, because that's how you'll
--    encounter real facility data, and because JOIN practice across these
--    tables IS the SQL skill-building exercise. Resist the urge to flatten
--    it for convenience.
--
-- 2. `sampling_locations` carries x_position/y_position even though Module 1
--    never uses them. They exist so Module 2 (Bayesian spatial localization,
--    from your paper) can reuse this exact schema without a redesign.
--
-- 3. Limits live in TWO places on purpose:
--      - `limits_reference`: the master table of regulatory limits by grade/
--        sample type (ISO 14644-1 style). This is what a validated site's
--        QA limits table actually looks like.
--      - `em_readings.alert_limit` / `action_limit`: a denormalized copy on
--        each reading. This is intentional, not an oversight — regulatory
--        limits can change over time (revalidation), and a reading must
--        always show the limit that was IN EFFECT when it was taken, not
--        today's limit. Never let historical readings silently inherit a
--        newer limit.
-- ============================================================================

CREATE TABLE rooms (
    room_id     INTEGER PRIMARY KEY,
    room_name   TEXT NOT NULL,                 -- e.g. 'Fill Suite 1'
    iso_grade   TEXT NOT NULL                   -- 'A', 'B', 'C', 'D'
                CHECK (iso_grade IN ('A','B','C','D')),
    area_type   TEXT NOT NULL                   -- 'Fill Line','Gowning','Airlock','Corridor'
);

CREATE TABLE sampling_locations (
    location_id     INTEGER PRIMARY KEY,
    room_id         INTEGER NOT NULL REFERENCES rooms(room_id),
    location_name   TEXT NOT NULL,              -- e.g. 'Sensor 3 - Stopper Bowl'
    sample_type     TEXT NOT NULL
                    CHECK (sample_type IN
                        ('nonviable_particle','viable_air','surface','glove','gown')),
    x_position      REAL,                       -- optional; used by Module 2
    y_position      REAL
);

CREATE TABLE limits_reference (
    limit_id            INTEGER PRIMARY KEY,
    iso_grade           TEXT NOT NULL,
    sample_type         TEXT NOT NULL,
    particle_size_bin   TEXT,                   -- '0.5um' / '5.0um', NULL for viable/surface
    alert_limit         REAL NOT NULL,
    action_limit        REAL NOT NULL,
    unit                TEXT NOT NULL,           -- 'counts/m3','CFU/plate','CFU/m3'
    effective_date      DATE NOT NULL
);

CREATE TABLE personnel (
    operator_id     INTEGER PRIMARY KEY,
    role            TEXT                         -- 'Operator','Line Lead','QA'
);

CREATE TABLE em_readings (
    reading_id          INTEGER PRIMARY KEY,
    location_id         INTEGER NOT NULL REFERENCES sampling_locations(location_id),
    sample_datetime     TIMESTAMP NOT NULL,
    shift               TEXT,                    -- 'Day','Evening','Night'
    operator_id         INTEGER REFERENCES personnel(operator_id),
    particle_size_bin   TEXT,                    -- NULL for viable/surface samples
    raw_count           REAL NOT NULL,
    unit                TEXT NOT NULL,
    alert_limit         REAL NOT NULL,            -- copied from limits_reference at sample time
    action_limit        REAL NOT NULL,            -- copied from limits_reference at sample time
    is_alert_breach     INTEGER NOT NULL DEFAULT 0,
    is_action_breach    INTEGER NOT NULL DEFAULT 0,
    mechanism_label     TEXT                      -- ground-truth label for synthetic data only:
                                                   -- 'none','glove_breach','mechanical_friction','hvac_drift'
                                                   -- (used to train/validate Module 2's classifier)
);

CREATE TABLE excursion_events (
    event_id                INTEGER PRIMARY KEY,
    reading_id              INTEGER REFERENCES em_readings(reading_id),
    detected_datetime       TIMESTAMP,
    mechanism_hypothesis    TEXT,                 -- investigator's/model's hypothesis
    investigation_status    TEXT,                 -- 'Open','Closed','Pending QA Review'
    root_cause              TEXT,
    capa_reference          TEXT
);

-- Helpful indexes for the trending queries you'll be writing
CREATE INDEX idx_readings_location_time ON em_readings(location_id, sample_datetime);
CREATE INDEX idx_readings_breaches ON em_readings(is_alert_breach, is_action_breach);
