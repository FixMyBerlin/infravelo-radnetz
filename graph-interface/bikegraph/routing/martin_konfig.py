"""Martin-Konfiguration des Routing-Matchers (routing_qa.sh) aus den Tabellen in routing_martin: ../martin/routing_qa.yaml
(Ebenen mit den Spalten aus der Datenbank) und ../martin/styles/routing_qa.json (MapLibre-Style). Eigene Konfiguration,
damit die Pipeline-Konfiguration rvn_matching.yaml ohne die Tabellen des Routing-Matchers startet.
Aufruf (nach routing_qa.sh): MATCHING_PG=... PGPASSWORD=... python3 graph-interface/bikegraph/routing/martin_konfig.py"""
import json
import os

import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
MARTIN = os.path.join(HERE, "..", "martin")
EBENEN = [  # (Tabelle, Geometrietyp, minzoom)
    ("routing_radwege", "LINESTRING", 12),
    ("routing_wege", "LINESTRING", 13),
    ("routing_strassen", "LINESTRING", 13),
    ("routing_rvn_diff", "MULTILINESTRING", None),
    ("routing_routen", "LINESTRING", 12),
    ("routing_crossings", "MULTILINESTRING", 12),
    ("routing_unbequem", "LINESTRING", None),
    ("routing_luecken", "POINT", None),
    ("routing_rvn", "LINESTRING", None),
    ("routing_diff_v7", "LINESTRING", None),
    ("routing_urteil_routing", "LINESTRING", None),
    ("routing_urteil_v7", "LINESTRING", None),
    ("routing_urteil_grenzfall", "LINESTRING", None),
    ("routing_haltestellen", "POINT", None),
]
TYP = {"integer": "int4", "bigint": "int8", "numeric": "numeric", "text": "text", "character varying": "text", "boolean": "bool",
       "double precision": "float8"}

con = psycopg2.connect(os.environ["MATCHING_PG"])
cur = con.cursor()
namen = [t for t, _, _ in EBENEN]
y = ["# Martin: Ebenen des Routing-Matchers (routing/README.md), Schema routing_martin (routing/martin.sql, von routing_qa.sh).",
     "# Erzeugt von routing/martin_konfig.py aus den Spalten der Tabellen. Eigene Konfiguration neben rvn_matching.yaml: Martin",
     "# startet nur, wenn alle Tabellen existieren, also erst routing_qa.sh laufen lassen. Start (Verbindung aus DATABASE_URL):",
     "#   docker run -d --name routing-qa-martin --network host -e DATABASE_URL=postgresql://USER:PASS@localhost:5433/postgres \\",
     "#     -v \"$PWD/graph-interface/bikegraph/martin:/cfg:ro\" ghcr.io/maplibre/martin:latest --config /cfg/routing_qa.yaml",
     "# Vorschau: http://localhost:3001/ · Kacheln: http://localhost:3001/{" + ",".join(namen) + "}/{z}/{x}/{y}",
     "listen_addresses: '0.0.0.0:3001'",
     "# Kein Kachel-Cache: routing_qa.sh baut die Tabellen neu",
     "cache_size_mb: 0",
     "web_ui: enable-for-all",
     "postgres:",
     "  connection_string: ${DATABASE_URL}",
     "  auto_publish: false",
     "  tables:"]
for t, gt, mz in EBENEN:
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'routing_martin' AND table_name = %s "
                "ORDER BY ordinal_position", (t,))
    cols = [(c, TYP[d]) for c, d in cur.fetchall() if c not in ("id", "geom")]
    if not cols:
        raise SystemExit(f"Tabelle routing_martin.{t} fehlt: erst routing_qa.sh laufen lassen")
    y += [f"    {t}:", "      schema: routing_martin", f"      table: {t}", "      srid: 25833", "      geometry_column: geom",
          f"      geometry_type: {gt}", "      id_column: id"] + ([f"      minzoom: {mz}"] if mz else []) + ["      properties:"]
    y += [f"        {c}: {d}" for c, d in cols]
y += ["styles:", "  sources:", "    routing_qa: /cfg/styles/routing_qa.json", ""]
open(os.path.join(MARTIN, "routing_qa.yaml"), "w").write("\n".join(y))

FUEHR = ["match", ["get", "fuehr"], "Radweg", "#00a046", "Geschützter Radfahrstreifen", "#00897b", "Radfahrstreifen", "#64dd17",
         "Schutzstreifen", "#c0ca33", "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)", "#6d4c41",
         "Fahrradstraße /-zone (Z 244)", "#1b5e20", "Gemeinsamer Geh- und Radweg mit Z240", "#26a69a",
         "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)", "#2979ff", "Mischverkehr mit motorisiertem Verkehr", "#ff9100",
         "Keine Radinfrastruktur vorhanden", "#ffd600", "Kreuzungsweg", "#d500f9", "#757575"]


