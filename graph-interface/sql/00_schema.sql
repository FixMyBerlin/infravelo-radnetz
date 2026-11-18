-- Schemas und Hilfsfunktionen für die Matching-Schnittstelle.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS matching;
CREATE SCHEMA IF NOT EXISTS matching_staging;

-- Wie normalize_name im Rust-Matching (processing/map-matching/src/trace/mod.rs):
-- klein, "str." und "strasse" -> "straße", ohne Leerzeichen und Bindestriche.
CREATE OR REPLACE FUNCTION matching.normalize_match_key(name text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT NULLIF(
        regexp_replace(
            replace(replace(lower(btrim(name)), 'str.', 'straße'), 'strasse', 'straße'),
            '[[:space:]-]', '', 'g'),
        '')
$$;
