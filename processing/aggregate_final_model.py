#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggregate_final_model.py
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

Aggregationsregeln:
- Längster Abschnitt: Bezirk, Art der Radverkehrsführung, Benutzungspflicht, 
  Oberflächenmaterial, farbliche Beschichtung, Art der Protektion
- Schlechteste Ausprägung: Breite (kleinste), Sicherheitstrennstreifen, 
  Nutzungsbeschränkung (physische Sperre > Schadensschild > keine)

INPUT:
- output/snapping_network_enriched.fgb (angereicherte Netzwerkdaten mit element_nr und ri)
- data/Berlin Bezirke.gpkg (Berliner Bezirksgrenzen für Bezirkszuweisung)

OUTPUT:
- output/aggregated_rvn_final.gpkg (finale aggregierte Netzwerkdaten als GeoPackage)
  - Layer "hinrichtung": Kanten mit ri=0 
  - Layer "gegenrichtung": Kanten mit ri=1
"""
import argparse, sys
from pathlib import Path
import os, logging
import pandas as pd
import geopandas as gpd
from shapely.ops import linemerge
from shapely.geometry import LineString, MultiLineString
from helpers.progressbar import print_progressbar
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_neukoelln


# -------------------------------------------------------------- Konstanten --
# Minimale Länge für signifikante Änderungen (in Metern)
MIN_SIGNIFICANT_LENGTH = 50.0

# Minimale Breitenänderung für Signifikanz (in Metern)
MIN_SIGNIFICANT_WIDTH_CHANGE = 0.3

# Attribute für regelbasierte Aggregation
LONGEST_SECTION_ATTRIBUTES = [
    "bezirk", "fuehr", "pflicht", "ofm", "farbe", "protek"
]

WORST_CASE_ATTRIBUTES = {
    "breite": "min",  # Kleinste Breite
    "trennstreifen": "worst_trennstreifen",  # Spezielle Logik
    "nutz_beschr": "worst_nutz_beschr"  # Spezielle Logik
}

# Hierarchie für Nutzungsbeschränkungen (schlechteste zuerst)
NUTZ_BESCHR_HIERARCHY = [
    "Physische Sperre",
    "Schadensschild/StVO Zusatzeichen (Straßenschäden, Gehwegschäden, Radwegschäden)",
    "keine"
]

# Hierarchie für Sicherheitstrennstreifen (schlechteste zuerst) 
TRENNSTREIFEN_HIERARCHY = [
    "nein",  # Worst case
    "ja",    # Best case
    "entfällt"
]

# Spalten, die nach der Aggregation gelöscht werden sollen
COLUMNS_TO_DROP = [
    "okstra_id", "existenz", "ist_radvorrangnetz", "elem_nr", "gisid", "gueltig_von", 
    "dnez__sdatenid", "str_bez", "Index", "strassenklasse", "sfid"
]

# Spaltenreihenfolge wird jetzt in start_snapping.py als Datenvorbereitung behandelt


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


def find_worst_nutz_beschr(values):
    """
    Findet die schlechteste Nutzungsbeschränkung basierend auf der Hierarchie.
    """
    values = [v for v in values if pd.notna(v) and v is not None]
    if not values:
        return "keine"
    
    for worst_option in NUTZ_BESCHR_HIERARCHY:
        if worst_option in values:
            return worst_option
    
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
        changes.append(f"Benutzungspflicht-Änderung: {pflicht_values}")
    
    # Prüfe Änderungen bei Nutzungsbeschränkung
    nutz_values = segments_group['nutz_beschr'].dropna().unique()
    if len(nutz_values) > 1:
        changes.append(f"Nutzungsbeschränkung-Änderung: {nutz_values}")
    
    # Prüfe Änderungen bei anderen Attributen auf 50m+ Abschnitten
    long_segments = segments_group[segments_group.geometry.length >= MIN_SIGNIFICANT_LENGTH]
    
    if len(long_segments) > 0:
        # Art der Radverkehrsführung
        fuehr_values = long_segments['fuehr'].dropna().unique()
        if len(fuehr_values) > 1:
            changes.append(f"RVA-Änderung auf {len(long_segments)} langen Segmenten: {fuehr_values}")
        
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
            changes.append(f"Oberflächenmaterial-Änderung: {ofm_values}")
        
        # Protektion
        protek_values = long_segments['protek'].dropna().unique()
        if len(protek_values) > 1:
            changes.append(f"Protektion-Änderung: {protek_values}")
        
        # Sicherheitstrennstreifen
        trenn_values = long_segments['trennstreifen'].dropna().unique()
        if len(trenn_values) > 1:
            changes.append(f"Trennstreifen-Änderung: {trenn_values}")
    
    return changes


def aggregate_by_longest_section(segments_group, attribute):
    """
    Aggregiert ein Attribut basierend auf dem längsten Abschnitt.
    """
    if attribute not in segments_group.columns:
        return None
    
    # Gruppiere Segmente nach Attributwert und summiere Längen
    value_lengths = {}
    for _, segment in segments_group.iterrows():
        value = segment[attribute]
        length = calculate_segment_length(segment.geometry)
        
        if pd.notna(value):
            if value not in value_lengths:
                value_lengths[value] = 0
            value_lengths[value] += length
    
    if not value_lengths:
        return None
    
    # Finde den Wert mit der längsten Gesamtlänge
    longest_value = max(value_lengths, key=value_lengths.get)
    return longest_value


def aggregate_by_worst_case(segments_group, attribute, aggregation_type):
    """
    Aggregiert ein Attribut basierend auf dem schlechtesten Fall.

    """
    if attribute not in segments_group.columns:
        return None
    
    values = segments_group[attribute].dropna().tolist()
    if not values:
        return None
    
    if aggregation_type == "min":
        # Kleinster numerischer Wert (für Breite)
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
    
    # Extrahiere alle nicht-leeren Werte
    values = segments_group[attribute].dropna().astype(str)
    
    # Entferne leere Strings und 'nan' Werte
    values = values[values != '']
    values = values[values.str.lower() != 'nan']
    values = values[values.str.lower() != 'none']
    
    if len(values) == 0:
        return None
    
    # Ermittle einzigartige Werte und sortiere sie
    unique_values = sorted(values.unique())
    
    # Kombiniere mit Semikolon
    return ';'.join(unique_values) if len(unique_values) > 0 else None


def aggregate_edge_group(edge_group):
    """
    Aggregiert alle Segmente einer Kante (gleiche element_nr und ri) zu einer finalen Kante.
    Wendet die definierten Aggregationsregeln an.
    """
    if len(edge_group) == 1:
        # Nur ein Segment - keine Aggregation nötig
        aggregated = edge_group.iloc[0].copy()
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
        changes = detect_significant_changes(edge_group)
        if changes:
            element_nr = aggregated.get('element_nr', 'unknown')
            ri = aggregated.get('ri', 'unknown')
            logging.info(f"Signifikante Änderungen in Kante {element_nr} (Richtung: {ri}): {'; '.join(changes)}")
        
        # Attribute nach "längster Abschnitt" aggregieren
        for attr in LONGEST_SECTION_ATTRIBUTES:
            if attr in edge_group.columns:
                aggregated[attr] = aggregate_by_longest_section(edge_group, attr)
        
        # Attribute nach "schlechtestem Fall" aggregieren
        for attr, agg_type in WORST_CASE_ATTRIBUTES.items():
            if attr in edge_group.columns:
                aggregated[attr] = aggregate_by_worst_case(edge_group, attr, agg_type)
        
        # TILDA-Attribute durch Semikolon-Kombination aggregieren (dynamisch erkannt)
        tilda_attributes = [col for col in edge_group.columns if col.startswith('tilda_')]
        for attr in tilda_attributes:
            aggregated[attr] = aggregate_tilda_attributes(edge_group, attr)
    
    # Berechne die Länge für ALLE Kanten (Einzelsegmente und aggregierte Kanten)
    aggregated['Länge'] = int(round(calculate_segment_length(aggregated.geometry)))
    
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
    
    for idx, (group_key, edge_group) in enumerate(grouped, 1):
        # Aggregiere die Segmente der aktuellen Kante mit gleicher Richtung
        aggregated_edge = aggregate_edge_group(edge_group)
        aggregated_edges.append(aggregated_edge)
        
        # Erweiterte Logging-Info bei Richtungsgruppierung
        if 'ri' in gdf.columns:
            element_nr, ri = group_key
            logging.debug(f"Aggregiere element_nr={element_nr}, ri={ri}: {len(edge_group)} Segmente")
        
        # Fortschrittsanzeige
        print_progressbar(idx, total_groups, prefix="Aggregiere: ")
    
    # Erstelle neues GeoDataFrame aus aggregierten Kanten
    result_gdf = gpd.GeoDataFrame(aggregated_edges, geometry="geometry", crs=gdf.crs)
    
    # Entferne unerwünschte Spalten
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


def assign_district_to_edges(edges_gdf, districts_path, crs):
    """
    Weist den Kanten Bezirksnummern basierend auf dem größten räumlichen Anteil zu.
    Kanten, die sich über mehrere Bezirke erstrecken, erhalten den Bezirk,
    in dem sie den größten Anteil haben.
    
    Args:
        edges_gdf: GeoDataFrame mit den Kanten
        districts_path: Pfad zur Bezirks-Datei
        crs: Koordinatensystem für Berechnungen
        
    Returns:
        GeoDataFrame mit zusätzlicher 'Bezirksnummer'-Spalte
    """
    logging.info(f"Lade Bezirksgrenzen von {districts_path}")
    districts_gdf = gpd.read_file(districts_path).to_crs(crs)
    
    # Sicherstellen, dass die CRS übereinstimmen
    if edges_gdf.crs != districts_gdf.crs:
        logging.info("Projiziere Bezirke auf das CRS der Kanten")
        districts_gdf = districts_gdf.to_crs(edges_gdf.crs)
    
    logging.info("Berechne Bezirkszuweisungen basierend auf größtem räumlichen Anteil...")
    
    # Initialisiere Bezirksnummer-Spalte
    edges_gdf['Bezirksnummer'] = None
    
    total_edges = len(edges_gdf)
    processed_edges = 0
    
    for idx, edge in edges_gdf.iterrows():
        edge_geom = edge.geometry
        max_intersection_length = 0
        assigned_district = None
        
        # Prüfe Überschneidung mit allen Bezirken
        for _, district in districts_gdf.iterrows():
            try:
                # Berechne Überschneidung zwischen Kante und Bezirk
                intersection = edge_geom.intersection(district.geometry)
                
                if intersection.is_empty:
                    continue
                
                # Berechne Länge der Überschneidung
                if hasattr(intersection, 'length'):
                    intersection_length = intersection.length
                else:
                    # Falls Punkt oder andere Geometrie
                    intersection_length = 0
                
                # Speichere Bezirk mit größter Überschneidung
                if intersection_length > max_intersection_length:
                    max_intersection_length = intersection_length
                    # Extrahiere zweistellige Bezirksnummer aus 'gem'-Spalte
                    if 'gem' in district and pd.notna(district['gem']):
                        assigned_district = str(district['gem'])[-2:]
                    else:
                        assigned_district = None
                        
            except Exception as e:
                logging.warning(f"Fehler bei Überschneidungsberechnung für Kante {idx}: {e}")
                continue
        
        # Weise Bezirksnummer zu
        edges_gdf.at[idx, 'Bezirksnummer'] = assigned_district
        
        processed_edges += 1
        if processed_edges % 100 == 0:
            print_progressbar(processed_edges, total_edges, prefix="Bezirkszuweisung: ")
    
    # Finale Fortschrittsanzeige
    print_progressbar(total_edges, total_edges, prefix="Bezirkszuweisung: ")
    
    # Statistiken
    assigned_count = edges_gdf['Bezirksnummer'].notna().sum()
    logging.info(f"Bezirkszuweisung abgeschlossen: {assigned_count}/{total_edges} Kanten haben eine Bezirksnummer erhalten")
    
    if assigned_count > 0:
        district_counts = edges_gdf['Bezirksnummer'].value_counts()
        logging.info(f"Verteilung nach Bezirken: {dict(district_counts)}")
    
    return edges_gdf


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


# ------------------------------------------------------------- Hauptablauf --
def process(input_path, output_path, crs, clip_neukoelln=False, data_dir="./data", assign_districts=True):
    """
    Hauptfunktion: Lädt angereicherte Netzwerkdaten und führt finale Aggregation durch.
    
    Args:
        input_path: Pfad zu angereicherten Netzwerkdaten
        output_path: Pfad für finale aggregierte Daten  
        crs: Ziel-Koordinatensystem (EPSG)
        clip_neukoelln: Ob auf Neukölln zugeschnitten werden soll
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
    
    # Optional: Auf Neukölln zuschneiden
    if clip_neukoelln:
        logging.info("Schneide Daten auf Neukölln zu")
        gdf = clip_to_neukoelln(gdf, data_dir, crs)
        logging.info(f"Nach Neukölln-Clipping: {len(gdf)} Segmente")

    # Prüfen, ob Pflichtfelder vorhanden sind
    if 'element_nr' not in gdf.columns:
        sys.exit("Pflichtfeld 'element_nr' fehlt in den Eingangsdaten!")
    
    if 'ri' not in gdf.columns:
        logging.warning("Attribut 'ri' (Richtung) fehlt in den Eingangsdaten! Aggregation erfolgt nur nach element_nr.")
    else:
        logging.info(f"Richtungsattribut 'ri' gefunden. Verfügbare Richtungen: {sorted(gdf['ri'].dropna().unique())}")

    # ---------- Aggregation durchführen ------------------------------------
    logging.info("Starte finale Aggregation...")
    result_gdf = aggregate_network(gdf)

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

    # ---------- Ergebnis speichern ------------------------------------------
    p, *layer = output_path.split(":")
    layer = layer[0] if layer else "aggregated_edges"
    
    # Stelle sicher, dass das Ausgabeverzeichnis existiert
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Path(p).unlink(missing_ok=True)
    
    # Füge Suffix für Neukölln-Dateien hinzu
    if clip_neukoelln:
        p_parts = p.split('.')
        if len(p_parts) > 1:
            p_base = '.'.join(p_parts[:-1])
            p_ext = p_parts[-1]
            p = f"{p_base}_neukoelln.{p_ext}"
        else:
            p = f"{p}_neukoelln"
    
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
        
        print(f"✔  {len(result_gdf)} finale Kanten → {p_gpkg} (3 Layer: hinrichtung, gegenrichtung, alle_richtungen)")
        
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
    ap.add_argument("--input", default="./output/snapping_network_enriched.fgb", 
                    help="Angereicherte Netzwerkdaten (Pfad[:Layer]) - Default: ./output/snapping_network_enriched.fgb")
    ap.add_argument("--output", default="./output/aggregated_rvn_final.gpkg", 
                    help="Finale aggregierte Daten (Pfad[:Layer]) - Default: ./output/aggregated_rvn_final.fgb. Bei ri-Attribut wird GPKG mit 3 Layern erstellt: hinrichtung (ri=0), gegenrichtung (ri=1), alle_richtungen")
    ap.add_argument("--crs", type=int, default=DEFAULT_CRS,
                    help=f"Ziel-EPSG (default {DEFAULT_CRS})")
    ap.add_argument("--clip-neukoelln", action="store_true",
                    help="Schneide Daten auf Neukölln zu (optional)")
    ap.add_argument("--data-dir", default="./data", 
                    help="Pfad zum Datenverzeichnis (default: ./data)")
    ap.add_argument("--no-districts", action="store_true",
                    help="Überspringe Bezirkszuweisung (optional)")
    args = ap.parse_args()

    # Hauptfunktion aufrufen
    process(args.input, args.output, args.crs, args.clip_neukoelln, args.data_dir, not args.no_districts)