def fuehr(feld):
    m = json.loads(json.dumps(FUEHR))
    m[1] = feld
    return m


def breite(a, b, z0=12, z1=17):
    return ["interpolate", ["linear"], ["zoom"], z0, a, z1, b]


def linie(t, farbe, w, **extra):
    paint = {"line-color": farbe, "line-width": w}
    paint.update(extra)
    return {"id": t, "type": "line", "source": t, "source-layer": t, "paint": paint, "layout": {"visibility": "none"}}


versatz = ["match", ["get", "ri"], 0, breite(1.5, 5, 12, 16), breite(-1.5, -5, 12, 16)]
schichten = [
    {"id": "basemap", "type": "raster", "source": "basemap"},
    linie("routing_strassen", ["case", ["==", ["get", "richtung"], "gesperrt"], "#ef9a9a", ["has", "zusatz"], "#bcaaa4", "#9e9e9e"], breite(0.5, 2, 13, 18)),
    linie("routing_wege", ["match", ["get", "highway"], "steps", "#7b1fa2", "elevator", "#7b1fa2", "#90caf9"], breite(0.5, 2, 13, 18)),
    linie("routing_radwege", fuehr(["coalesce", ["get", "fuehr0"], ["get", "fuehr1"]]), breite(1, 3)),
    linie("routing_rvn_diff", ["match", ["get", "art"], "entfernt", "#d50000", "gelöst", "#ff9100", "neu", "#00c853", "#000000"], breite(3, 9, 10, 17), **{"line-opacity": 0.8}),
    linie("routing_routen", FUEHR, ["interpolate", ["linear"], ["zoom"], 12, ["min", ["+", 1, ["*", 0.5, ["get", "routen"]]], 4],
                                    17, ["min", ["+", 2, ["*", 1.5, ["get", "routen"]]], 12]]),
    linie("routing_crossings", FUEHR, ["case", ["get", "lang"], breite(2, 6), breite(1, 4)], **{"line-dasharray": [2, 1]}),
    linie("routing_unbequem", ["match", ["get", "art"], "treppe", "#7b1fa2", "service", "#6d4c41", "baustelle", "#ff6d00", "brücke", "#d50000", "#000000"],
          breite(3, 8, 10, 17), **{"line-dasharray": [1, 1]}),
    linie("routing_rvn", ["match", ["get", "status"], "gleich", "#2e7d32", "anders", "#d50000", "#9e9e9e"], breite(2, 6), **{"line-offset": versatz}),
    linie("routing_diff_v7", ["match", ["get", "klasse"], "Rückfall (keine Radinfra)", "#9e9e9e", "anders, v7 = Henri", "#d50000", "#ff9100"],
          breite(2, 6, 10, 16), **{"line-offset": versatz}),
    linie("routing_urteil_routing", "#2e7d32", breite(3, 8, 10, 17), **{"line-offset": versatz}),
    linie("routing_urteil_v7", "#d50000", breite(3, 8, 10, 17), **{"line-offset": versatz}),
    linie("routing_urteil_grenzfall", ["match", ["get", "urteil"], "Grenzfall", "#ff9100", "TILDA-Daten", "#7b1fa2", "#9e9e9e"],
          breite(3, 8, 10, 17), **{"line-offset": versatz}),
    {"id": "routing_luecken", "type": "circle", "source": "routing_luecken", "source-layer": "routing_luecken",
     "paint": {"circle-color": ["match", ["slice", ["get", "ursache"], 0, 8], "entfernt", "#6a1b9a", "gesperrt", "#d50000", "Einbahn:", "#ff6d00", "#000000"],
               "circle-radius": breite(4, 9), "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5}, "layout": {"visibility": "none"}},
    {"id": "routing_haltestellen", "type": "circle", "source": "routing_haltestellen", "source-layer": "routing_haltestellen",
     "paint": {"circle-color": ["case", ["!", ["has", "streifen_20m"]], "#9e9e9e", ["in", "Radfahrstreifen", ["get", "streifen_20m"]], "#1565c0", "#00acc1"],
               "circle-radius": breite(3, 7), "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5}, "layout": {"visibility": "none"}},
]
quellen = {"basemap": {"type": "raster", "tiles": ["https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"], "tileSize": 256,
                       "attribution": "© OpenStreetMap contributors © CARTO"}}
for t in namen:
    quellen[t] = {"type": "vector", "url": f"http://localhost:3001/{t}"}
style = {"version": 8, "name": "Routing-Matcher (QA)", "center": [13.405, 52.52], "zoom": 12, "sources": quellen, "layers": schichten}
open(os.path.join(MARTIN, "styles", "routing_qa.json"), "w").write(json.dumps(style, ensure_ascii=False, indent=1))
print("geschrieben: martin/routing_qa.yaml, martin/styles/routing_qa.json:", ", ".join(namen))
