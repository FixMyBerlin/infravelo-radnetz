-- Schritt 0a: Eingang des Radnetz-Graphen direkt aus den TILDA-Tabellen, mit übersetzten Attributen (ersetzt
-- load_input.py, frühere Python-Fassung). Liest tilda-geo public.bikelanes, public.roads, public."roadsPathClasses" (je Zeile ein TILDA-Objekt,
-- Weg oder Seitenobjekt) und schreibt bikegraph.input_raw (n, trace_group, input_ref, geom_hex, attrs) für sql/05.
-- Die Übersetzung ist ein SQL-Port von translate_tilda_attributes (processing/scripts/
-- translate_attributes_tilda_to_rvn.py) samt has_traffic_sign, parse_width und collect_todo_attributes (processing/
-- helpers); Regeln, Texte und Reihenfolge wie dort. Änderungen an den Regeln müssen in beiden Fassungen erfolgen.
-- Abweichung vom Python-Weg, bewusst: ein fehlender Tag zählt wie in der ungeteilten Tabelle als "nan" (str(NaN));
-- load_input.py übersetzte in Blöcken zu 2000 Objekten, dort wurde ein Tag, der im ganzen Block fehlt, zu "" (betrifft
-- nur Texte mit dem Wert, am 2026-11-17 kein Objekt).
-- Wie load_input.py: Schlüssel mit ":" werden zu "_" (bei doppelten Schlüsseln gilt der spätere in jsonb-Reihenfolge:
-- "a_b" vor "a:b"); id, osm_id, osm_type aus den Spalten; Straßen und Wege ohne oneway-Tag gelten als oneway=no;
-- Ausgabewerte ganzzahlig ohne Nachkommastelle, Wahrheitswerte als Text True/False, leere Werte entfallen; ursprüngliche
-- Tags mit Präfix tilda_, ohne CONFIG_REMOVE_TILDA_ATTRIBUTES.
-- Schritte (psql-Variable schritt), damit graph.sh die Übersetzung auf mehrere Sitzungen verteilen kann (PostgreSQL rechnet
-- die Projektion mit Unterabfragen sonst nur im Leader):
--   vorbereiten  Hilfsfunktionen, leere Tabelle bikegraph.input_raw_ungeordnet
--   rechnen      Teil :teil von :teile (Objekte nach Hash der id verteilt) übersetzen und anhängen
--   abschluss    Nummer n in der Reihenfolge von load_input.py (Tabelle, dann id) -> bikegraph.input_raw
--   alles        alle drei nacheinander in einer Sitzung (Standard, teile = 1)
\if :{?schritt}
\else
\set schritt alles
\endif
\if :{?teile}
\else
\set teile 1
\endif
\if :{?teil}
\else
\set teil 0
\endif
SELECT :'schritt' IN ('alles', 'vorbereiten') AS s_vorbereiten, :'schritt' IN ('alles', 'rechnen') AS s_rechnen,
       :'schritt' IN ('alles', 'abschluss') AS s_abschluss \gset
-- Jede Sitzung rechnet allein (die Parallelität kommt aus graph.sh)
SET max_parallel_workers_per_gather = 0;

\if :s_vorbereiten
DROP TABLE IF EXISTS bikegraph.input_raw_ungeordnet;
CREATE UNLOGGED TABLE bikegraph.input_raw_ungeordnet (reihe int, id text, gruppe text, geom_hex text, attrs jsonb);

-- Wert eines Tags wie str(row.get(k, "")) nach dem Umschreiben ":" -> "_": fehlend "nan", JSON-null "None",
-- Wahrheitswerte "True"/"False". k ist der Schlüssel mit "_", k2 dieselbe Schreibweise mit ":" (oder NULL).
CREATE OR REPLACE FUNCTION bikegraph.tr_wert(t jsonb, k text, k2 text DEFAULT NULL) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE jsonb_typeof(coalesce(t -> k, t -> k2))
               WHEN 'boolean' THEN CASE WHEN coalesce(t -> k, t -> k2)::boolean THEN 'True' ELSE 'False' END
               WHEN 'null' THEN 'None'
               ELSE coalesce(t ->> k, t ->> k2, 'nan') END
