#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_dual_carriageway.py
--------------------------------------------------------------------
Analysiert den matched Datensatz auf potentiell fehlende dual_carriageway=yes 
Attribute in OSM.

Das Problem: Zwei von der Richtung gegensätzliche Wege mit gleichem Straßennamen,
die beide tilda_oneway=yes haben, aber nicht als yes_dual_carriageway markiert sind.
Dies deutet darauf hin, dass in OSM das dual_carriageway=yes Attribut fehlt.

Logik:
1. Lade matched_tilda_ways.fgb
2. Filtere auf tilda_oneway='yes' (echte Einbahnstraßen)
3. Gruppiere nach Straßenname (tilda_name)
4. Berechne Richtungswinkel jedes Weges
5. Finde Straßen mit Wegen in entgegengesetzten Richtungen (~180° Unterschied)
6. Diese sind verdächtig für fehlende dual_carriageway Markierung

OUTPUT: output/analysis/potential_missing_dual_carriageway.fgb
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path
from shapely.geometry import LineString, MultiLineString
import logging

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Konstanten
ANGLE_TOLERANCE = 45  # Grad Toleranz für "entgegengesetzte" Richtung (180° ± tolerance)
MIN_WAYS_PER_DIRECTION = 1  # Mindestanzahl Wege pro Richtung für Verdacht


def get_line_direction_angle(geometry):
    """
    Berechnet den Richtungswinkel einer Linie (von Start zu Ende).
    
    Args:
        geometry: LineString oder MultiLineString
        
    Returns:
        float: Winkel in Grad (-180 bis 180)
    """
    if isinstance(geometry, MultiLineString):
        # Bei MultiLineString: Nimm die erste Linie
        line = geometry.geoms[0]
    elif isinstance(geometry, LineString):
        line = geometry
    else:
        return None
    
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    
    # Berechne Vektor von Start zu Ende
    dx = coords[-1][0] - coords[0][0]
    dy = coords[-1][1] - coords[0][1]
    
    # Winkel in Grad
    angle = np.degrees(np.arctan2(dy, dx))
    return angle


def normalize_angle_difference(angle1, angle2):
    """
    Berechnet den kleinsten Winkelunterschied zwischen zwei Winkeln.
    
    Returns:
        float: Winkelunterschied (0 bis 180)
    """
    diff = abs(angle1 - angle2)
    if diff > 180:
        diff = 360 - diff
    return diff


def are_opposite_directions(angle1, angle2, tolerance=ANGLE_TOLERANCE):
    """
    Prüft ob zwei Winkel entgegengesetzte Richtungen repräsentieren.
    
    Args:
        angle1, angle2: Winkel in Grad
        tolerance: Toleranz in Grad
        
    Returns:
        bool: True wenn Winkel ~180° auseinander liegen
    """
    diff = normalize_angle_difference(angle1, angle2)
    return abs(diff - 180) <= tolerance


def analyze_street_for_dual_carriageway(street_gdf):
    """
    Analysiert eine Gruppe von Wegen mit gleichem Straßennamen auf 
    potentiell fehlende dual_carriageway Markierung.
    
    Args:
        street_gdf: GeoDataFrame mit Wegen einer Straße
        
    Returns:
        dict oder None: Analyseergebnis wenn verdächtig, sonst None
    """
    if len(street_gdf) < 2:
        return None
    
    # Berechne Richtungswinkel für alle Wege
    angles = []
    for idx, row in street_gdf.iterrows():
        angle = get_line_direction_angle(row.geometry)
        if angle is not None:
            angles.append((idx, angle))
    
    if len(angles) < 2:
        return None
    
    # Gruppiere Winkel in "ähnliche Richtungen"
    # Verwende Clustering: Winkel die nahe beieinander liegen gehören zusammen
    direction_groups = []
    
    for idx, angle in angles:
        assigned = False
        for group in direction_groups:
            # Prüfe ob Winkel zu einer existierenden Gruppe passt
            group_angle = group['representative_angle']
            diff = normalize_angle_difference(angle, group_angle)
            if diff <= ANGLE_TOLERANCE:
                group['members'].append((idx, angle))
                assigned = True
                break
        
        if not assigned:
            # Neue Gruppe erstellen
            direction_groups.append({
                'representative_angle': angle,
                'members': [(idx, angle)]
            })
    
    # Suche nach entgegengesetzten Gruppen
    opposite_pairs = []
    for i, group1 in enumerate(direction_groups):
        for j, group2 in enumerate(direction_groups):
            if i >= j:
                continue
            if are_opposite_directions(group1['representative_angle'], 
                                       group2['representative_angle']):
                opposite_pairs.append((group1, group2))
    
    if not opposite_pairs:
        return None
    
    # Es gibt entgegengesetzte Richtungen -> verdächtig
    # Sammle alle betroffenen Indizes
    suspicious_indices = set()
    for group1, group2 in opposite_pairs:
        if (len(group1['members']) >= MIN_WAYS_PER_DIRECTION and 
            len(group2['members']) >= MIN_WAYS_PER_DIRECTION):
            for idx, _ in group1['members']:
                suspicious_indices.add(idx)
            for idx, _ in group2['members']:
                suspicious_indices.add(idx)
    
    if not suspicious_indices:
        return None
    
    return {
        'suspicious_indices': suspicious_indices,
        'direction_groups': len(direction_groups),
        'opposite_pairs': len(opposite_pairs)
    }


