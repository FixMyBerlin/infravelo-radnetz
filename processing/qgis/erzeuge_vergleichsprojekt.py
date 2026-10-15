#!/usr/bin/env python3
"""Erzeugt das QGIS-Projekt "Map-Matching Vergleich.qgz" (neu: HMM, Referenz: Snapping, gematchte TILDA-Wege).

Das Projekt verweist relativ auf die aktuellen Dateien in output/, es kopiert nichts.
Nach einem neuen Lauf (`map-matching run --eval`) zeigt es automatisch den neuen Stand.

Darstellung:
- beide Fahrtrichtungen seitlich versetzt (ri = 0 rechts, ri = 1 links der Digitalisierungsrichtung)
- Neu (HMM): breite Linie, Farbe nach `fuehr`
- Referenz: schmale Linie gleicher Palette in der Mitte der neuen Linie;
  sieht man eine andersfarbige Mittellinie, weichen beide ab
- Abweichungen `fuehr`: roter Rand unter der neuen Linie
- TILDA gematcht: tatsächliche Lage der TILDA-Kanten, gleiche Palette, gestrichelt

Aufruf (QGIS-Python, aus processing/):
    QT_QPA_PLATFORM=offscreen /usr/bin/python3 qgis/erzeuge_vergleichsprojekt.py
"""

from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsBookmark,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsLineSymbol,
    QgsProject,
    QgsProperty,
    QgsRasterLayer,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSymbolLayer,
    QgsVectorLayer,
)

PROCESSING = Path(__file__).resolve().parents[1]
OUT = PROCESSING / "output"
PROJECT = Path(__file__).resolve().parent / "Map-Matching Vergleich.qgz"

SOURCES = {
    "neu": OUT / "map-matching/network_enriched_hmm.fgb",
    "referenz": OUT / "reference-legacy/snapping_network_enriched.fgb",
    "abweichungen": OUT / "map-matching/evaluation/primaer_snapping/disagreements.fgb",
    "tilda": OUT / "map-matching/matched_tilda_ways.fgb",
    "rvn": OUT / "rvn/vorrangnetz_details_combined_rvn.fgb",
}

# fuehr -> Farbe (gleiche Palette in allen Ebenen)
FUEHR_COLORS = {
    "Geschützter Radfahrstreifen": "#08306b",
    "Radfahrstreifen": "#1f78b4",
    "Radfahrstreifen mit Linienverkehr frei (Z237 mit Z1026-32)": "#6a3d9a",
    "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)": "#e7298a",
    "Schutzstreifen": "#7fc8f8",
    "Fahrradstraße /-zone (Z 244)": "#1b9e77",
    "Radweg": "#ff7f00",
    "Gemeinsamer Geh- und Radweg mit Z240": "#a6611a",
    'Gehweg mit Zusatzzeichen "Radverkehr frei" (Z239 mit Z1022-10)': "#fdbf6f",
    'Fußgängerzone "Radverkehr frei" (Z242 mit Z1022-10)': "#f781bf",
    "Kreuzungsweg": "#e6c200",
    "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)": "#a6d96a",
    "Mischverkehr mit motorisiertem Verkehr": "#737373",
    "Keine Radinfrastruktur vorhanden": "#d9d9d9",
    "[TODO] Klärung notwendig": "#000000",
    "[TODO] Führung fehlt": "#000000",
}
OTHER_COLOR = "#ff00ff"

# Versatz je Fahrtrichtung in mm (positiv = rechts der Linienrichtung, per Render-Test geprüft)
OFFSET_RI = 'CASE WHEN "ri" = 1 THEN -1.3 ELSE 1.3 END'


def line_symbol(color: str, width: float, offset_expr: str | None = None, dashed: bool = False, opacity: float = 1.0) -> QgsLineSymbol:
    sym = QgsLineSymbol.createSimple(
        {"color": color, "width": str(width), "capstyle": "flat", "line_style": "dash" if dashed else "solid"}
    )
    sym.setOpacity(opacity)
    if offset_expr:
        sym.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.Offset, QgsProperty.fromExpression(offset_expr))
    return sym


