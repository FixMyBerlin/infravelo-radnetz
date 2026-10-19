#!/usr/bin/env python3
"""Erzeugt das QGIS-Projekt "Einrichtungsfahrbahnen Prüfung.qgz".

Zweck: die Kanten prüfen, bei denen die Regel "R/G-Kante ohne Freigabe in Gegenrichtung -> ri=1
entfällt" der alten Referenz widerspricht (`pruefen`, Gruppe C), sowie die Korrekturen aus
data/rvn_korrekturen.csv. Hintergrund: map-matching/docs/einrichtungsfahrbahnen.md, Abschnitt 2.4.

Voraussetzung: `validation/analyse_einrichtungsfahrbahnen.py` ist gelaufen.
Das Projekt verweist relativ auf die Dateien, es kopiert nichts.

Darstellung:
- R/G-Kanten mit Pfeilen in Fahrtrichtung (= Digitalisierungsrichtung, G-Kanten sind im RVN gedreht),
  Farbe nach Gruppe: A = Referenz ohne Radverkehr in ri=1, B = Zweirichtungsweg, C = Einrichtungsweg
- Referenz und neu (HMM): Farbe nach `fuehr`, ri = 0 rechts, ri = 1 links versetzt
- TILDA-Straßen: Einbahn mit Pfeilen in OSM-Richtung, Freigabe in Gegenrichtung (oneway_bicycle=no) grün
- TILDA-Radwege: Einrichtungs- und Zweirichtungswege getrennt eingefärbt
- Lesezeichen für jede zu prüfende Kante und jede Korrektur

Aufruf (QGIS-Python, aus processing/):
    QT_QPA_PLATFORM=offscreen /usr/bin/python3 qgis/erzeuge_einrichtungsfahrbahnen_projekt.py
"""

import csv
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsBookmark,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterLayer,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsRuleBasedRenderer,
    QgsSimpleMarkerSymbolLayerBase,
    QgsSingleSymbolRenderer,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from erzeuge_vergleichsprojekt import OFFSET_RI, OUT, fuehr_renderer, line_symbol

PROCESSING = Path(__file__).resolve().parents[1]
PROJECT = Path(__file__).resolve().parent / "Einrichtungsfahrbahnen Prüfung.qgz"
CORRECTIONS = PROCESSING / "data/rvn_korrekturen.csv"

SOURCES = {
    "analyse": OUT / "analysis/einrichtungsfahrbahnen.fgb",
    "referenz": OUT / "reference-legacy/snapping_network_enriched.fgb",
    "neu": OUT / "map-matching/network_enriched_hmm.fgb",
    "strassen": PROCESSING / "data/TILDA Straßen Berlin.fgb",
    "radwege": PROCESSING / "data/TILDA Radwege Berlin.fgb",
}

GROUPS = {
    "A": ("#1b9e77", "A: Referenz ohne Radverkehr in ri=1"),
    "B": ("#377eb8", "B: Zweirichtungsweg in ri=1 (bleibt)"),
    "C": ("#ff7f00", "C: Einrichtungsweg in ri=1 (prüfen)"),
}


def arrow_line(color: str, width: float, interval_mm: float = 8.0, opacity: float = 1.0) -> QgsLineSymbol:
    """Linie mit Pfeilspitzen in Linienrichtung."""
    sym = line_symbol(color, width, opacity=opacity)
    marker = QgsMarkerSymbol.createSimple({"color": color, "outline_style": "no", "size": str(width * 2.4 + 1.2)})
    marker.symbolLayer(0).setShape(QgsSimpleMarkerSymbolLayerBase.Shape.ArrowHeadFilled)
    arrows = QgsMarkerLineSymbolLayer(True, interval_mm)
    arrows.setSubSymbol(marker)
    sym.appendSymbolLayer(arrows)
    return sym


def vector(path: Path, name: str, subset: str | None = None) -> QgsVectorLayer:
    if not path.exists():
        raise SystemExit(f"Datei fehlt: {path} (zuerst validation/analyse_einrichtungsfahrbahnen.py ausführen)")
    lyr = QgsVectorLayer(str(path), name, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"Ebene ungültig: {path}")
    if subset:
        lyr.setSubsetString(subset)
    return lyr


def label(lyr: QgsVectorLayer, expression: str):
    settings = QgsPalLayerSettings()
    settings.fieldName = expression
    settings.isExpression = True
    settings.placement = QgsPalLayerSettings.Placement.Line
    fmt = QgsTextFormat()
    fmt.setSize(8)
    fmt.buffer().setEnabled(True)
    settings.setFormat(fmt)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    lyr.setLabelsEnabled(True)


def bookmark(project: QgsProject, lyr: QgsVectorLayer, element_nr: str, name: str, group: str):
    feats = list(lyr.getFeatures(QgsFeatureRequest().setFilterExpression(f"\"element_nr\" = '{element_nr}'")))
    if not feats:
        return
    box = feats[0].geometry().boundingBox()
    for f in feats[1:]:
        box.combineExtentWith(f.geometry().boundingBox())
    box.grow(80)
    bm = QgsBookmark()
    bm.setName(name)
    bm.setGroup(group)
    bm.setExtent(QgsReferencedRectangle(box, project.crs()))
    project.bookmarkManager().addBookmark(bm)


