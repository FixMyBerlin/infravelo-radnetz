#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_aggregation.py
--------------------------------------------------------------------
Aggregiert mehrere Attributausprägungen innerhalb einer Kante auf eine finale Kante.
Erkennt signifikante Änderungen und führt regelbasierte Aggregation durch.

WICHTIG: Berücksichtigt die Linienrichtung (Attribut 'ri'). Kanten werden nur aggregiert,
wenn sie dieselbe element_nr UND dieselbe Richtung haben. Pro Straße entstehen normalerweise
zwei aggregierte Kanten (eine pro Fahrtrichtung), außer bei Einbahnstraßen.

Signifikante Änderungen:
- Jede Änderung der Benutzungspflicht und Nutzungsbeschränkung aufgrund baulicher Mängel
- Änderung der Ausprägung von Attributen auf mindestens 50m Länge: 
  Art der RVA, Breite (>30cm), Oberflächenmaterial, Protektion, Sicherheitstrennstreifen
  Diese Erkennung schreibt nur Log-Meldungen, in eine eigene Datei neben der Ausgabe
  (<Ausgabe>_signifikante_aenderungen.log). Die 50-m-Regel gilt für die Erfassung;
  die Aggregation nimmt alle Segmente der Kante, ohne Mindestlänge (siehe REQUIREMENTS.md).

Aggregationsregeln:
- Längster Abschnitt: Bezirk, Art der Radverkehrsführung, Benutzungspflicht, 
  Oberflächenmaterial, farbliche Beschichtung, Art der Protektion
- Schlechteste Ausprägung: Breite (kleinste), Sicherheitstrennstreifen, 
  Nutzungsbeschränkung (physische Sperre > Schadensschild > keine)

INPUT:
- output/snapping_converted_bikelanes.fgb (konvertierte Radverkehrsanlagen mit element_nr und ri)
- data/Berlin Bezirke.gpkg (Berliner Bezirksgrenzen für Bezirkszuweisung)

OUTPUT:
- output/aggregated_rvn_final.gpkg (finale aggregierte Netzwerkdaten als GeoPackage)
  - Layer "hinrichtung": Kanten mit ri=0 
  - Layer "gegenrichtung": Kanten mit ri=1
