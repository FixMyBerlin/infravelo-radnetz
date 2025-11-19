#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
start_overriding.py
--------------------------------------------------------------------
Wendet Override-Konfigurationen auf bereits gesnappte und konvertierte Netzwerkdaten an.
Overrides werden NACH dem Snapping angewendet und überschreiben gezielt Attribute.

Zwei Override-Quellen werden unterstützt:
1. GeoPackage-Overrides (data/override_ways.gpkg): 
   - Räumliche Overrides mit Geometrien
   - Override-Geometrie wird auf Netz projiziert
   - Alle betroffenen Segmente bekommen Override-Attribute

2. Text-Overrides (data/override_ways.txt):
   - Format: tilda_id|element_nr|ri|attributes_json
   - Alle Segmente mit element_nr+ri bekommen Attribute vom tilda_id

Bei Overrides werden:
- Nur Override-spezifische Attribute überschrieben (fuehr, ofm, protek, pflicht, breite, farbe, trennstreifen, nutz_beschr)
- Prioritäts-Attribute gelöscht (prio_*)
- Kommentar hinzugefügt mit Override-Informationen

INPUT:
- output/snapping/snapping_converted_bikelanes.fgb (nach Snapping und Konvertierung)
- output/matched/matched_tilda_ways.fgb (für Attribut-Lookup bei Text-Overrides)
- data/override_ways.gpkg (GeoPackage mit räumlichen Override-Geometrien)
- data/override_ways.txt (Textdatei mit Text-Overrides)

