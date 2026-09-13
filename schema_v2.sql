-- ============================================================================
-- Environmental Monitoring (EM) Data Schema -- v2
-- ============================================================================
-- Changes from v1, and why:
--
-- 1. `rooms.iso_grade` no longer has a strict CHECK on 'A'/'B'/'C'/'D'.
--    Real facilities use TWO related but distinct classification systems:
--      - EU GMP grades:      A, B, C, D          (EudraLex Annex 1)
--      - ISO 14644-1 classes: ISO 5, ISO 7, ISO 8 (international standard)
--    They roughly correspond (Grade A ~ ISO 5, Grade C ~ ISO 7, Grade D ~
--    ISO 8) but are not identical, and different documentation systems use
--    one or the other. Storing whichever your source data uses, as free
--    text, and being able to explain the correspondence when asked, is
--    itself a small but real credibility signal.
--
-- 2. `sampling_locations.sample_type` now also accepts 'particle_count' and
--    'non_viable_air' as first-class values (alongside the original
--    'nonviable_particle') to match how monitoring types are actually
--    labeled in typical EM exports. Keep whichever vocabulary your source
--    data uses -- don't silently rename things to fit a schema.
--
-- 3. `personnel.external_id` added -- real systems reference people by a
--    site-assigned code (e.g. 'AN-075'), not a clean integer. The integer
--    `operator_id` stays as the internal primary key; `external_id` keeps
--    the original code for traceability back to source records.
--
-- 4. `em_readings.batch_id` added -- ties an EM reading to the manufacturing
--    batch in progress at the time of sampling. This is exactly the kind of
--    field that turns "here's a chart of particle counts" into "here's
--    which batches were potentially at risk," which is the question a QA
--    reviewer actually wants answered during an investigation.
--
-- Everything else (the reasoning for denormalized alert/action limits on
-- each reading, the x/y positions for future spatial work) is unchanged
-- from v1 -- see the original schema.sql for that discussion.
-- ============================================================================

CREATE TABLE rooms (
    room_id     INTEGER PRIMARY KEY,
    room_name   TEXT NOT NULL,                 -- e.g. 'Room_A' or 'Fill Suite 1'
    iso_grade   TEXT NOT NULL,                 -- e.g. 'A' or 'ISO5' -- whatever your source uses
    area_type   TEXT NOT NULL DEFAULT 'Unspecified'
);

CREATE TABLE sampling_locations (
    location_id     INTEGER PRIMARY KEY,
    room_id         INTEGER NOT NULL REFERENCES rooms(room_id),
    location_name   TEXT NOT NULL,
    sample_type     TEXT NOT NULL
                    CHECK (sample_type IN
                        ('nonviable_particle','particle_count','non_viable_air',
                         'viable_air','surface','glove','gown')),
    x_position      REAL,                       -- optional; used by Module 2
    y_position      REAL
);

CREATE TABLE limits_reference (
    limit_id            INTEGER PRIMARY KEY,
    iso_grade           TEXT NOT NULL,
    sample_type         TEXT NOT NULL,
    particle_size_bin   TEXT,
    alert_limit         REAL NOT NULL,
    action_limit        REAL NOT NULL,
    unit                TEXT NOT NULL,
    effective_date      DATE NOT NULL
);

CREATE TABLE personnel (
    operator_id     INTEGER PRIMARY KEY,
    external_id     TEXT,                       -- original source code, e.g. 'AN-075'
    role            TEXT
);

CREATE TABLE em_readings (
    reading_id          INTEGER PRIMARY KEY,
    location_id         INTEGER NOT NULL REFERENCES sampling_locations(location_id),
    sample_datetime     TIMESTAMP NOT NULL,
    shift               TEXT,
    operator_id         INTEGER REFERENCES personnel(operator_id),
    batch_id            TEXT,                    -- manufacturing batch in progress at sample time
    particle_size_bin   TEXT,
    raw_count           REAL NOT NULL,
    unit                TEXT NOT NULL,
    alert_limit         REAL NOT NULL,
    action_limit        REAL NOT NULL,
    is_alert_breach     INTEGER NOT NULL DEFAULT 0,
    is_action_breach    INTEGER NOT NULL DEFAULT 0,
    mechanism_label     TEXT
);

CREATE TABLE excursion_events (
    event_id                INTEGER PRIMARY KEY,
    reading_id              INTEGER REFERENCES em_readings(reading_id),
    detected_datetime       TIMESTAMP,
    mechanism_hypothesis    TEXT,
    investigation_status    TEXT,
    root_cause              TEXT,
    capa_reference          TEXT
);

CREATE INDEX idx_readings_location_time ON em_readings(location_id, sample_datetime);
CREATE INDEX idx_readings_breaches ON em_readings(is_alert_breach, is_action_breach);
CREATE INDEX idx_readings_batch ON em_readings(batch_id);