$$;
-- str(...).strip()
CREATE OR REPLACE FUNCTION bikegraph.tr_strip(v text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT btrim(v, E' \t\n\r\f\v')
$$;
-- float(v) oder None
CREATE OR REPLACE FUNCTION bikegraph.tr_zahl(t jsonb, k text) RETURNS float8 LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN jsonb_typeof(t -> k) = 'number' THEN (t ->> k)::float8
                WHEN jsonb_typeof(t -> k) = 'string'
                     AND t ->> k ~ '^\s*[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?\s*$' THEN (t ->> k)::float8 END
$$;
-- has_traffic_sign (helpers/traffic_signs.py): "DE:<z>" irgendwo im Wert, oder ein Teil (Komma, ohne Leerraum) gleich
-- <z>, sofern der Wert "DE:" enthält. z ist eine Konstante; die Funktion wird eingebettet.
CREATE OR REPLACE FUNCTION bikegraph.tr_zeichen(v text, z text) RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT coalesce(v, '') <> '' AND (
        strpos(v, 'DE:' || z) > 0
        OR (strpos(v, 'DE:') > 0
            AND v ~ ('(^|,)\s*' || regexp_replace(z, '([.^$*+?()\[\]{}|\\])', '\\\1', 'g') || '\s*(,|$)')))
$$;
-- round(w, 1) wie Python: auf dem exakten Binärwert, genau halbe Werte zur geraden Ziffer. Exakter Wert über den
-- ganzzahligen Teil und den Bruchteil mal 2^62 (für Werte ab 2^-10 ganzzahlig, also exakt in bigint); ein Ausdruck,
-- damit PostgreSQL die Funktion einbettet.
CREATE OR REPLACE FUNCTION bikegraph.tr_runde1(w float8) RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT (CASE WHEN ((floor(w)::numeric + ((w - floor(w)) * 4611686018427387904::float8)::bigint::numeric / 4611686018427387904) * 10)
                      - floor((floor(w)::numeric + ((w - floor(w)) * 4611686018427387904::float8)::bigint::numeric / 4611686018427387904) * 10) <> 0.5
                 THEN round((floor(w)::numeric + ((w - floor(w)) * 4611686018427387904::float8)::bigint::numeric / 4611686018427387904) * 10)
                 ELSE floor((floor(w)::numeric + ((w - floor(w)) * 4611686018427387904::float8)::bigint::numeric / 4611686018427387904) * 10)
                      + mod(floor((floor(w)::numeric + ((w - floor(w)) * 4611686018427387904::float8)::bigint::numeric / 4611686018427387904) * 10), 2) END) / 10
$$;
-- collect_todo_attributes(include_missing=True) für einen Textwert: leer, "nan", "None"/"none", "[TODO]" oder "fehlt"
CREATE OR REPLACE FUNCTION bikegraph.tr_fehlt(v text) RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT v IS NULL OR bikegraph.tr_strip(v) IN ('', 'nan', 'None', 'none') OR strpos(lower(v), '[todo]') > 0 OR strpos(lower(v), 'fehlt') > 0
$$;
-- Ausgabewert wie plain() in load_input.py: ganzzahlige Zahlen ohne Nachkommastelle, Wahrheitswerte als Text
CREATE OR REPLACE FUNCTION bikegraph.tr_ausgabe(v jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE jsonb_typeof(v)
               WHEN 'boolean' THEN to_jsonb(CASE WHEN v::boolean THEN 'True' ELSE 'False' END)
               WHEN 'number' THEN CASE WHEN (v #>> '{}')::numeric = trunc((v #>> '{}')::numeric)
                                       THEN to_jsonb(trunc((v #>> '{}')::numeric)) ELSE v END
               ELSE v END
$$;

\endif

\if :s_rechnen
INSERT INTO bikegraph.input_raw_ungeordnet (reihe, id, gruppe, geom_hex, attrs)
WITH quelle AS (
    -- Reihenfolge wie load_input.py: Tabelle, dann id
    SELECT 1 AS reihe, 'bikelanes'::text AS gruppe, id, osm_id, osm_type, coalesce(tags, '{}'::jsonb) AS t, geom FROM public.bikelanes
    UNION ALL SELECT 2, 'streets', id, osm_id, osm_type, coalesce(tags, '{}'::jsonb), geom FROM public.roads
    UNION ALL SELECT 3, 'paths', id, osm_id, osm_type, coalesce(tags, '{}'::jsonb), geom FROM public."roadsPathClasses"
),
teil AS (
    SELECT * FROM quelle WHERE mod(abs(hashtextextended(id, 0)), :teile) = :teil
),
felder AS (
    SELECT q.reihe, q.gruppe, q.id, q.osm_id, q.osm_type, q.t, ST_Transform(q.geom, 25833) AS g,
           -- oneway; Straßen und Wege ohne Wert: "no" (load_input.py)
           CASE WHEN q.gruppe <> 'bikelanes' AND coalesce(q.t ->> 'oneway', '') = '' THEN 'no'
                ELSE bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'oneway')) END AS o,
           bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'oneway_bicycle', 'oneway:bicycle')) AS ob,
           bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'category')) AS cat,
           bikegraph.tr_wert(q.t, 'traffic_sign') AS ts,
           bikegraph.tr_wert(q.t, 'traffic_sign_forward', 'traffic_sign:forward') AS ts_vor,
           bikegraph.tr_wert(q.t, 'traffic_sign_backward', 'traffic_sign:backward') AS ts_rueck,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'surface'))) AS surf,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'surface_color', 'surface:color'))) AS farbwert,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'separation_left', 'separation:left'))) AS sep_l,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'separation_right', 'separation:right'))) AS sep_r,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'traffic_mode_left', 'traffic_mode:left'))) AS tm_l,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'traffic_mode_right', 'traffic_mode:right'))) AS tm_r,
           lower(bikegraph.tr_wert(q.t, 'marking_left', 'marking:left')) AS mk_l,
           lower(bikegraph.tr_wert(q.t, 'marking_right', 'marking:right')) AS mk_r,
           bikegraph.tr_zahl(q.t, CASE WHEN q.t ? 'buffer_left' THEN 'buffer_left' ELSE 'buffer:left' END) AS buf_l,
           bikegraph.tr_zahl(q.t, CASE WHEN q.t ? 'buffer_right' THEN 'buffer_right' ELSE 'buffer:right' END) AS buf_r,
           coalesce(bikegraph.tr_zahl(q.t, CASE WHEN q.t ? 'width_effective' THEN 'width_effective' ELSE 'width:effective' END),
                    bikegraph.tr_zahl(q.t, 'width')) AS w,
           lower(bikegraph.tr_strip(bikegraph.tr_wert(q.t, 'lifecycle'))) AS lc
    FROM teil q
),
regeln AS (
    SELECT f.*,
           -- determine_verkehrsri
           CASE WHEN f.gruppe = 'bikelanes' THEN
                    CASE WHEN f.o = 'yes' THEN 'Einrichtungsverkehr'
                         WHEN f.o IN ('no', 'car_not_bike', 'assumed_no') THEN 'Zweirichtungsverkehr'
                         WHEN f.o = 'implicit_yes' THEN 'Einrichtungsverkehr'
                         WHEN f.o IN ('', 'None', 'none') THEN '[TODO] Fehlender Wert: oneway=' || f.o
                         ELSE '[TODO] Fehlerhafter Wert: oneway=' || f.o END
                ELSE
                    CASE WHEN f.o IN ('', 'None', 'none', 'nil') THEN 'Zweirichtungsverkehr'
                         WHEN f.ob = 'no' THEN 'Zweirichtungsverkehr'
                         WHEN f.o IN ('yes', 'yes_dual_carriageway') THEN 'Einrichtungsverkehr'
                         WHEN f.o = 'no' THEN 'Zweirichtungsverkehr'
                         ELSE '[TODO] Fehlerhafter Wert: oneway=' || f.o END
           END AS verkehrsri,
           -- determine_fuehrung
           CASE WHEN f.gruppe = 'streets' THEN 'Mischverkehr mit motorisiertem Verkehr'
                WHEN f.gruppe = 'paths' THEN 'Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)'
                WHEN f.cat IN ('cyclewayOnHighway_exclusive', 'cyclewayOnHighwayBetweenLanes') THEN 'Radfahrstreifen'
                WHEN f.cat = 'sharedBusLaneBikeWithBus' THEN 'Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)'
                WHEN f.cat = 'sharedBusLaneBusWithBike' THEN 'Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)'
                WHEN f.cat = 'cyclewayOnHighwayProtected' THEN 'Geschützter Radfahrstreifen'
                WHEN f.cat = 'cyclewayOnHighway_advisory' THEN 'Schutzstreifen'
                WHEN f.cat IN ('bicycleRoad', 'bicycleRoad_vehicleDestination') THEN 'Fahrradstraße /-zone (Z 244)'
                WHEN starts_with(f.cat, 'footAndCyclewayShared') OR starts_with(f.cat, 'footAndCyclewaySegregated')
                  OR starts_with(f.cat, 'cyclewaySeparated') OR starts_with(f.cat, 'cycleway_adjoining') THEN
                    CASE WHEN starts_with(f.cat, 'footAndCyclewayShared') AND bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '240')
                         THEN 'Gemeinsamer Geh- und Radweg mit Z240' ELSE 'Radweg' END
                WHEN f.cat = 'cycleway_isolated' THEN 'Radweg'
                WHEN starts_with(f.cat, 'footwayBicycleYes') THEN
                    CASE WHEN bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '239') AND bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '1022-10')
                         THEN 'Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)'
                         ELSE 'Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)' END
                WHEN f.cat = 'pedestrianAreaBicycleYes'
                     AND (bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '242') OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '242.1'))
                     AND bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '1022-10') THEN 'Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)'
                WHEN f.cat = 'sharedMotorVehicleLane' THEN 'Mischverkehr mit motorisiertem Verkehr'
                WHEN f.cat = 'pedestrianAreaBicycleYes' THEN 'Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)'
                WHEN f.cat = 'crossing' THEN 'Kreuzungsweg'
                WHEN f.cat = 'needsClarification' THEN '[TODO] Klärung notwendig'
                ELSE '[TODO] Führung fehlt' END AS fuehr,
           -- determine_pflicht: Z237, Z240, Z241 in traffic_sign, _forward oder _backward; nie auf Straßen
           f.gruppe <> 'streets' AND (
               (bikegraph.tr_strip(f.ts) <> '' AND (bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '237')
                    OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '240') OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts), '241')))
            OR (bikegraph.tr_strip(f.ts_vor) <> '' AND (bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts_vor), '237')
                    OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts_vor), '240') OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts_vor), '241')))
            OR (bikegraph.tr_strip(f.ts_rueck) <> '' AND (bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts_rueck), '237')
                    OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts_rueck), '240') OR bikegraph.tr_zeichen(bikegraph.tr_strip(f.ts_rueck), '241')))
           ) AS pflicht,
           -- parse_width(width_effective, sonst width): 0 und Fehlendes ergeben keinen Wert
           CASE WHEN coalesce(f.w, 0) <> 0 THEN bikegraph.tr_runde1(f.w) END AS breite,
           -- determine_ofm
           CASE WHEN f.surf IN ('', 'nan') THEN 'NICHT-GEFUNDEN'
                WHEN f.surf = 'none' THEN '[TODO] Fehlt'
                WHEN f.surf = 'asphalt' THEN 'Asphalt'
                WHEN f.surf IN ('concrete', 'concrete:plates', 'concrete:lanes') THEN 'Beton (Platte etc.)'
                WHEN f.surf IN ('paving_stones', 'mosaic_sett', 'small_sett', 'large_sett')
                     THEN 'Gepflastert (Berliner Platte, Mosaik, Kleinstein...)'
                WHEN f.surf IN ('sett', 'cobblestone', 'bricks', 'stone') THEN 'Kopfsteinpflaster / Großstein'
                WHEN f.surf IN ('unpaved', 'ground', 'grass', 'sand', 'compacted', 'fine_gravel', 'pebblestone', 'gravel') THEN 'Ungebunden'
                ELSE 'Sonstige' END AS ofm,
           -- determine_farbe
           f.farbwert IN ('red', 'green') AS farbe,
           -- determine_protek: nur geschützte Radfahrstreifen; erst links, dann rechts
           CASE WHEN f.cat <> 'cyclewayOnHighwayProtected' THEN 'Ohne'
                ELSE coalesce(
                    CASE WHEN f.tm_l = 'parking' AND strpos(f.mk_l, 'barred_area') > 0 THEN 'Ruhender Verkehr (mit Sperrfläche)'
                         WHEN f.sep_l = 'bollard' THEN 'Poller (auf Sperrfläche)'
                         WHEN f.sep_l = 'bump' THEN 'Schwellen (auf Sperrfläche)'
                         WHEN f.sep_l IN ('vertical_panel', 'flex_post') THEN 'Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)'
                         WHEN f.sep_l IN ('planter', 'guard_rail', 'fence', 'jersey_barrier') THEN 'Sonstige (z.B. Pflanzkübel, Leitplanke)'
                         WHEN f.sep_l = 'no' THEN 'Ohne' END,
                    CASE WHEN f.tm_r = 'parking' AND strpos(f.mk_r, 'barred_area') > 0 THEN 'Ruhender Verkehr (mit Sperrfläche)'
                         WHEN f.sep_r = 'bollard' THEN 'Poller (auf Sperrfläche)'
                         WHEN f.sep_r = 'bump' THEN 'Schwellen (auf Sperrfläche)'
                         WHEN f.sep_r IN ('vertical_panel', 'flex_post') THEN 'Leitboys (flexibel, auf Breitstrich, ohne Sperrfläche)'
                         WHEN f.sep_r IN ('planter', 'guard_rail', 'fence', 'jersey_barrier') THEN 'Sonstige (z.B. Pflanzkübel, Leitplanke)'
                         WHEN f.sep_r = 'no' THEN 'Ohne' END,
                    'Protektionstyp nicht bekannt') END AS protek,
           -- determine_trennstreifen
           CASE WHEN starts_with(lower(f.cat), 'bicycleroad') THEN
                    CASE WHEN (f.tm_l = 'parking' AND (f.buf_l > 0 OR strpos(bikegraph.tr_strip(f.mk_l), 'dashed_line') > 0
                                                       OR strpos(bikegraph.tr_strip(f.mk_l), 'solid_line') > 0))
                           OR (f.tm_r = 'parking' AND (f.buf_r > 0 OR strpos(bikegraph.tr_strip(f.mk_r), 'dashed_line') > 0
                                                       OR strpos(bikegraph.tr_strip(f.mk_r), 'solid_line') > 0)) THEN 'ja'
                         WHEN f.tm_l = 'parking' OR f.tm_r = 'parking' THEN 'nein'
                         ELSE 'entfällt' END
                WHEN f.tm_r <> 'parking' THEN 'entfällt'
                WHEN f.buf_r >= 0.6 THEN 'ja'
                ELSE 'nein' END AS trennstreifen,
           CASE WHEN f.lc IN ('construction', 'construction_no_access') THEN 'Baustelle'
                WHEN f.lc = 'temporary' THEN 'temporärer Infrastruktur' END AS kommentar_art
    FROM felder f
),
fertig AS (
    SELECT r.*,
           -- determine_nutz_beschr (nach der Führung)
           CASE WHEN r.fuehr = 'Mischverkehr mit motorisiertem Verkehr' THEN 'keine'
                WHEN strpos(r.ts, 'Gehwegschäden') > 0 OR strpos(r.ts, 'Radwegschäden') > 0 OR strpos(r.ts, 'Geh- und Radwegschäden') > 0
                THEN 'Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden)'
                ELSE 'keine' END AS nutz_beschr
    FROM regeln r
),
ausgabe AS (
SELECT x.reihe, x.id, x.gruppe,
       encode(ST_AsBinary(x.g), 'hex') AS geom_hex,
       -- ursprüngliche Tags mit Präfix tilda_ und ":" -> "_", ohne id, osm_id, osm_type, oneway (kommen eigens),
       -- CONFIG_REMOVE_TILDA_ATTRIBUTES und Namen der RVN-Attribute; Werte wie plain(). Als Text zusammengesetzt und einmal
       -- gelesen (dreimal schneller als jsonb_object_agg); bei doppelten Schlüsseln gilt beim Lesen der letzte, in der
       -- Reihenfolge von jsonb_each ("a_b" nach "a:b") wie das dict in load_input.py
       coalesce((SELECT ('{' || string_agg(to_json('tilda_' || replace(j.key, ':', '_'))::text || ':' ||
                     CASE jsonb_typeof(j.value)
                          WHEN 'boolean' THEN CASE WHEN j.value::boolean THEN '"True"' ELSE '"False"' END
                          WHEN 'number' THEN CASE WHEN j.value::text ~ '^-?[0-9]+\.0+$' THEN split_part(j.value::text, '.', 1)
                                                  ELSE j.value::text END
                          ELSE j.value::text END, ',') || '}')::jsonb
                 FROM jsonb_each(x.t) j
                 WHERE jsonb_typeof(j.value) <> 'null'
                   AND replace(j.key, ':', '_') NOT IN (
                       'id', 'osm_id', 'osm_type', 'oneway',
                       'lit', 'description', 'maxspeed_name_ref', 'maxspeed_confidence', 'maxspeed_conditional', 'maxspeed_source',
                       'mapillary_coverage', 'bridge', 'tunnel', 'todos', 'updated_age', 'updated_at', 'surface_confidence',
                       'surface_source', 'smoothness_confidence', 'smoothness_source', 'length', 'offset', '_parent_highway',
                       'pflicht', 'breite', 'ofm', 'farbe', 'protek', 'trennstreifen', 'nutz_beschr', 'fuehr', 'verkehrsri',
                       'Länge', 'Kommentar')), '{}'::jsonb)
       -- id, osm_id, osm_type aus den Spalten; oneway nach der Ergänzung (Straßen und Wege ohne Wert: "no")
       || jsonb_strip_nulls(jsonb_build_object('tilda_id', x.id, 'tilda_osm_id', x.osm_id, 'tilda_osm_type', x.osm_type,
              'tilda_oneway', CASE WHEN x.gruppe <> 'bikelanes' AND coalesce(x.t ->> 'oneway', '') = '' THEN to_jsonb('no'::text)
                                   WHEN jsonb_typeof(x.t -> 'oneway') = 'null' THEN NULL
                                   ELSE bikegraph.tr_ausgabe(x.t -> 'oneway') END))
       || jsonb_strip_nulls(jsonb_build_object(
              'verkehrsri', x.verkehrsri, 'fuehr', x.fuehr, 'pflicht', CASE WHEN x.pflicht THEN 'True' ELSE 'False' END,
              'breite', bikegraph.tr_ausgabe(to_jsonb(x.breite)), 'ofm', x.ofm, 'farbe', CASE WHEN x.farbe THEN 'True' ELSE 'False' END,
              'protek', x.protek, 'trennstreifen', x.trennstreifen, 'nutz_beschr', x.nutz_beschr,
              'Länge', round(ST_Length(x.g))::bigint,
              -- determine_kommentar: Baustelle oder temporäre Markierung, dazu die fehlenden Attribute in der Reihenfolge
              -- von CONFIG_ATTRIBUTES_TODO_CHECK (Pflicht und Farbe sind nie leer). array_to_string überspringt NULL; die
              -- Namen werden mit "<Text>; " verbunden und "<Text>" angehängt, ohne fehlendes Attribut bleibt nur "<Text>" (nullif)
              'Kommentar', CASE WHEN x.kommentar_art IS NOT NULL THEN
                  CASE WHEN x.kommentar_art = 'Baustelle' THEN 'Derzeit Baustelle (Stand unbekannt)'
                       ELSE 'Temporäre Markierungen zum Erhebungszeitpunkt' END
                  || coalesce('; ' || nullif(array_to_string(ARRAY[
                      CASE WHEN x.breite IS NULL THEN 'Breite' END,
                      CASE WHEN bikegraph.tr_fehlt(x.ofm) THEN 'Ofm' END,
                      CASE WHEN bikegraph.tr_fehlt(x.protek) THEN 'Protek' END,
                      CASE WHEN bikegraph.tr_fehlt(x.trennstreifen) THEN 'Trennstreifen' END,
                      CASE WHEN bikegraph.tr_fehlt(x.nutz_beschr) THEN 'Nutz_beschr' END,
                      CASE WHEN bikegraph.tr_fehlt(x.fuehr) THEN 'Fuehr' END,
                      CASE WHEN bikegraph.tr_fehlt(x.verkehrsri) THEN 'Verkehrsri' END], ' Attribut fehlt aufgrund von ' || x.kommentar_art || '; ')
                      || ' Attribut fehlt aufgrund von ' || x.kommentar_art, ' Attribut fehlt aufgrund von ' || x.kommentar_art), '') END)) AS attrs
FROM fertig x
)
SELECT reihe, id, gruppe, geom_hex, attrs FROM ausgabe;
\endif

\if :s_abschluss
BEGIN;
DROP TABLE IF EXISTS bikegraph.input_raw;
CREATE TABLE bikegraph.input_raw AS
SELECT row_number() OVER (ORDER BY a.reihe, a.id) AS n, a.gruppe AS trace_group, a.id AS input_ref, a.geom_hex, a.attrs
FROM bikegraph.input_raw_ungeordnet a;
DROP TABLE bikegraph.input_raw_ungeordnet;
COMMIT;
SELECT trace_group, count(*) AS objekte FROM bikegraph.input_raw GROUP BY 1 ORDER BY 1;
\endif