OUTPUT:
- output/snapping_with_overrides.fgb (Netzwerk mit angewendeten Overrides)
(Bei Clipping: snapping_with_overrides_neukoelln.fgb bzw. snapping_with_overrides_norden.fgb)
"""
import argparse
import sys
from pathlib import Path
import os
import logging
import json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points
from helpers.globals import DEFAULT_CRS
from helpers.clipping import clip_to_region, clip_to_view


# ============================================================================
# KONFIGURATION
# ============================================================================

# Override-spezifische Attribute die überschrieben werden dürfen
OVERRIDE_ATTRIBUTES = [
    'fuehr', 'ofm', 'protek', 'pflicht', 'breite', 
    'farbe', 'trennstreifen', 'nutz_beschr'
]

# Prioritäts-Attribute die bei Override gelöscht werden
PRIORITY_ATTRIBUTES = [
    'prio_total', 'prio_distance', 'prio_angle', 'prio_verkehrsri'
]

# Räumliche Matching-Parameter
SPATIAL_TOLERANCE_METERS = 7.0  # Maximale Distanz für räumliches Matching
MIN_OVERLAP_RATIO = 0.8  # Minimaler Overlap-Anteil (0.0-1.0) für GeoPackage-Overrides


def load_override_geopackage(gpkg_path, crs):
    """
    Lädt Override-Einträge aus GeoPackage.
    
    Args:
        gpkg_path: Pfad zur Override-GeoPackage-Datei
        crs: Ziel-CRS (EPSG-Code)
    
    Returns:
        GeoDataFrame mit Override-Einträgen oder None bei Fehler
    """
    if not os.path.exists(gpkg_path):
        logging.info(f"ℹ️  Keine GeoPackage-Override-Datei gefunden: {gpkg_path}")
        return None
    
    try:
        override_gdf = gpd.read_file(gpkg_path)
        if override_gdf.empty:
            logging.info("ℹ️  GeoPackage-Override-Datei ist leer")
            return None
        
        # Konvertiere zu Ziel-CRS
        if override_gdf.crs and override_gdf.crs != f"EPSG:{crs}":
            override_gdf = override_gdf.to_crs(crs)
        
        logging.info(f"✔  {len(override_gdf)} GeoPackage-Override-Einträge geladen")
        return override_gdf
    
    except Exception as e:
        logging.error(f"❌ Fehler beim Laden der GeoPackage-Override-Datei: {e}")
        return None


def load_text_overrides(text_path):
    """
    Lädt Override-Einträge aus Textdatei.
    
    Format: tilda_id|element_nr|ri|attributes_json
    
    Args:
        text_path: Pfad zur Override-Textdatei
    
    Returns:
        Dictionary mit Override-Einträgen: {(element_nr, ri): {...}} oder None bei Fehler
    """
    if not os.path.exists(text_path):
        logging.info(f"ℹ️  Keine Text-Override-Datei gefunden: {text_path}")
        return None
    
    overrides = {}
    line_num = 0
    
    try:
        with open(text_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_num += 1
                line = line.strip()
                
                # Überspringe Kommentare und leere Zeilen
                if not line or line.startswith('#'):
                    continue
                
                # Parse Format: tilda_id|element_nr|ri|attributes_json
                parts = line.split('|')
                if len(parts) != 4:
                    logging.warning(f"⚠️  Zeile {line_num}: Ungültiges Format (erwartet 4 Teile): {line}")
                    continue
                
                tilda_id, element_nr, ri_str, attributes_json = parts
                
                # Validiere und parse
                try:
                    ri = int(ri_str)
                    if ri not in [0, 1]:
                        logging.warning(f"⚠️  Zeile {line_num}: ri muss 0 oder 1 sein: {ri}")
                        continue
                    
                    # Parse Attribute (JSON oder leer)
                    attributes = {}
                    if attributes_json and attributes_json.strip():
                        attributes = json.loads(attributes_json)
                    
                    # Speichere Override
                    key = (str(element_nr), ri)
                    overrides[key] = {
                        'tilda_id': tilda_id.strip(),
                        'attributes': attributes
                    }
                    
                except (ValueError, json.JSONDecodeError) as e:
                    logging.warning(f"⚠️  Zeile {line_num}: Parse-Fehler: {e}")
                    continue
        
        if overrides:
            logging.info(f"✔  {len(overrides)} Text-Override-Einträge geladen")
        else:
            logging.info("ℹ️  Keine gültigen Text-Override-Einträge gefunden")
        
        return overrides if overrides else None
    
    except Exception as e:
        logging.error(f"❌ Fehler beim Laden der Text-Override-Datei: {e}")
        return None


def project_geometry_to_network(override_geom, network_gdf, override_idx=None, tilda_id=None):
    """
    Projiziert eine Override-Geometrie auf das Netzwerk und findet alle betroffenen Segmente.
    
    Ein Segment wird nur als betroffen betrachtet, wenn mindestens MIN_OVERLAP_RATIO (80%)
    der Override-Geometrie mit dem Segment überlappt.
    
    Args:
        override_geom: Shapely-Geometrie des Overrides
        network_gdf: GeoDataFrame mit Netzwerk-Segmenten
        override_idx: Index des Override-Eintrags (für Logging)
        tilda_id: tilda_id des Override-Eintrags (für Logging)
    
    Returns:
        Liste von Segment-Indizen die vom Override betroffen sind
    """
    affected_segments = []
    override_label = f"Override {override_idx}" if override_idx is not None else "Override"
    if tilda_id:
        override_label += f" (tilda_id={tilda_id})"
    
    try:
        # Verwende räumlichen Index für effiziente Suche
        # Erweitere Bounding Box um Toleranz, um auch nahe Segmente zu finden
        minx, miny, maxx, maxy = override_geom.bounds
        expanded_bounds = (
            minx - SPATIAL_TOLERANCE_METERS,
            miny - SPATIAL_TOLERANCE_METERS,
            maxx + SPATIAL_TOLERANCE_METERS,
            maxy + SPATIAL_TOLERANCE_METERS
        )
        possible_matches_idx = list(network_gdf.sindex.intersection(expanded_bounds))
        
        override_length = override_geom.length
        if override_length == 0:
            logging.warning(f"⚠️  {override_label}: Override-Geometrie hat Länge 0")
            return []
        
        logging.info(f"🔍 {override_label}: Länge={override_length:.1f}m, {len(possible_matches_idx)} potenzielle Segmente in erweiteter Bounding Box (±{SPATIAL_TOLERANCE_METERS}m)")
        
        checked_count = 0
        for idx in possible_matches_idx:
            segment_geom = network_gdf.iloc[idx].geometry
            segment_info = network_gdf.iloc[idx]
            element_nr = segment_info.get('element_nr', 'N/A')
            ri = segment_info.get('ri', 'N/A')
            sfid = segment_info.get('sfid', 'N/A')
            
            # Prüfe räumliche Nähe
            distance = segment_geom.distance(override_geom)
            intersects = segment_geom.intersects(override_geom)
            
            if not (intersects or distance < SPATIAL_TOLERANCE_METERS):
                logging.debug(
                    f"  ✗ Segment {idx} (sfid={sfid}, element_nr={element_nr}, ri={ri}): "
                    f"Zu weit entfernt (distance={distance:.1f}m > {SPATIAL_TOLERANCE_METERS}m)"
                )
                continue
            
            checked_count += 1
            
            # Berechne Overlap: Wie viel % des Segments wird von der Override-Geometrie abgedeckt?
            try:
                overlap_length = 0.0
                segment_length = segment_geom.length
                
                if segment_length == 0:
                    logging.debug(f"  ⚠️  Segment {idx}: Länge 0, überspringe")
                    continue
                
                # Methode: Berechne wie viel des Segments innerhalb eines Buffers um die Override-Geometrie liegt
                # Buffer um die Override-Geometrie erstellen
                override_buffer = override_geom.buffer(SPATIAL_TOLERANCE_METERS)
                
                # Intersection des Segments mit dem Buffer
                if override_buffer.intersects(segment_geom):
                    intersection = override_buffer.intersection(segment_geom)
                    if hasattr(intersection, 'length'):
                        overlap_length = intersection.length
                    elif hasattr(intersection, 'geoms'):
                        # MultiLineString oder GeometryCollection
                        overlap_length = sum(g.length for g in intersection.geoms if hasattr(g, 'length'))
                
                # Berechne Overlap-Ratio (wie viel % des SEGMENTS wird abgedeckt)
                overlap_ratio = overlap_length / segment_length if segment_length > 0 else 0.0
                
                # Segment ist betroffen wenn Overlap >= Schwellwert
                if overlap_ratio >= MIN_OVERLAP_RATIO:
                    affected_segments.append(idx)
                    logging.info(
                        f"  ✓ Segment {idx} (sfid={sfid}, element_nr={element_nr}, ri={ri}): "
                        f"Overlap {overlap_ratio:.1%} auf Segment (Segment: {segment_length:.1f}m, Overlap: {overlap_length:.1f}m, "
                        f"Override: {override_length:.1f}m)"
                    )
                else:
                    logging.info(
                        f"  ✗ Segment {idx} (sfid={sfid}, element_nr={element_nr}, ri={ri}): "
                        f"Overlap {overlap_ratio:.1%} < {MIN_OVERLAP_RATIO:.0%} auf Segment "
                        f"(Segment: {segment_length:.1f}m, Overlap: {overlap_length:.1f}m, "
                        f"Override: {override_length:.1f}m)"
                    )
            
            except Exception as e:
                logging.warning(f"  ⚠️  Segment {idx}: Fehler bei Overlap-Berechnung: {e}")
                continue
        
        if checked_count == 0:
            logging.info(f"  ℹ️  Keine Segmente innerhalb {SPATIAL_TOLERANCE_METERS}m Toleranz gefunden")
        
        return affected_segments
    
    except Exception as e:
        logging.error(f"❌ {override_label}: Fehler bei Geometrie-Projektion: {e}")
        return []


def apply_geopackage_overrides(network_gdf, override_gdf, matched_tilda_gdf):
    """
    Wendet GeoPackage-Overrides auf Netzwerk an.
    
    Args:
        network_gdf: GeoDataFrame mit Netzwerk-Segmenten (wird modifiziert)
        override_gdf: GeoDataFrame mit Override-Einträgen
        matched_tilda_gdf: GeoDataFrame mit matched TILDA ways (für Attribut-Lookup)
    
    Returns:
        tuple: (Anzahl angewendeter Overrides, Liste von Warnungen bei Dopplungen, Anzahl nicht angewendeter Overrides)
    """
    if override_gdf is None or len(override_gdf) == 0:
        return 0, [], 0
    
    applied_count = 0
    warnings = []
    not_applied_count = 0
    
    # Track welche Segmente bereits Override haben (für Dopplung-Warnung)
    segments_with_override = set()
    
    for override_idx, override_row in override_gdf.iterrows():
        override_geom = override_row.geometry
        override_ri = override_row.get('ri')
        tilda_id = override_row.get('tilda_id')
        
        # Finde betroffene Segmente
        affected_segments = project_geometry_to_network(override_geom, network_gdf, override_idx, tilda_id)
        
        if not affected_segments:
            logging.debug(f"🔍 GeoPackage-Override {override_idx}: Keine betroffenen Segmente gefunden")
            not_applied_count += 1
            continue
        
        # Filtere nach ri wenn vorhanden und nicht NULL
        # Wenn ri=NULL: beide Richtungen werden angepasst
        # Wenn ri=0 oder ri=1: nur diese Richtung wird angepasst
        if override_ri is not None and not pd.isna(override_ri):
            try:
                override_ri_int = int(override_ri)
                if override_ri_int in [0, 1]:
                    affected_segments = [
                        idx for idx in affected_segments 
                        if int(network_gdf.iloc[idx].get('ri', -1)) == override_ri_int
                    ]
                    logging.debug(f"🔍 GeoPackage-Override {override_idx}: Filtere auf ri={override_ri_int}, {len(affected_segments)} Segmente übrig")
                else:
                    logging.warning(f"⚠️  GeoPackage-Override {override_idx}: ri={override_ri_int} ungültig (erwartet 0, 1 oder NULL)")
            except (ValueError, TypeError):
                logging.debug(f"🔍 GeoPackage-Override {override_idx}: ri-Konvertierung fehlgeschlagen, behandle als NULL (beide Richtungen)")
        else:
            logging.debug(f"🔍 GeoPackage-Override {override_idx}: ri=NULL, beide Richtungen werden angepasst ({len(affected_segments)} Segmente)")
        
        if not affected_segments:
            logging.debug(f"🔍 GeoPackage-Override {override_idx}: Keine Segmente mit passendem ri gefunden")
            not_applied_count += 1
            continue
        
        # Hole Attribute zum Überschreiben
        override_attributes = {}
        
        # 1. Direkte Attribute aus GeoPackage
        for attr in OVERRIDE_ATTRIBUTES:
            if attr in override_row.index and override_row[attr] is not None:
                value = override_row[attr]
                if isinstance(value, str) and value.strip():
                    override_attributes[attr] = value
                elif not isinstance(value, str):
                    override_attributes[attr] = value
        
        # 2. Falls tilda_id gegeben, hole Attribute aus matched_tilda_ways
        if tilda_id and matched_tilda_gdf is not None:
            tilda_match = matched_tilda_gdf[matched_tilda_gdf['tilda_id'] == tilda_id]
            if not tilda_match.empty:
                tilda_row = tilda_match.iloc[0]
                for attr in OVERRIDE_ATTRIBUTES:
                    # Nur übernehmen wenn nicht schon direkt im Override gesetzt
                    if attr not in override_attributes and attr in tilda_row.index:
                        value = tilda_row[attr]
                        if value is not None:
                            override_attributes[attr] = value
        
        if not override_attributes:
            logging.debug(f"🔍 GeoPackage-Override {override_idx}: Keine Attribute zum Überschreiben gefunden")
            not_applied_count += 1
            continue
        
        # Wende Override auf alle betroffenen Segmente an
        for seg_idx in affected_segments:
            # Prüfe auf Dopplung
            if seg_idx in segments_with_override:
                element_nr = network_gdf.iloc[seg_idx].get('element_nr', 'N/A')
                ri = network_gdf.iloc[seg_idx].get('ri', 'N/A')
                warnings.append(
                    f"⚠️  Segment element_nr={element_nr}, ri={ri} hat bereits Override "
                    f"(GeoPackage-Override überschreibt vorherigen)"
                )
            
            segments_with_override.add(seg_idx)
            
            # Überschreibe Attribute
            for attr, value in override_attributes.items():
                network_gdf.at[seg_idx, attr] = value
            
            # Lösche Prioritäts-Attribute
            for prio_attr in PRIORITY_ATTRIBUTES:
                if prio_attr in network_gdf.columns:
                    network_gdf.at[seg_idx, prio_attr] = None
            
            # Füge Kommentar hinzu
            existing_comment = network_gdf.at[seg_idx, 'Kommentar']
            override_comment = (
                f"Override angewendet; Quelle: GeoPackage; "
                f"tilda_id: {tilda_id if tilda_id else 'N/A'}; "
                f"Attribute: {', '.join(override_attributes.keys())}"
            )
            
            if existing_comment and str(existing_comment).strip():
                network_gdf.at[seg_idx, 'Kommentar'] = f"{existing_comment}; {override_comment}"
            else:
                network_gdf.at[seg_idx, 'Kommentar'] = override_comment
            
            applied_count += 1
    
    return applied_count, warnings, not_applied_count


def apply_text_overrides(network_gdf, text_overrides, matched_tilda_gdf):
    """
    Wendet Text-Overrides auf Netzwerk an.
    
    Args:
        network_gdf: GeoDataFrame mit Netzwerk-Segmenten (wird modifiziert)
        text_overrides: Dictionary mit Override-Einträgen {(element_nr, ri): {...}}
        matched_tilda_gdf: GeoDataFrame mit matched TILDA ways (für Attribut-Lookup)
    
    Returns:
        tuple: (Anzahl angewendeter Overrides, Liste von Warnungen bei Dopplungen, Anzahl nicht angewendeter Overrides)
    """
    if text_overrides is None or len(text_overrides) == 0:
        return 0, [], 0
    
    applied_count = 0
    warnings = []
    not_applied_count = 0
    
    # Track welche Segmente bereits Override haben (für Dopplung-Warnung)
    segments_with_override = set()
    
    for (element_nr, ri), override_config in text_overrides.items():
        tilda_id = override_config['tilda_id']
        direct_attributes = override_config.get('attributes', {})
        
        # Finde alle Segmente mit dieser element_nr und ri
        mask = (
            (network_gdf['element_nr'] == element_nr) & 
            (network_gdf['ri'] == ri)
        )
        affected_segments = network_gdf[mask].index.tolist()
        
        if not affected_segments:
            logging.debug(f"🔍 Text-Override element_nr={element_nr}, ri={ri}: Keine betroffenen Segmente gefunden")
            not_applied_count += 1
            continue
        
        # Hole Attribute zum Überschreiben
        override_attributes = {}
        
        # 1. Direkte Attribute aus Text-Override
        for attr in OVERRIDE_ATTRIBUTES:
            if attr in direct_attributes:
                override_attributes[attr] = direct_attributes[attr]
        
        # 2. Hole Attribute aus matched_tilda_ways via tilda_id
        if tilda_id and matched_tilda_gdf is not None:
            tilda_match = matched_tilda_gdf[matched_tilda_gdf['tilda_id'] == tilda_id]
            if not tilda_match.empty:
                tilda_row = tilda_match.iloc[0]
                for attr in OVERRIDE_ATTRIBUTES:
                    # Nur übernehmen wenn nicht schon direkt im Override gesetzt
                    if attr not in override_attributes and attr in tilda_row.index:
                        value = tilda_row[attr]
                        if value is not None:
                            override_attributes[attr] = value
            else:
                logging.warning(f"⚠️  Text-Override element_nr={element_nr}, ri={ri}: tilda_id={tilda_id} nicht in matched_tilda_ways gefunden")
        
        if not override_attributes:
            logging.debug(f"🔍 Text-Override element_nr={element_nr}, ri={ri}: Keine Attribute zum Überschreiben gefunden")
            not_applied_count += 1
            continue
        
        # Wende Override auf alle betroffenen Segmente an
        for seg_idx in affected_segments:
            # Prüfe auf Dopplung (aber nur warnen wenn bereits GeoPackage-Override)
            if seg_idx in segments_with_override:
                warnings.append(
                    f"⚠️  Segment element_nr={element_nr}, ri={ri} hat bereits Override "
                    f"(Text-Override wird ignoriert, GeoPackage hat Vorrang)"
                )
                continue  # Überspringe diesen Text-Override
            
            segments_with_override.add(seg_idx)
            
            # Überschreibe Attribute
            for attr, value in override_attributes.items():
                network_gdf.at[seg_idx, attr] = value
            
            # Lösche Prioritäts-Attribute
            for prio_attr in PRIORITY_ATTRIBUTES:
                if prio_attr in network_gdf.columns:
                    network_gdf.at[seg_idx, prio_attr] = None
            
            # Füge Kommentar hinzu
            existing_comment = network_gdf.at[seg_idx, 'Kommentar']
            override_comment = (
                f"Override angewendet; Quelle: Text; "
                f"tilda_id: {tilda_id}; "
                f"Attribute: {', '.join(override_attributes.keys())}"
            )
            
            if existing_comment and str(existing_comment).strip():
                network_gdf.at[seg_idx, 'Kommentar'] = f"{existing_comment}; {override_comment}"
            else:
                network_gdf.at[seg_idx, 'Kommentar'] = override_comment
            
            applied_count += 1
    
    return applied_count, warnings, not_applied_count


def main():
    parser = argparse.ArgumentParser(
        description="Wendet Override-Konfigurationen auf gesnappte Netzwerkdaten an"
    )
    parser.add_argument(
        "--clip",
        type=str,
        choices=["neukoelln", "norden", "sueden", "view"],
        help="Region für Clipping (optional)",
    )
    args = parser.parse_args()

    # Logging konfigurieren
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stdout
    )

    # Pfade
    project_dir = Path(__file__).parent.parent
    output_dir = project_dir / "output"
    snapping_dir = output_dir / "snapping"
    matched_dir = output_dir / "matched"
    data_dir = project_dir / "data"

    # Input-Dateien (snapping_converted_bikelanes liegt im Root von output/)
    if args.clip:
        input_file = output_dir / f"snapping_converted_bikelanes_{args.clip}.fgb"
        output_file = output_dir / f"snapping_with_overrides_{args.clip}.fgb"
    else:
        input_file = output_dir / "snapping_converted_bikelanes.fgb"
        output_file = output_dir / "snapping_with_overrides.fgb"
    
    matched_tilda_file = matched_dir / "matched_tilda_ways.fgb"
    override_gpkg_file = data_dir / "override_ways.gpkg"
    override_text_file = data_dir / "override_ways.txt"

    # Lade Netzwerk-Daten
    logging.info(f"📖 Lade Netzwerk-Daten aus {input_file}")
    if not input_file.exists():
        logging.error(f"❌ Input-Datei nicht gefunden: {input_file}")
        sys.exit(1)
    
    network_gdf = gpd.read_file(input_file)
    if network_gdf.crs != f"EPSG:{DEFAULT_CRS}":
        network_gdf = network_gdf.to_crs(DEFAULT_CRS)
    
    logging.info(f"✔  {len(network_gdf)} Netzwerk-Segmente geladen")

    # Lade matched TILDA ways
    matched_tilda_gdf = None
    if matched_tilda_file.exists():
        logging.info(f"📖 Lade matched TILDA ways aus {matched_tilda_file}")
        matched_tilda_gdf = gpd.read_file(matched_tilda_file)
        if matched_tilda_gdf.crs != f"EPSG:{DEFAULT_CRS}":
            matched_tilda_gdf = matched_tilda_gdf.to_crs(DEFAULT_CRS)
        logging.info(f"✔  {len(matched_tilda_gdf)} matched TILDA ways geladen")
    else:
        logging.warning(f"⚠️  matched_tilda_ways.fgb nicht gefunden - Attribut-Lookup eingeschränkt")

    # Lade Override-Konfigurationen
    logging.info("📖 Lade Override-Konfigurationen")
    override_gdf = load_override_geopackage(override_gpkg_file, DEFAULT_CRS)
    text_overrides = load_text_overrides(override_text_file)

    if override_gdf is None and text_overrides is None:
        logging.warning("⚠️  Keine Override-Konfigurationen gefunden - keine Änderungen")
        # Schreibe Input als Output
        network_gdf.to_file(output_file, driver="FlatGeobuf")
        logging.info(f"✔  Ausgabe geschrieben: {output_file}")
        sys.exit(0)

    # Wende GeoPackage-Overrides an (haben Vorrang)
    logging.info("🔧 Wende GeoPackage-Overrides an")
    gpkg_count, gpkg_warnings, gpkg_not_applied = apply_geopackage_overrides(network_gdf, override_gdf, matched_tilda_gdf)
    
    if gpkg_count > 0:
        logging.info(f"✔  {gpkg_count} Segmente durch GeoPackage-Overrides modifiziert")
    if gpkg_not_applied > 0:
        logging.info(f"ℹ️  {gpkg_not_applied} GeoPackage-Overrides konnten nicht angewendet werden")
    
    for warning in gpkg_warnings:
        logging.warning(warning)

    # Wende Text-Overrides an
    logging.info("🔧 Wende Text-Overrides an")
    text_count, text_warnings, text_not_applied = apply_text_overrides(network_gdf, text_overrides, matched_tilda_gdf)
    
    if text_count > 0:
        logging.info(f"✔  {text_count} Segmente durch Text-Overrides modifiziert")
    if text_not_applied > 0:
        logging.info(f"ℹ️  {text_not_applied} Text-Overrides konnten nicht angewendet werden")
    
    for warning in text_warnings:
        logging.warning(warning)

    # Zusammenfassung
    total_count = gpkg_count + text_count
    if total_count > 0:
        logging.info(f"✅ Insgesamt {total_count} Segmente durch Overrides modifiziert")
    else:
        logging.info("ℹ️  Keine Overrides angewendet")

    # Schreibe Output
    logging.info(f"💾 Schreibe Output nach {output_file}")
    network_gdf.to_file(output_file, driver="FlatGeobuf")
    logging.info(f"✔  Ausgabe geschrieben: {output_file}")


if __name__ == "__main__":
    main()