- output/aggregated_rvn_final_signifikante_aenderungen.log (eine Zeile je Kante mit signifikanten Änderungen)
"""
import argparse, sys
from pathlib import Path
import os, logging
import pandas as pd
import geopandas as gpd
from shapely.ops import linemerge
from shapely.geometry import LineString, MultiLineString
from helpers.progressbar import print_progressbar
from helpers.district_assignment import assign_district_to_edges
from helpers.globals import DEFAULT_CRS
from helpers.tilda_link_generator import generate_aggregation_tilda_link, generate_tilda_mapillary_link


# -------------------------------------------------------------- Konstanten --
# Minimale Länge für signifikante Änderungen (in Metern)
MIN_SIGNIFICANT_LENGTH = 50.0

# Minimale Breitenänderung für Signifikanz (in Metern)
MIN_SIGNIFICANT_WIDTH_CHANGE = 0.3

# Attribute die bei "Keine Radinfrastruktur vorhanden" auf NULL gesetzt werden
# (Segment-Attribute ohne 'ri' und 'fuehr')
NULL_ATTRIBUTES_KEINE_RADINFRA = [
    'ofm', 'protek', 'pflicht', 'breite', 'farbe', 
    'verkehrsri', 'trennstreifen', 'nutz_beschr', 'Kommentar'
]

# Attribute für regelbasierte Aggregation
LONGEST_SECTION_ATTRIBUTES = [
    "bezirk", "fuehr", "pflicht", "ofm", "farbe", "protek"
]

WORST_CASE_ATTRIBUTES = {
    "breite": "min",  # Kleinste Breite
    "trennstreifen": "worst_trennstreifen",  # Spezielle Logik
    "nutz_beschr": "worst_nutz_beschr"  # Spezielle Logik
}

# Attribute mit einer weiteren Spalte <attr>_anteile: Aufteilung der Kante auf die Ausprägungen (siehe add_shares).
# Die Spalten ändern keinen Wert.
SHARE_ATTRIBUTES = [
    "fuehr", "verkehrsri", "pflicht", "breite", "ofm", "farbe", "protek", "trennstreifen", "nutz_beschr",
    "tilda_smoothness", "tilda_maxspeed",
]
SHARE_SUFFIX = "_anteile"
# Attribute, bei denen Kreuzungswege nicht zählen, außer die Kante besteht nur aus Kreuzungswegen
WITHOUT_CROSSINGS_ATTRIBUTES = ["breite", "tilda_maxspeed", "tilda_smoothness"]
# Name für Kreuzungswege (aus OSM und an Knotenpunkten konvertiert) in <attr>_anteile
CROSSING_LABEL = "Kreuzungsbereich"

# Hierarchie für Nutzungsbeschränkungen (schlechteste zuerst)
NUTZ_BESCHR_HIERARCHY = [
    "Physische Sperre",
    "Radverkehr nicht erlaubt",
    "Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden)",
    "keine"
]

# Hierarchie für Sicherheitstrennstreifen (schlechteste zuerst) 
TRENNSTREIFEN_HIERARCHY = [
    "nein",  # Worst case
    "ja",    # Best case
    "entfällt"
]

# Reihenfolge der Fahrqualität (beste zuerst) für `tilda_smoothness`: die Werte von TILDA (topic-docs, `smoothness`);
# TILDA fasst horrible, very_horrible und impassable zu very_bad zusammen
SMOOTHNESS_ORDER = [
    "excellent", "good", "intermediate", "bad", "very_bad"
]

# Hilfsspalten, die vor der Aggregation einmal berechnet und danach gelöscht werden (siehe add_helper_columns)
LENGTH_COLUMN = "_laenge_segment"
CROSSING_COLUMN = "_ist_kreuzungsweg"
HELPER_COLUMNS = [LENGTH_COLUMN, CROSSING_COLUMN]

# Logger für signifikante Änderungen: schreibt in eine eigene Datei neben der Ausgabe, nicht ins Terminal
CHANGES_LOGGER = logging.getLogger("signifikante_aenderungen")
CHANGES_LOG_SUFFIX = "_signifikante_aenderungen.log"

# Spalten, die nach der Aggregation gelöscht werden sollen
COLUMNS_TO_DROP = [
    "okstra_id", "existenz", "ist_radvorrangnetz", "elem_nr", "gisid", "gueltig_von", 
    "dnez__sdatenid", "str_bez", "Index", "strassenklasse", "sfid", "fid"
]

# Spaltenreihenfolge für finale Ausgabe (ohne geometry)
AGGREGATED_COLUMN_ORDER = [
    "afid",                   # 1. Aggregation FID
    "element_nr",             # 2. element_nr
    "beginnt_bei_vp",         # 3. beginnt_bei_vp
    "endet_bei_vp",           # 4. endet_bei_vp
    "Länge",                  # 5. Länge (gerundet, ohne Nachkommastellen)
    "ri",                     # 6. ri
    "verkehrsri",             # 7. verkehrsri
    "Bezirksnummer",          # 8. Bezirksnummer
    "strassenname",           # 9. Straßenname
    "fuehr",                  # 10. fuehr
    "pflicht",                # 11. pflicht
    "breite",                 # 12. breite
    "ofm",                    # 13. ofm
    "farbe",                  # 14. farbliche beschichtung
    "protek",                 # 15. protek
    "trennstreifen",          # 16. trennstreifen
    "nutz_beschr",            # 17. nutzungsbeschränkung
    "Kommentar",              # 18. Kommentar
]


AGGREGATED_COLUMN_ORDER = [
    c for col in AGGREGATED_COLUMN_ORDER
    for c in ([col, col + SHARE_SUFFIX] if col in SHARE_ATTRIBUTES else [col])
]


# --------------------------------------------------------- Hilfsfunktionen --
def lines_from_geom(g):
    """
    Gibt alle Linien einer Geometrie als Liste von LineStrings zurück.
    Falls MultiLineString, werden alle Teile einzeln zurückgegeben.
    Falls LineString, wird eine Liste mit diesem einen Element zurückgegeben.
    """
    if isinstance(g, LineString):
        return [g]
    if isinstance(g, MultiLineString):
        return list(g.geoms)
    raise TypeError(f"Geometry {g.geom_type} nicht unterstützt")


def calculate_segment_length(geometry):
    """
    Berechnet die Länge eines Segments in Metern.
    """
    return geometry.length


def add_helper_columns(gdf):
    """
    Berechnet Länge und Kreuzungsweg-Kennung je Segment einmal für das ganze Netz (Spalten LENGTH_COLUMN und
    CROSSING_COLUMN), statt sie je Kante und Attribut neu zu berechnen. Die Spalten werden nach der Aggregation
    wieder entfernt (HELPER_COLUMNS).
    """
    gdf = gdf.copy()
    gdf[LENGTH_COLUMN] = gdf.geometry.length
    if 'fuehr' in gdf.columns:
        gdf[CROSSING_COLUMN] = gdf['fuehr'].map(is_kreuzungsweg).astype(bool)
    return gdf


def segment_lengths(segments_group):
    """Längen der Segmente (aus LENGTH_COLUMN, falls vorhanden) als numpy-Array in Zeilenreihenfolge."""
    if LENGTH_COLUMN in segments_group.columns:
        return segments_group[LENGTH_COLUMN].to_numpy()
    return segments_group.geometry.length.to_numpy()


def crossing_mask(segments_group):
    """Boolesche Series: Segment ist ein Kreuzungsweg (aus CROSSING_COLUMN, falls vorhanden)."""
    if CROSSING_COLUMN in segments_group.columns:
        return segments_group[CROSSING_COLUMN].astype(bool)
    return segments_group['fuehr'].apply(is_kreuzungsweg).astype(bool)


def format_values(values):
    """Werte für Log-Meldungen als einzeilige, kommagetrennte Liste."""
    return ", ".join(str(v) for v in values)


def find_worst_nutz_beschr(values):
    """
    Findet die schlechteste Nutzungsbeschränkung basierend auf der Hierarchie.
    """
    values = [v for v in values if pd.notna(v) and v is not None]
    if not values:
        return "keine"
    
    # Ein Wert kann mehrere Beschränkungen nebeneinander tragen ("…; Radverkehr nicht erlaubt (…)"):
    # der erste Wert, der die schlechteste Beschränkung enthält, gewinnt, mit allen seinen Teilen.
    for worst_option in NUTZ_BESCHR_HIERARCHY:
        for v in sorted(values, key=lambda x: (-str(x).count(";"), str(x))):
            if worst_option in str(v):
                return v
    
    # Fallback: Ersten verfügbaren Wert verwenden
    return values[0]


def find_worst_trennstreifen(values):
    """
    Findet die schlechteste Trennstreifen-Ausprägung basierend auf der Hierarchie.
    Regel: "nein" vor "ja" vor "entfällt"
    """
    values = [v for v in values if pd.notna(v) and v is not None]
    if not values:
        return "entfällt"
    
    for worst_option in TRENNSTREIFEN_HIERARCHY:
        if worst_option in values:
            return worst_option
    
    # Fallback: Ersten verfügbaren Wert verwenden
    return values[0]


def detect_significant_changes(segments_group):
    """
    Erkennt signifikante Änderungen innerhalb einer Kantengruppe.
    Gibt eine Liste von Änderungen zurück für Logging/Debugging.
    """
    changes = []
    
    # Prüfe Änderungen bei Benutzungspflicht
    pflicht_values = segments_group['pflicht'].dropna().unique()
    if len(pflicht_values) > 1:
        changes.append(f"Benutzungspflicht-Änderung: {format_values(pflicht_values)}")

    # Prüfe Änderungen bei Nutzungsbeschränkung
    nutz_values = segments_group['nutz_beschr'].dropna().unique()
    if len(nutz_values) > 1:
        changes.append(f"Nutzungsbeschränkung-Änderung: {format_values(nutz_values)}")

    # Prüfe Änderungen bei anderen Attributen auf 50m+ Abschnitten
    long_segments = segments_group[segment_lengths(segments_group) >= MIN_SIGNIFICANT_LENGTH]

    if len(long_segments) > 0:
        # Art der Radverkehrsführung
        fuehr_values = long_segments['fuehr'].dropna().unique()
        if len(fuehr_values) > 1:
            changes.append(f"RVA-Änderung auf {len(long_segments)} langen Segmenten: {format_values(fuehr_values)}")
        
        # Breite (Änderung >30cm)
        breite_values = long_segments['breite'].dropna()
        if len(breite_values) > 1:
            # Konvertiere zu numerischen Werten, falls als String gespeichert
            numeric_breite = pd.to_numeric(breite_values, errors='coerce').dropna()
            if len(numeric_breite) > 1:
                breite_range = numeric_breite.max() - numeric_breite.min()
                if breite_range > MIN_SIGNIFICANT_WIDTH_CHANGE:
                    changes.append(f"Breiten-Änderung >{MIN_SIGNIFICANT_WIDTH_CHANGE}m auf langen Segmenten: {breite_range:.2f}m")
        
        # Oberflächenmaterial
        ofm_values = long_segments['ofm'].dropna().unique()
        if len(ofm_values) > 1:
            changes.append(f"Oberflächenmaterial-Änderung: {format_values(ofm_values)}")

        # Protektion
        protek_values = long_segments['protek'].dropna().unique()
        if len(protek_values) > 1:
            changes.append(f"Protektion-Änderung: {format_values(protek_values)}")

        # Sicherheitstrennstreifen
        trenn_values = long_segments['trennstreifen'].dropna().unique()
        if len(trenn_values) > 1:
            changes.append(f"Trennstreifen-Änderung: {format_values(trenn_values)}")
    
    return changes


def is_kreuzungsweg(fuehr_value):
    """
    Prüft ob eine Führungsform ein Kreuzungsweg ist (inkl. konvertierte Varianten).
    
    Args:
        fuehr_value: Führungsform-String
        
    Returns:
        bool: True wenn es sich um einen Kreuzungsweg handelt
    """
    if pd.isna(fuehr_value):
        return False
    return str(fuehr_value).startswith("Kreuzungsweg")


def aggregate_by_longest_section(segments_group, attribute):
    """
    Aggregiert ein Attribut basierend auf dem längsten Abschnitt.
    """
    if attribute not in segments_group.columns:
        return None
    
    # Gruppiere Segmente nach Attributwert und summiere Längen (in Zeilenreihenfolge, wie bisher)
    value_lengths = {}
    for value, length in zip(segments_group[attribute].to_numpy(), segment_lengths(segments_group)):
        if pd.notna(value):
            if value not in value_lengths:
                value_lengths[value] = 0
            value_lengths[value] += length
    
    if not value_lengths:
        return None
    
    # Finde den Wert mit der längsten Gesamtlänge
    longest_value = max(value_lengths, key=value_lengths.get)
    return longest_value


def aggregate_fuehr_by_longest_section(segments_group):
    """
    Aggregiert das 'fuehr'-Attribut (Führungsform) basierend auf dem längsten Abschnitt.
    Spezielle Logik: "Kreuzungsweg" wird ausgeschlossen und nur gewählt, wenn keine
    andere Führungsform vorhanden ist.
    
    Args:
        segments_group: DataFrame-Gruppe mit Segmenten einer Kante
        
    Returns:
        String mit der dominanten Führungsform (exkl. Kreuzungsweg wenn möglich)
    """
    if 'fuehr' not in segments_group.columns:
        return None
    
    # Gruppiere Segmente nach Führungsform und summiere Längen (in Zeilenreihenfolge, wie bisher)
    value_lengths = {}
    for value, length in zip(segments_group['fuehr'].to_numpy(), segment_lengths(segments_group)):
        if pd.notna(value):
            if value not in value_lengths:
                value_lengths[value] = 0
            value_lengths[value] += length
    
    if not value_lengths:
        return None
    
    # Entferne alle Kreuzungsweg-Varianten aus der Auswahl (falls andere Werte existieren)
    filtered_lengths = {k: v for k, v in value_lengths.items() if not is_kreuzungsweg(k)}
    
    # Falls nach Filterung noch Werte vorhanden sind, wähle längsten
    if filtered_lengths:
        longest_value = max(filtered_lengths, key=filtered_lengths.get)
        
        # Logging, wenn Kreuzungsweg ignoriert wurde
        kreuzungsweg_variants = {k: v for k, v in value_lengths.items() if is_kreuzungsweg(k)}
        if kreuzungsweg_variants:
            kreuzungsweg_total_length = sum(kreuzungsweg_variants.values())
            total_length = sum(value_lengths.values())
            logging.debug(
                f"Kreuzungsweg-Varianten ({kreuzungsweg_total_length:.1f}m) ignoriert, "
                f"gewählt: {longest_value} ({filtered_lengths[longest_value]:.1f}m) "
                f"von insgesamt {total_length:.1f}m"
            )
        
        return longest_value
    
    # Fallback: Wenn nur Kreuzungsweg-Varianten vorhanden sind, verwende die längste
    kreuzungsweg_variants = {k: v for k, v in value_lengths.items() if is_kreuzungsweg(k)}
    if kreuzungsweg_variants:
        longest_kreuzungsweg = max(kreuzungsweg_variants, key=kreuzungsweg_variants.get)
        logging.debug(f"Nur Kreuzungsweg-Varianten vorhanden - verwende: {longest_kreuzungsweg}")
        return longest_kreuzungsweg
    
    # Sollte nie erreicht werden, aber sicherheitshalber
    return None


def append_comment(existing_comment, new_comment):
    """
    Ergänzt einen bestehenden Kommentar um einen neuen Text.
    Fügt "; " als Trennzeichen ein, wenn bereits ein Kommentar existiert.
    
    Args:
        existing_comment: Bestehender Kommentar (kann None oder leer sein)
        new_comment: Neuer Kommentar-Text zum Anhängen
        
    Returns:
        Kombinierter Kommentar-String
    """
    if existing_comment and pd.notna(existing_comment) and str(existing_comment).strip():
        return f"{existing_comment}; {new_comment}"
    return new_comment


def aggregate_breite_excluding_kreuzungsweg(segments_group):
    """
    Aggregiert die Breite (kleinster Wert) unter Ausschluss von Kreuzungsweg-Segmenten.
    
    Kreuzungswege haben oft schmale Breiten, die nicht repräsentativ für die gesamte
    Kante sind. Daher werden sie bei der Breitenaggregation ignoriert.
    
    Args:
        segments_group: DataFrame-Gruppe mit Segmenten einer Kante
        
    Returns:
        tuple: (aggregierte_breite, nur_kreuzungswege)
            - aggregierte_breite: Kleinste Breite der Nicht-Kreuzungsweg-Segmente oder None
            - nur_kreuzungswege: True wenn nur Kreuzungswege vorhanden waren
    """
    if 'breite' not in segments_group.columns:
        return None, False
    
    if 'fuehr' not in segments_group.columns:
        # Ohne fuehr-Spalte können wir Kreuzungswege nicht identifizieren
        # Fallback: normale min-Aggregation
        values = segments_group['breite'].dropna().tolist()
        if not values:
            return None, False
        numeric_values = pd.to_numeric(values, errors='coerce')
        numeric_values = numeric_values[~pd.isna(numeric_values)]
        return float(min(numeric_values)) if len(numeric_values) > 0 else None, False
    
    # Filtere Segmente die KEINE Kreuzungswege sind (inkl. konvertierte Varianten)
    non_kreuzungsweg_mask = ~crossing_mask(segments_group)
    non_kreuzungsweg_segments = segments_group[non_kreuzungsweg_mask]
    
    # Prüfe ob nur Kreuzungswege vorhanden sind
    if len(non_kreuzungsweg_segments) == 0:
        logging.debug("Nur Kreuzungswege vorhanden - Breite wird leer gelassen")
        return None, True
    
    # Extrahiere Breiten der Nicht-Kreuzungsweg-Segmente
    breite_values = non_kreuzungsweg_segments['breite'].dropna().tolist()
    if not breite_values:
        return None, False
    
    # Konvertiere zu numerischen Werten
    numeric_values = pd.to_numeric(breite_values, errors='coerce')
    numeric_values = numeric_values[~pd.isna(numeric_values)]
    
    if len(numeric_values) == 0:
        return None, False
    
    min_breite = float(min(numeric_values))
    
    # Logging wenn Kreuzungswege ignoriert wurden
    kreuzungsweg_count = (~non_kreuzungsweg_mask).sum()
    if kreuzungsweg_count > 0:
        logging.debug(
            f"Breite-Aggregation: {kreuzungsweg_count} Kreuzungsweg-Segment(e) ignoriert, "
            f"min. Breite aus {len(numeric_values)} Segment(en): {min_breite:.2f}m"
        )
    
    return min_breite, False


def aggregate_by_worst_case(segments_group, attribute, aggregation_type):
    """
    Aggregiert ein Attribut basierend auf dem schlechtesten Fall.
    
    Hinweis: Für 'breite' wird stattdessen aggregate_breite_excluding_kreuzungsweg
    verwendet, um Kreuzungswege auszuschließen.
    """
    if attribute not in segments_group.columns:
        return None
    
    values = segments_group[attribute].dropna().tolist()
    if not values:
        return None
    
    if aggregation_type == "min":
        # Kleinster numerischer Wert (für Breite)
        # HINWEIS: Für Breite sollte aggregate_breite_excluding_kreuzungsweg verwendet werden
        # Konvertiere zu numerischen Werten, falls als String gespeichert
        numeric_values = pd.to_numeric(values, errors='coerce')
        numeric_values = numeric_values[~pd.isna(numeric_values)]
        return float(min(numeric_values)) if len(numeric_values) > 0 else None
    
    elif aggregation_type == "worst_nutz_beschr":
        return find_worst_nutz_beschr(values)
    
    elif aggregation_type == "worst_trennstreifen":
        return find_worst_trennstreifen(values)
    
    else:
        raise ValueError(f"Unbekannter Aggregationstyp: {aggregation_type}")


def aggregate_tilda_attributes(segments_group, attribute):
    """
    Aggregiert TILDA-Attribute durch Kombination aller einzigartigen Werte mit Semikolon.
    Wird für alle Attribute verwendet, die mit 'tilda_' beginnen.
    
    Args:
        segments_group: DataFrame-Gruppe mit Segmenten einer Kante
        attribute: Name des TILDA-Attributs
        
    Returns:
        String mit allen einzigartigen Werten getrennt durch Semikolon, oder None
    """
    if attribute not in segments_group.columns:
        return None
    
    # Einzigartige nicht-leere Werte als Text; leere Strings sowie 'nan'/'none' (in jeder Schreibweise) zählen nicht.
    # Einfaches Python statt pandas-Operationen je Spalte: die Gruppen sind klein, pandas kostet hier nur Overhead.
    unique_values = set()
    for value in segments_group[attribute].to_numpy():
        if pd.isna(value):
            continue
        text = str(value)
        if text != '' and text.lower() not in ('nan', 'none'):
            unique_values.add(text)

    # Sortiert mit Semikolon kombinieren
    return ';'.join(sorted(unique_values)) if unique_values else None


def longest_smoothness(segments_group):
    """
    Fahrqualität (`tilda_smoothness`) mit dem größten Längenanteil an der Kante, wie die Bewertung des
    Radvorrangnetzes (infravelo-radnetz-bewertung, Annahme A17). Bei gleicher Länge zählt die schlechtere nach
    SMOOTHNESS_ORDER. Unbekannte Werte werden ignoriert.
    """
    if 'tilda_smoothness' not in segments_group.columns:
        return None
    rank = {value: index for index, value in enumerate(SMOOTHNESS_ORDER)}
    lengths = {}
    for value, length in zip(segments_group['tilda_smoothness'], segment_lengths(segments_group)):
        if value in rank:
            lengths[value] = lengths.get(value, 0) + length
    if not lengths:
        return None
    return max(lengths, key=lambda value: (lengths[value], rank[value]))


def highest_maxspeed(segments_group):
    """Höchste numerische `tilda_maxspeed` der Segmente einer Kante (km/h), sonst None.
    Werte über 200 sind Tippfehler in OSM (z. B. eine Telefonnummer im Tag) und zählen nicht."""
    if 'tilda_maxspeed' not in segments_group.columns:
        return None
    speeds = pd.to_numeric(segments_group['tilda_maxspeed'], errors='coerce').dropna()
    speeds = speeds[speeds <= 200]
    return int(speeds.max()) if len(speeds) > 0 else None

def _share_label(attr, value):
    if pd.isna(value):
        return "ohne Wert"
    if attr == "breite":
        number = pd.to_numeric(value, errors="coerce")
        if pd.notna(number):
            return f"{float(number):.2f} m".replace(".", ",")
    if attr == "tilda_maxspeed":
        return f"{value} km/h"
    if attr == "fuehr" and is_kreuzungsweg(value):
        return CROSSING_LABEL
    return str(value)


def _share_percent(share):
    percent = round(share * 100)
    return "<1 %" if percent == 0 else f"{percent} %"


def add_shares(aggregated, edge_group):
    """
    Ergänzt je Attribut aus SHARE_ATTRIBUTES `<attr>_anteile`: je Ausprägung der Anteil an der Länge der Segmente,
    in Klammern die Führungsformen bzw. „nicht gewertet, da Kreuzungsbereich“ bei Kreuzungswegen, wo sie nicht zählen
    (WITHOUT_CROSSINGS_ATTRIBUTES).
    Der Wert der Kante steht vorne, danach die übrigen Ausprägungen nach Anteil, z. B. für `breite`:
    „8 % 0,90 m (Radweg); 86 % 1,50 m (Radweg); 6 % 2,00 m (nicht gewertet, da Kreuzungsbereich)“.
    """
    lengths = dict(zip(edge_group.index, segment_lengths(edge_group)))
    total = sum(lengths.values())
    has_fuehr = "fuehr" in edge_group.columns
    segment_is_crossing = crossing_mask(edge_group) if has_fuehr else pd.Series(False, index=edge_group.index)
    for attr in SHARE_ATTRIBUTES:
        if attr not in edge_group.columns:
            continue
        if total <= 0:
            aggregated[attr + SHARE_SUFFIX] = None
            continue
        chosen = aggregated.get(attr)
        # Wie aggregate_breite_excluding_kreuzungsweg: Breiten von Kreuzungswegen zählen nicht, außer es gibt nur
        # Kreuzungswege (dann bleibt die Breite leer, bei einem einzelnen konvertierten Segment bleibt sie stehen)
        crossing = (segment_is_crossing.copy() if attr in WITHOUT_CROSSINGS_ATTRIBUTES
                    else pd.Series(False, index=edge_group.index))
        if crossing.all():
            crossing[:] = False
        entries = {}
        for idx, value, fuehr, fuehr_is_crossing in zip(
            edge_group.index, edge_group[attr],
            edge_group["fuehr"] if has_fuehr else [None] * len(edge_group), segment_is_crossing,
        ):
            excluded = bool(pd.notna(value) and crossing[idx])
            entry = entries.setdefault((_share_label(attr, value), excluded), {"length": 0.0, "fuehr": []})
            entry["length"] += lengths[idx]
            fuehr_label = CROSSING_LABEL if fuehr_is_crossing else fuehr
            if attr != "fuehr" and pd.notna(fuehr) and fuehr_label not in entry["fuehr"]:
                entry["fuehr"] = sorted(entry["fuehr"] + [fuehr_label])
        parts = []
        chosen_label = _share_label(attr, chosen) if pd.notna(chosen) else None
        for (label, excluded), entry in sorted(
            entries.items(), key=lambda item: (item[0] != (chosen_label, False), -item[1]["length"])
        ):
            details = [" / ".join(entry["fuehr"])] if entry["fuehr"] and not excluded else []
            if excluded:
                details.append(f"nicht gewertet, da {CROSSING_LABEL}")
            text = f"{_share_percent(entry['length'] / total)} {label}"
            parts.append(f"{text} ({', '.join(details)})" if details else text)
        aggregated[attr + SHARE_SUFFIX] = "; ".join(parts)
    return aggregated


def aggregate_edge_group(edge_group):
    """
    Aggregiert alle Segmente einer Kante (gleiche element_nr und ri) zu einer finalen Kante.
    Wendet die definierten Aggregationsregeln an.
    """
    if len(edge_group) == 1:
        # Nur ein Segment - keine Aggregation nötig
        aggregated = edge_group.iloc[0].copy()
        
        # Prüfe ob Einzelsegment ein Kreuzungsweg ist → Breite entfernen und Kommentar ergänzen
        if 'fuehr' in aggregated and aggregated.get('fuehr') == "Kreuzungsweg":
            aggregated['breite'] = None
            existing_comment = aggregated.get('Kommentar', None)
            aggregated['Kommentar'] = append_comment(
                existing_comment,
                "Breite nicht ermittelbar (nur Kreuzungswege vorhanden)"
            )
            logging.debug(f"Einzelsegment Kreuzungsweg: Breite entfernt, Kommentar ergänzt")
    else:
        # Basis-Informationen der Kante übernehmen (erste Zeile)
        aggregated = edge_group.iloc[0].copy()
        
        # Geometrie zusammenführen
        
        # Extrahiere alle LineString-Komponenten
        all_lines = []
        for geom in edge_group.geometry:
            all_lines.extend(lines_from_geom(geom))
        
        merged_geom = linemerge(all_lines)
        aggregated['geometry'] = merged_geom
        
        # Signifikante Änderungen erkennen
        # Nur ins Log der signifikanten Änderungen (Datei), nicht ins Terminal
        if CHANGES_LOGGER.isEnabledFor(logging.INFO):
            changes = detect_significant_changes(edge_group)
            if changes:
                element_nr = aggregated.get('element_nr', 'unknown')
                ri = aggregated.get('ri', 'unknown')
                CHANGES_LOGGER.info(f"Kante {element_nr} (Richtung: {ri}): {'; '.join(changes)}")
        
        # Spezielle Behandlung für 'fuehr' (Führungsform) mit Kreuzungsweg-Ausschluss
        if 'fuehr' in edge_group.columns:
            aggregated['fuehr'] = aggregate_fuehr_by_longest_section(edge_group)
        
        # Attribute nach "längster Abschnitt" aggregieren (außer 'fuehr', das bereits behandelt wurde)
        for attr in LONGEST_SECTION_ATTRIBUTES:
            if attr in edge_group.columns and attr != 'fuehr':
                aggregated[attr] = aggregate_by_longest_section(edge_group, attr)
        
        # Attribute nach "schlechtestem Fall" aggregieren
        # Spezielle Behandlung für Breite: Kreuzungswege ausschließen
        if 'breite' in edge_group.columns:
            breite_value, nur_kreuzungswege = aggregate_breite_excluding_kreuzungsweg(edge_group)
            aggregated['breite'] = breite_value
            if nur_kreuzungswege:
                # Kommentar ergänzen wenn nur Kreuzungswege vorhanden waren
                existing_comment = aggregated.get('Kommentar', None)
                aggregated['Kommentar'] = append_comment(
                    existing_comment,
                    "Breite nicht ermittelbar (nur Kreuzungswege vorhanden)"
                )
                logging.debug(f"Kante mit nur Kreuzungswegen: Kommentar ergänzt")
        
        # Andere Worst-Case-Attribute aggregieren (ohne Breite, da oben behandelt)
        for attr, agg_type in WORST_CASE_ATTRIBUTES.items():
            if attr in edge_group.columns and attr != 'breite':
                aggregated[attr] = aggregate_by_worst_case(edge_group, attr, agg_type)
        
        # TILDA-Attribute durch Semikolon-Kombination aggregieren (dynamisch erkannt)
        tilda_attributes = [col for col in edge_group.columns
                            if col.startswith('tilda_') and col not in ('tilda_maxspeed', 'tilda_smoothness')]
        for attr in tilda_attributes:
            aggregated[attr] = aggregate_tilda_attributes(edge_group, attr)

    # Ein Wert je Kante und Richtung (auch bei Einzelsegmenten), ohne Kreuzungswege wie bei `fuehr`
    without_crossings = edge_group
    if 'fuehr' in edge_group.columns:
        non_crossings = edge_group[~crossing_mask(edge_group)]
        if len(non_crossings) > 0:
            without_crossings = non_crossings
    if 'tilda_maxspeed' in edge_group.columns:
        aggregated['tilda_maxspeed'] = highest_maxspeed(without_crossings)
    if 'tilda_smoothness' in edge_group.columns:
        aggregated['tilda_smoothness'] = longest_smoothness(without_crossings)
    
    aggregated = add_shares(aggregated, edge_group)

    # Berechne die Länge für ALLE Kanten (Einzelsegmente und aggregierte Kanten)
    aggregated['Länge'] = int(round(calculate_segment_length(aggregated.geometry)))
    
    # Regeneriere tilda_link für die aggregierte Geometrie
    # (tilda_link sollte auf den Mittelpunkt der aggregierten Geometrie zeigen)
    if 'tilda_id' in aggregated and aggregated['tilda_id']:
        tilda_id_value = str(aggregated['tilda_id'])
        # Nur generieren wenn tilda_id vorhanden und nicht leer/None
        if tilda_id_value and tilda_id_value.lower() not in ['none', 'nan', '']:
            aggregated['tilda_link'] = generate_aggregation_tilda_link(tilda_id_value, aggregated.geometry)
    
    # Generiere tilda_link_mapillary basierend auf verfügbaren Mapillary-Attributen
    aggregated['tilda_link_mapillary'] = generate_tilda_mapillary_link(aggregated, aggregated.geometry)
    
    # Zusätzliche Metadaten
    # DEBUG 
    # aggregated['segments_count'] = len(edge_group)
    # aggregated['total_length'] = sum(calculate_segment_length(geom) for geom in edge_group.geometry)
    # aggregated['has_significant_changes'] = len(changes) > 0
    
    return aggregated


def aggregate_network(gdf):
    """
    Aggregiert das gesamte Netzwerk nach element_nr und Richtung (ri).
    Jede Kombination aus element_nr und ri wird zu einer finalen Kante zusammengeführt.
    Berücksichtigt die Linienrichtung, sodass pro Straße zwei aggregierte Kanten entstehen
    (eine pro Fahrtrichtung), außer bei Einbahnstraßen.
    """
    aggregated_edges = []
    
    # Prüfen, ob Richtungsattribut vorhanden ist
    if 'ri' not in gdf.columns:
        logging.warning("Attribut 'ri' (Richtung) fehlt! Aggregiere nur nach element_nr.")
        # Fallback: Gruppiere nur nach element_nr
        grouped = list(gdf.groupby('element_nr'))
    else:
        # Gruppiere nach element_nr UND Richtung (ri)
        grouped = list(gdf.groupby(['element_nr', 'ri']))
    
    total_groups = len(grouped)
    
    logging.info(f"Aggregiere {len(gdf)} Segmente in {total_groups} Richtungs-Kanten...")

    # Fortschrittsanzeige etwa alle 1 % statt nach jeder Kante (Ausgabe ins Terminal kostet Zeit)
    progress_step = max(1, total_groups // 100)
    debug_enabled = logging.getLogger().isEnabledFor(logging.DEBUG)

    for idx, (group_key, edge_group) in enumerate(grouped, 1):
        # Aggregiere die Segmente der aktuellen Kante mit gleicher Richtung
        aggregated_edge = aggregate_edge_group(edge_group)
        aggregated_edges.append(aggregated_edge)

        # Erweiterte Logging-Info bei Richtungsgruppierung
        if debug_enabled and 'ri' in gdf.columns:
            element_nr, ri = group_key
            logging.debug(f"Aggregiere element_nr={element_nr}, ri={ri}: {len(edge_group)} Segmente")

        if idx % progress_step == 0 or idx == total_groups:
            print_progressbar(idx, total_groups, prefix="Aggregiere: ")
    
    # Erstelle neues GeoDataFrame aus aggregierten Kanten
    result_gdf = gpd.GeoDataFrame(aggregated_edges, geometry="geometry", crs=gdf.crs)
    
    # Entferne unerwünschte Spalten (Hilfsspalten werden in process entfernt)
    columns_to_drop = [col for col in COLUMNS_TO_DROP if col in result_gdf.columns]
    if columns_to_drop:
        result_gdf = result_gdf.drop(columns=columns_to_drop)
        logging.info(f"Entfernte Spalten: {columns_to_drop}")
    
    # Prüfe und logge die Längenberechnung
    if 'Länge' in result_gdf.columns:
        total_length = result_gdf['Länge'].sum()
        avg_length = result_gdf['Länge'].mean()
        logging.info(f"Längenstatistiken: Gesamtlänge={total_length:.0f}m, Durchschnitt={avg_length:.0f}m")
    
    # Statistiken über Richtungsverteilung
    if 'ri' in result_gdf.columns:
        ri_counts = result_gdf['ri'].value_counts()
        logging.info(f"Richtungsverteilung nach Aggregation: {dict(ri_counts)}")
    
    logging.info(f"Aggregation abgeschlossen: {len(gdf)} Segmente → {len(result_gdf)} Richtungs-Kanten")
    
    return result_gdf


def normalize_radfahrstreifen_types(gdf):
    """
    Vereinheitlicht alle Varianten von Radfahrstreifen zu einem einzigen Typ "Radfahrstreifen".
    
    Konvertiert folgende Typen:
    - "Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)" → "Radfahrstreifen"
    - "Radfahrstreifen (OSM:Kurzer Schutzstreifen)" → "Radfahrstreifen"
    - "Radfahrstreifen" bleibt unverändert
    
    Args:
        gdf: GeoDataFrame mit aggregierten Kanten
        
    Returns:
        GeoDataFrame mit vereinheitlichten Radfahrstreifen-Typen
    """
    if 'fuehr' not in gdf.columns:
        logging.warning("Spalte 'fuehr' nicht gefunden - überspringe Normalisierung der Radfahrstreifen-Typen")
        return gdf
    
    # Arbeite mit einer Kopie
    gdf = gdf.copy()
    
    # Definiere die zu normalisierenden Radfahrstreifen-Varianten
    radfahrstreifen_variants = [
        "Radfahrstreifen (OSM:Schutzstreifen an Haltestelle)",
        "Radfahrstreifen (OSM:Kurzer Schutzstreifen)"
    ]
    
    # Zähle Vorkommen vor der Konvertierung
    variant_counts = {}
    for variant in radfahrstreifen_variants:
        count = (gdf['fuehr'] == variant).sum()
        if count > 0:
            variant_counts[variant] = count
    
    # Konvertiere alle Varianten zu "Radfahrstreifen"
    if variant_counts:
        logging.info("Vereinheitliche Radfahrstreifen-Typen zu 'Radfahrstreifen':")
        for variant, count in variant_counts.items():
            logging.info(f"  - {count}× '{variant}' → 'Radfahrstreifen'")
            gdf.loc[gdf['fuehr'] == variant, 'fuehr'] = 'Radfahrstreifen'
        
        # Zähle Gesamtzahl der Radfahrstreifen nach Normalisierung
        total_radfahrstreifen = (gdf['fuehr'] == 'Radfahrstreifen').sum()
        logging.info(f"Gesamt nach Normalisierung: {total_radfahrstreifen}× 'Radfahrstreifen'")
    else:
        logging.info("Keine Radfahrstreifen-Varianten zur Normalisierung gefunden")
    
    return gdf


def normalize_mischverkehr_types(gdf):
    """
    Entfernt die Breite bei allen Mischverkehr-Kanten nach der Aggregation.
    
    WICHTIG: Mischverkehr-Kanten sollen keine Breitenangabe haben.
    Dies ist notwendig, da bei der Aggregation die Breite von anderen Segmenten 
    übernommen werden könnte.
    
    Args:
        gdf: GeoDataFrame mit aggregierten Kanten
        
    Returns:
        GeoDataFrame ohne Breite bei Mischverkehr-Kanten
    """
    if 'fuehr' not in gdf.columns:
        logging.warning("Spalte 'fuehr' nicht gefunden - überspringe Mischverkehr-Verarbeitung")
        return gdf
    
    # Arbeite mit einer Kopie
    gdf = gdf.copy()
    
    # WICHTIG: Entferne Breite bei ALLEN Mischverkehr-Kanten nach der Aggregation
    # Dies ist notwendig, da bei der Aggregation die Breite von anderen Segmenten übernommen werden könnte
    if 'breite' in gdf.columns:
        mischverkehr_mask = gdf['fuehr'].str.contains('Mischverkehr', case=False, na=False)
        mischverkehr_with_breite = (mischverkehr_mask & gdf['breite'].notna()).sum()
        if mischverkehr_with_breite > 0:
            logging.info(f"Entferne Breite bei {mischverkehr_with_breite} Mischverkehr-Kanten nach Aggregation")
            gdf.loc[mischverkehr_mask, 'breite'] = None
    
    return gdf


def add_afid_column(gdf):
    """
    Fügt eine AFID-Spalte (Aggregation FID) mit fortlaufender Nummerierung hinzu.
    
    Args:
        gdf: GeoDataFrame mit den aggregierten Kanten
        
    Returns:
        GeoDataFrame mit AFID-Spalte
    """
    # Arbeite mit einer Kopie
    gdf = gdf.copy()
    
    # Füge AFID-Spalte hinzu (fortlaufende Nummer)
    gdf['afid'] = range(1, len(gdf) + 1)
    
    logging.info(f"AFID-Spalte hinzugefügt: {len(gdf)} Kanten nummeriert")
    
    return gdf


def reorder_aggregated_columns(gdf):
    """
    Ordnet die Spalten gemäß der definierten Reihenfolge für aggregierte Daten.
    
    Args:
        gdf: GeoDataFrame mit den aggregierten Kanten
        
    Returns:
        GeoDataFrame mit geordneten Spalten
    """
    # Arbeite mit einer Kopie
    gdf = gdf.copy()
    
    # Bestimme verfügbare Spalten in der gewünschten Reihenfolge (ohne geometry)
    available_columns = []
    for col in AGGREGATED_COLUMN_ORDER:
        if col in gdf.columns and col != 'geometry':
            available_columns.append(col)
    
    # Füge alle anderen Spalten hinzu, die nicht in AGGREGATED_COLUMN_ORDER definiert sind (ohne geometry)
    for col in gdf.columns:
        if col not in available_columns and col != 'geometry':
            available_columns.append(col)
    
    # Erstelle neues GeoDataFrame mit geordneten Spalten
    # Behalte die originale geometry-Spalte bei
    ordered_data = {}
    for col in available_columns:
        ordered_data[col] = gdf[col]
    
    # Erstelle GeoDataFrame mit originaler geometry
    result_gdf = gpd.GeoDataFrame(ordered_data, geometry=gdf.geometry, crs=gdf.crs)
    
    logging.info(f"Spalten für aggregierte Ausgabe geordnet: {len(available_columns) + 1} Spalten (inkl. geometry)")
    logging.debug(f"Aggregierte Spaltenreihenfolge: {available_columns + ['geometry']}")
    
    return result_gdf


# ------------------------------------------------------------- Hauptablauf --
def regional_output_file(p, clip_region):
    """Hängt bei regionalem Zuschnitt die Region an den Dateinamen an (vor der Endung)."""
    if not clip_region:
        return p
    p_parts = p.split('.')
    if len(p_parts) > 1:
        return f"{'.'.join(p_parts[:-1])}_{clip_region}.{p_parts[-1]}"
    return f"{p}_{clip_region}"


class _CountingFilter(logging.Filter):
    """Zählt die Meldungen, die durch einen Handler gehen."""
    def __init__(self):
        super().__init__()
        self.count = 0

    def filter(self, record):
        self.count += 1
        return True


def open_changes_log(output_file):
    """
    Leitet CHANGES_LOGGER in eine Datei neben der Ausgabe um (<Ausgabe ohne Endung>_signifikante_aenderungen.log,
    wird überschrieben). Gibt Pfad, Handler und Zähler zurück.
    """
    base, ext = os.path.splitext(output_file)
    log_path = f"{base}{CHANGES_LOG_SUFFIX}"
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    counter = _CountingFilter()
    handler.addFilter(counter)
    CHANGES_LOGGER.setLevel(logging.INFO)
    CHANGES_LOGGER.propagate = False
    CHANGES_LOGGER.addHandler(handler)
    return log_path, handler, counter


def process(input_path, output_path, crs, clip_region=None, data_dir="./data", assign_districts=True):
    """
    Hauptfunktion: Lädt angereicherte Netzwerkdaten und führt finale Aggregation durch.
    
    Args:
        input_path: Pfad zu angereicherten Netzwerkdaten
        output_path: Pfad für finale aggregierte Daten  
        crs: Ziel-Koordinatensystem (EPSG)
        clip_region: Regionale Beschränkung ('neukoelln', 'norden', 'sueden')
        data_dir: Verzeichnis mit den Eingabedateien
        assign_districts: Ob Bezirksnummern zugewiesen werden sollen
    """
    # Logging konfigurieren
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # ---------- Daten laden -------------------------------------------------
    def read(path):
        f, *layer = path.split(":")
        return gpd.read_file(f, layer=layer[0] if layer else None)

    logging.info("Lade angereicherte Netzwerkdaten...")
    gdf = read(input_path).to_crs(crs)
    
    logging.info(f"Eingangsdaten: {len(gdf)} Segmente geladen")
    
    # ---------- Führungstypen vereinheitlichen vor Aggregation -------------
    logging.info("Vereinheitliche Radfahrstreifen-Typen vor Aggregation...")
    gdf = normalize_radfahrstreifen_types(gdf)
    
    logging.info("Vereinheitliche Mischverkehr-Typen vor Aggregation...")
    gdf = normalize_mischverkehr_types(gdf)
    
    # Optional: Auf Gebiet zuschneiden
    if clip_region:
        from helpers.clipping import clip_to_region
        logging.info(f"Schneide Daten auf Region {clip_region} zu")
        gdf = clip_to_region(gdf, data_dir, crs, clip_region)
        logging.info(f"Nach {clip_region}-Clipping: {len(gdf)} Segmente")

    if gdf.empty:
        raise SystemExit("Abbruch: Keine Daten nach Clipping vorhanden")

    # Prüfen, ob Pflichtfelder vorhanden sind
    if 'element_nr' not in gdf.columns:
        sys.exit("Pflichtfeld 'element_nr' fehlt in den Eingangsdaten!")
    
    if 'ri' not in gdf.columns:
        logging.warning("Attribut 'ri' (Richtung) fehlt in den Eingangsdaten! Aggregation erfolgt nur nach element_nr.")
    else:
        logging.info(f"Richtungsattribut 'ri' gefunden. Verfügbare Richtungen: {sorted(gdf['ri'].dropna().unique())}")

    output_file = regional_output_file(output_path.split(":")[0], clip_region)
    changes_log_path, changes_handler, changes_counter = open_changes_log(output_file)

    # ---------- Aggregation durchführen ------------------------------------
    logging.info("Starte finale Aggregation...")
    gdf = add_helper_columns(gdf)
    try:
        result_gdf = aggregate_network(gdf)
    finally:
        CHANGES_LOGGER.removeHandler(changes_handler)
        changes_handler.close()
    result_gdf = result_gdf.drop(columns=[c for c in HELPER_COLUMNS if c in result_gdf.columns])
    logging.info(f"Signifikante Änderungen in {changes_counter.count} Kanten → {changes_log_path}")

    # ---------- Bezirkszuweisung durchführen -------------------------------
    if assign_districts:
        districts_path = os.path.join(data_dir, "Berlin Bezirke.gpkg")
        if os.path.exists(districts_path):
            logging.info("Starte Bezirkszuweisung...")
            result_gdf = assign_district_to_edges(result_gdf, districts_path, crs)
        else:
            logging.warning(f"Bezirksdatei nicht gefunden: {districts_path}. Überspringe Bezirkszuweisung.")

    # ---------- FID hinzufügen ----------------------------------------------
    logging.info("Füge AFID-Spalte hinzu...")
    result_gdf = add_afid_column(result_gdf)
    
    # ---------- Spalten ordnen ----------------------------------------------
    logging.info("Ordne Spalten für finale Ausgabe...")
    result_gdf = reorder_aggregated_columns(result_gdf)

    # ---------- NULL-Werte für "Keine Radinfrastruktur vorhanden" setzen ---
    logging.info("Setze alle relevanten Attribute auf NULL bei 'Keine Radinfrastruktur vorhanden'...")
    if 'fuehr' in result_gdf.columns:
        keine_radinfra_mask = result_gdf['fuehr'] == 'Keine Radinfrastruktur vorhanden'
        keine_radinfra_count = keine_radinfra_mask.sum()
        
        if keine_radinfra_count > 0:
            logging.info(f"  {keine_radinfra_count} Features mit 'Keine Radinfrastruktur vorhanden' gefunden")
            
            # Setze alle Attribute auf NULL und zähle Änderungen
            null_attrs = NULL_ATTRIBUTES_KEINE_RADINFRA + [
                a + SHARE_SUFFIX for a in SHARE_ATTRIBUTES if a in NULL_ATTRIBUTES_KEINE_RADINFRA
            ]
            for attr in null_attrs:
                if attr in result_gdf.columns:
                    attr_changes = (keine_radinfra_mask & result_gdf[attr].notna()).sum()
                    if attr_changes > 0:
                        result_gdf.loc[keine_radinfra_mask, attr] = None
                        logging.info(f"  → {attr}: {attr_changes} Werte auf NULL gesetzt")
        else:
            logging.info("  Keine Features mit 'Keine Radinfrastruktur vorhanden' gefunden")
    else:
        logging.warning("  Attribut 'fuehr' nicht gefunden - überspringe NULL-Setzung")

    # ---------- Ergebnis speichern ------------------------------------------
    p, *layer = output_path.split(":")
    layer = layer[0] if layer else "aggregated_edges"
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Path(p).unlink(missing_ok=True)
    
    # Füge Suffix für regionale Dateien hinzu
    p = regional_output_file(p, clip_region)

    # Nach Richtung filtern und in separate Layer schreiben, falls ri-Attribut vorhanden
    if 'ri' in result_gdf.columns:
        # Konvertiere zu GeoPackage für Multi-Layer-Support
        p_gpkg = p.replace('.fgb', '.gpkg') if p.endswith('.fgb') else p
        if not p_gpkg.endswith('.gpkg'):
            p_gpkg = f"{p_gpkg}.gpkg"
        
        # Filtere nach Richtungen und ordne Spalten für jeden Layer separat
        ri_0_gdf = result_gdf[result_gdf['ri'] == 0].copy()
        ri_1_gdf = result_gdf[result_gdf['ri'] == 1].copy()
        
        # Schreibe Hinrichtung (ri=0) mit separater FID-Nummerierung
        if len(ri_0_gdf) > 0:
            ri_0_gdf['afid'] = range(1, len(ri_0_gdf) + 1)  # Separate AFID-Nummerierung für Layer
            ri_0_gdf.to_file(p_gpkg, layer="hinrichtung", driver="GPKG")
            logging.info(f"✔  {len(ri_0_gdf)} Kanten Hinrichtung (ri=0) → {p_gpkg}:hinrichtung")
        
        # Schreibe Gegenrichtung (ri=1) mit separater FID-Nummerierung
        if len(ri_1_gdf) > 0:
            ri_1_gdf['afid'] = range(1, len(ri_1_gdf) + 1)  # Separate AFID-Nummerierung für Layer
            ri_1_gdf.to_file(p_gpkg, layer="gegenrichtung", driver="GPKG", mode='a')
            logging.info(f"✔  {len(ri_1_gdf)} Kanten Gegenrichtung (ri=1) → {p_gpkg}:gegenrichtung")
        
        print(f"✔  {len(result_gdf)} finale Kanten → {p_gpkg} (2 Layer: hinrichtung, gegenrichtung)")
        
        # Statistiken ausgeben
        ri_counts = result_gdf['ri'].value_counts()
        logging.info(f"Richtungsverteilung: ri=0 (Hinrichtung): {ri_counts.get(0, 0)}, ri=1 (Gegenrichtung): {ri_counts.get(1, 0)}")
        
    else:
        # Fallback: Speichere wie bisher als FlatGeoBuf
        result_gdf.to_file(p, layer=layer, driver="FlatGeoBuf")
        print(f"✔  {len(result_gdf)} finale Kanten → {p}:{layer}")


# ------------------------------------------------------------- CLI Wrapper --
if __name__ == "__main__":
    # Kommandozeilenargumente parsen
    ap = argparse.ArgumentParser(description="Finale Aggregation des angereicherten Radvorrangsnetz")
    ap.add_argument("--input", default="./output/snapping_converted_bikelanes.fgb", 
                    help="Konvertierte Radverkehrsanlagen (Pfad[:Layer]) - Default: ./output/snapping_converted_bikelanes.fgb")
    ap.add_argument("--output", default="./output/aggregated_rvn_final.gpkg", 
                    help="Finale aggregierte Daten (Pfad[:Layer]) - Default: ./output/aggregated_rvn_final.fgb. Bei ri-Attribut wird GPKG mit 3 Layern erstellt: hinrichtung (ri=0), gegenrichtung (ri=1)")
    ap.add_argument("--crs", type=int, default=DEFAULT_CRS,
                    help=f"Ziel-EPSG (default {DEFAULT_CRS})")
    ap.add_argument("--clip", type=str, choices=['neukoelln', 'norden', 'sueden'],
                    help="Regionaler Zuschnitt: 'neukoelln', 'norden' oder 'sueden'.")
    ap.add_argument("--data-dir", default="./data", 
                    help="Pfad zum Datenverzeichnis (default: ./data)")
    ap.add_argument("--no-districts", action="store_true",
                    help="Überspringe Bezirkszuweisung (optional)")
    args = ap.parse_args()
    
    # Automatische Anpassung des Input-Pfads für regionale Clipping
    if args.clip and args.input == "./output/snapping_converted_bikelanes.fgb":
        args.input = f"./output/snapping_converted_bikelanes_{args.clip}.fgb"
        logging.info(f"Automatische Eingabedatei-Anpassung für {args.clip}: {args.input}")

    # Hauptfunktion aufrufen
    process(args.input, args.output, args.crs, args.clip, args.data_dir, not args.no_districts)