def main():
    """Hauptfunktion."""
    base_path = Path(__file__).parent.parent
    
    # Input/Output Pfade
    # Nur streets-Datensatz verwenden (keine Radwege etc.)
    input_file = base_path / "output" / "matched" / "matched_tilda_streets_ways.fgb"
    snapping_file = base_path / "output" / "snapping_network_enriched.fgb"
    output_dir = base_path / "output" / "analysis"
    output_file = output_dir / "potential_missing_dual_carriageway.fgb"
    
    # Konstanten für Filterung
    BUFFER_DISTANCE = 20  # Meter für räumliche Verschneidung
    FUEHR_FILTER = "Mischverkehr"  # Substring der in fuehr enthalten sein muss
    
    # Output-Verzeichnis erstellen
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("="*80)
    logger.info("ANALYSE: Potentiell fehlende dual_carriageway=yes Attribute")
    logger.info("="*80)
    
    # Datei einlesen
    logger.info(f"Lade Datei: {input_file}")
    if not input_file.exists():
        logger.error(f"Datei nicht gefunden: {input_file}")
        return
    
    gdf = gpd.read_file(input_file)
    logger.info(f"Geladene Features: {len(gdf)}")
    
    # Filtere auf tilda_oneway='yes' (echte Einbahnstraßen, nicht dual_carriageway)
    gdf_oneway = gdf[gdf['tilda_oneway'] == 'yes'].copy()
    logger.info(f"Features mit tilda_oneway='yes': {len(gdf_oneway)}")
    
    # Filtere auf Features mit Straßennamen
    gdf_with_name = gdf_oneway[gdf_oneway['tilda_name'].notna()].copy()
    logger.info(f"Davon mit Straßennamen: {len(gdf_with_name)}")
    
    # Berechne Richtungswinkel für alle Wege
    logger.info("Berechne Richtungswinkel...")
    gdf_with_name['direction_angle'] = gdf_with_name.geometry.apply(get_line_direction_angle)
    
    # Entferne Wege ohne gültigen Winkel
    gdf_valid = gdf_with_name[gdf_with_name['direction_angle'].notna()].copy()
    logger.info(f"Features mit gültigem Richtungswinkel: {len(gdf_valid)}")
    
    # Gruppiere nach Straßenname und analysiere
    logger.info("Analysiere Straßen auf entgegengesetzte Richtungen...")
    
    suspicious_indices = set()
    street_stats = []
    
    grouped = gdf_valid.groupby('tilda_name')
    total_streets = len(grouped)
    
    for street_name, street_group in grouped:
        result = analyze_street_for_dual_carriageway(street_group)
        if result:
            suspicious_indices.update(result['suspicious_indices'])
            street_stats.append({
                'street_name': street_name,
                'total_ways': len(street_group),
                'direction_groups': result['direction_groups'],
                'opposite_pairs': result['opposite_pairs']
            })
    
    logger.info(f"Analysierte Straßen: {total_streets}")
    logger.info(f"Verdächtige Straßen (mit entgegengesetzten Richtungen): {len(street_stats)}")
    logger.info(f"Verdächtige Wege insgesamt: {len(suspicious_indices)}")
    
    if not suspicious_indices:
        logger.info("Keine verdächtigen Fälle gefunden.")
        return
    
    # Erstelle Output GeoDataFrame
    gdf_suspicious = gdf_valid.loc[list(suspicious_indices)].copy()
    
    # Füge Analyse-Informationen hinzu
    # Erstelle ein Mapping von Straßenname zu Stats
    street_stats_dict = {s['street_name']: s for s in street_stats}
    
    gdf_suspicious['analysis_direction_groups'] = gdf_suspicious['tilda_name'].map(
        lambda x: street_stats_dict.get(x, {}).get('direction_groups', 0)
    )
    gdf_suspicious['analysis_opposite_pairs'] = gdf_suspicious['tilda_name'].map(
        lambda x: street_stats_dict.get(x, {}).get('opposite_pairs', 0)
    )
    gdf_suspicious['analysis_total_ways'] = gdf_suspicious['tilda_name'].map(
        lambda x: street_stats_dict.get(x, {}).get('total_ways', 0)
    )
    
    # Verschneide mit Snapping-Daten: Nur Mischverkehr-Bereiche behalten
    logger.info("")
    logger.info("Filtere auf Mischverkehr-Bereiche aus Snapping-Daten...")
    logger.info(f"Lade Snapping-Datei: {snapping_file}")
    
    if not snapping_file.exists():
        logger.error(f"Snapping-Datei nicht gefunden: {snapping_file}")
        return
    
    gdf_snapping = gpd.read_file(snapping_file)
    logger.info(f"Geladene Snapping-Features: {len(gdf_snapping)}")
    
    # Filtere auf fuehr mit "Mischverkehr"
    gdf_mischverkehr = gdf_snapping[
        gdf_snapping['fuehr'].str.contains(FUEHR_FILTER, na=False)
    ].copy()
    logger.info(f"Davon mit '{FUEHR_FILTER}' in fuehr: {len(gdf_mischverkehr)}")
    
    # Erstelle Buffer um Mischverkehr-Segmente
    logger.info(f"Erstelle {BUFFER_DISTANCE}m Buffer um Mischverkehr-Segmente...")
    gdf_mischverkehr_buffer = gdf_mischverkehr.copy()
    gdf_mischverkehr_buffer['geometry'] = gdf_mischverkehr_buffer.geometry.buffer(BUFFER_DISTANCE)
    
    # Vereinige alle Buffer zu einer Geometrie für effiziente Abfrage
    mischverkehr_union = gdf_mischverkehr_buffer.union_all()
    
    # Filtere verdächtige Wege: Nur die, die den Mischverkehr-Buffer schneiden
    logger.info("Filtere verdächtige Wege auf Mischverkehr-Bereiche...")
    
    # Spatial Join wäre effizienter, aber für diesen Fall reicht intersects
    mask = gdf_suspicious.geometry.intersects(mischverkehr_union)
    gdf_suspicious_filtered = gdf_suspicious[mask].copy()
    
    logger.info(f"Verdächtige Wege nach Mischverkehr-Filter: {len(gdf_suspicious_filtered)}")
    
    if len(gdf_suspicious_filtered) == 0:
        logger.info("Keine verdächtigen Fälle nach Filterung gefunden.")
        return
    
    # Aktualisiere Statistiken für gefilterte Straßen
    filtered_street_names = gdf_suspicious_filtered['tilda_name'].unique()
    filtered_street_stats = [s for s in street_stats if s['street_name'] in filtered_street_names]
    
    # Speichere Ergebnis
    logger.info(f"Speichere Ergebnis: {output_file}")
    gdf_suspicious_filtered.to_file(output_file, driver='FlatGeobuf')
    
    # Zusammenfassung ausgeben
    logger.info("")
    logger.info("="*80)
    logger.info("ZUSAMMENFASSUNG")
    logger.info("="*80)
    logger.info(f"Verdächtige Straßen (nach Mischverkehr-Filter): {len(filtered_street_stats)}")
    logger.info(f"Verdächtige Wege (nach Mischverkehr-Filter): {len(gdf_suspicious_filtered)}")
    logger.info("")
    
    # Top 10 verdächtige Straßen
    logger.info("Top 10 verdächtige Straßen (nach Anzahl Wege):")
    sorted_stats = sorted(filtered_street_stats, key=lambda x: x['total_ways'], reverse=True)[:10]
    for stat in sorted_stats:
        logger.info(f"  - {stat['street_name']}: {stat['total_ways']} Wege, "
                   f"{stat['direction_groups']} Richtungsgruppen, "
                   f"{stat['opposite_pairs']} gegensätzliche Paare")
    
    logger.info("")
    logger.info(f"Output gespeichert: {output_file}")
    logger.info("="*80)


if __name__ == "__main__":
    main()