def fuehr_renderer(width: float, offset_expr: str | None = None, dashed: bool = False, opacity: float = 1.0) -> QgsCategorizedSymbolRenderer:
    cats = []
    for value, color in FUEHR_COLORS.items():
        none_dashed = dashed or value == "Keine Radinfrastruktur vorhanden"
        cats.append(QgsRendererCategory(value, line_symbol(color, width, offset_expr, none_dashed, opacity), value))
    cats.append(QgsRendererCategory(None, line_symbol(OTHER_COLOR, width, offset_expr, dashed, opacity), "sonstiger Wert"))
    return QgsCategorizedSymbolRenderer("fuehr", cats)


def vector(key: str, name: str) -> QgsVectorLayer:
    path = SOURCES[key]
    if not path.exists():
        raise SystemExit(f"Datei fehlt: {path} (zuerst `map-matching run --eval` ausführen)")
    lyr = QgsVectorLayer(str(path), name, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"Ebene ungültig: {path}")
    return lyr


def main():
    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:25833"))
    project.setTitle("Map-Matching Vergleich: HMM neu gegen Snapping-Referenz")
    root = project.layerTreeRoot()

    ref = vector("referenz", "Referenz (Snapping, alt) – Mittellinie")
    ref.setRenderer(fuehr_renderer(0.35, OFFSET_RI))
    neu = vector("neu", "Neu (HMM) – fuehr")
    neu.setRenderer(fuehr_renderer(1.2, OFFSET_RI))
    abw = vector("abweichungen", "Abweichungen fuehr (neu ≠ Referenz)")
    abw.setRenderer(QgsSingleSymbolRenderer(line_symbol("#ff0000", 2.6, OFFSET_RI, opacity=0.5)))
    tilda = vector("tilda", "TILDA gematcht (tatsächliche Lage)")
    tilda.setRenderer(fuehr_renderer(0.5, dashed=True, opacity=0.85))
    rvn = vector("rvn", "RVN-Kanten")
    rvn.setRenderer(QgsSingleSymbolRenderer(line_symbol("#9e9e9e", 0.25)))
    basemap = QgsRasterLayer(
        "type=xyz&url=https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png&zmax=19&zmin=0",
        "Hintergrund (CARTO Positron, © OSM-Mitwirkende)",
        "wms",
    )

    for lyr in (ref, neu, abw, tilda, rvn, basemap):
        project.addMapLayer(lyr, False)
    g_cmp = root.addGroup("Vergleich auf dem RVN (ri = 0 rechts, ri = 1 links versetzt)")
    for lyr in (ref, neu, abw):
        g_cmp.addLayer(lyr)
    root.addGroup("TILDA").addLayer(tilda)
    g_base = root.addGroup("Grundlage")
    g_base.addLayer(rvn)
    g_base.addLayer(basemap)

    # Lesezeichen: Beispielkante (Geschützter Radfahrstreifen gegen Bussonderfahrstreifen)
    example = "43520039_42520034.01"
    feats = list(neu.getFeatures(QgsFeatureRequest().setFilterExpression(f"\"element_nr\" = '{example}'")))
    if feats:
        box = feats[0].geometry().boundingBox()
        for f in feats[1:]:
            box.combineExtentWith(f.geometry().boundingBox())
        box.grow(60)
        bm = QgsBookmark()
        bm.setName(f"Beispiel {example}: Geschützter Radfahrstreifen vor Bussonderfahrstreifen")
        bm.setExtent(QgsReferencedRectangle(box, project.crs()))
        project.bookmarkManager().addBookmark(bm)

    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(rvn.extent(), project.crs()))
    if not project.write(str(PROJECT)):
        raise SystemExit(f"Projekt konnte nicht geschrieben werden: {PROJECT}")
    print(f"Geschrieben: {PROJECT}")
    app.exitQgis()


if __name__ == "__main__":
    main()