def main():
    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:25833"))
    project.setTitle("Einrichtungsfahrbahnen: Regel gegen Referenz prüfen")
    root = project.layerTreeRoot()

    corrections = []
    with open(CORRECTIONS, encoding="utf-8") as f:
        corrections = list(csv.DictReader(line for line in f if not line.startswith("#")))
    corr_ids = ", ".join(f"'{c['element_nr']}'" for c in corrections) or "''"

    pruefen = vector(SOURCES["analyse"], "Prüfen: Regel verwirft ri=1, Referenz hat Einrichtungsweg", '"pruefen" = 1')
    pruefen.setRenderer(QgsSingleSymbolRenderer(line_symbol("#e31a1c", 4.0, opacity=0.35)))
    label(pruefen, "\"strassenname\" || ' ' || \"element_nr\"")

    korrektur = vector(SOURCES["analyse"], "Korrekturen aus data/rvn_korrekturen.csv", f'"element_nr" IN ({corr_ids})')
    korrektur.setRenderer(QgsSingleSymbolRenderer(line_symbol("#984ea3", 4.0, opacity=0.35)))
    label(korrektur, "\"strassenname\" || ' ' || \"element_nr\" || ' → ' || \"verkehrsrichtung\"")

    rg = vector(SOURCES["analyse"], "R/G-Kanten (Pfeil = Fahrtrichtung)", "\"verkehrsrichtung\" IN ('R', 'G')")
    rg.setRenderer(QgsCategorizedSymbolRenderer(
        "gruppe", [QgsRendererCategory(k, arrow_line(c, 0.6), n) for k, (c, n) in GROUPS.items()]))

    ref = vector(SOURCES["referenz"], "Referenz (Snapping, alt) – fuehr")
    ref.setRenderer(fuehr_renderer(0.9, OFFSET_RI))
    neu = vector(SOURCES["neu"], "Neu (HMM) – fuehr")
    neu.setRenderer(fuehr_renderer(0.9, OFFSET_RI))

    strassen = vector(SOURCES["strassen"], "TILDA-Straßen: Einbahn (Pfeil = OSM-Richtung)",
                      "\"oneway\" IN ('yes', 'yes_dual_carriageway')")
    root_rule = QgsRuleBasedRenderer.Rule(None)
    for expr, color, name in [
        ("\"oneway_bicycle\" = 'no'", "#4daf4a", "Einbahn, Radverkehr in Gegenrichtung frei"),
        ("\"oneway\" = 'yes_dual_carriageway'", "#636363", "Richtungsfahrbahn (yes_dual_carriageway)"),
        ("ELSE", "#000000", "Einbahn (yes)"),
    ]:
        rule = QgsRuleBasedRenderer.Rule(arrow_line(color, 0.3, 6.0, 0.8), 0, 0, None if expr == "ELSE" else expr, name)
        if expr == "ELSE":
            rule.setIsElse(True)
        root_rule.appendChild(rule)
    strassen.setRenderer(QgsRuleBasedRenderer(root_rule))

    radwege = vector(SOURCES["radwege"], "TILDA-Radwege nach Richtung")
    radwege.setRenderer(QgsCategorizedSymbolRenderer("oneway", [
        QgsRendererCategory("yes", arrow_line("#a65628", 0.3, 6.0, 0.8), "Einrichtung (yes)"),
        QgsRendererCategory("implicit_yes", arrow_line("#a65628", 0.3, 6.0, 0.8), "Einrichtung (implicit_yes)"),
        QgsRendererCategory("no", line_symbol("#e7298a", 0.5, opacity=0.8), "Zweirichtung (no)"),
        QgsRendererCategory("assumed_no", line_symbol("#e7298a", 0.5, opacity=0.8, dashed=True), "Zweirichtung (assumed_no)"),
        QgsRendererCategory("car_not_bike", line_symbol("#e7298a", 0.5, opacity=0.8), "car_not_bike"),
    ]))

    alle = vector(SOURCES["analyse"], "RVN-Kanten")
    alle.setRenderer(QgsSingleSymbolRenderer(line_symbol("#9e9e9e", 0.25)))
    basemap = QgsRasterLayer(
        "type=xyz&url=https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png&zmax=19&zmin=0",
        "Hintergrund (CARTO Positron, © OSM-Mitwirkende)",
        "wms",
    )

    for lyr in (pruefen, korrektur, rg, ref, neu, strassen, radwege, alle, basemap):
        project.addMapLayer(lyr, False)
    g_check = root.addGroup("Prüfung")
    for lyr in (pruefen, korrektur, rg):
        g_check.addLayer(lyr)
    g_cmp = root.addGroup("Ergebnisse (ri = 0 rechts, ri = 1 links versetzt)")
    g_cmp.addLayer(ref)
    g_cmp.addLayer(neu).setItemVisibilityChecked(False)
    g_tilda = root.addGroup("TILDA (alte Daten)")
    g_tilda.addLayer(strassen)
    g_tilda.addLayer(radwege)
    g_base = root.addGroup("Grundlage")
    g_base.addLayer(alle)
    g_base.addLayer(basemap)

    for f in sorted(pruefen.getFeatures(), key=lambda f: f["strassenname"] or ""):
        bookmark(project, pruefen, f["element_nr"], f"{f['strassenname']} {f['element_nr']}", "Prüfen (Gruppe C)")
    for c in corrections:
        bookmark(project, korrektur, c["element_nr"], f"{c['element_nr']}: {c['begruendung']}", "Korrekturen")

    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(alle.extent(), project.crs()))
    if not project.write(str(PROJECT)):
        raise SystemExit(f"Projekt konnte nicht geschrieben werden: {PROJECT}")
    print(f"Geschrieben: {PROJECT} ({pruefen.featureCount()} zu prüfen, {korrektur.featureCount()} Korrekturen)")
    app.exitQgis()


if __name__ == "__main__":
    main()
