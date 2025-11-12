"""
Dieses Modul behandelt manuelle Eingriffe in den Datenverarbeitungsprozess.
Es ermöglicht das Ausschließen und Einschließen von OSM-Wegen durch vordefinierte Listen.
Sowie das Überschreiben von Attributen durch Override-Konfiguration.
"""

import os
import json
import logging

def read_way_ids_from_file(file_path):
    """
    Liest OSM-Weg-IDs aus einer Textdatei.
    Jede Zeile der Datei sollte eine ID enthalten.
    Kommentare (beginnend mit #) und leere Zeilen werden ignoriert.

    Args:
        file_path (str): Der Pfad zur Textdatei.

    Returns:
        set: Ein Set von OSM-Weg-IDs.
    """
    if not os.path.exists(file_path):
        print(f"Warnung: Datei nicht gefunden: {file_path}")
        return set()

    with open(file_path, 'r') as f:
        lines = f.readlines()

    way_ids = set()
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            try:
                way_ids.add(int(line))
            except ValueError:
                print(f"Warnung: Ungültige ID in {file_path}: {line}")
    return way_ids

def get_excluded_ways(exclude_file_path='./data/exclude_ways.txt'):
    """
    Ruft die IDs der Wege ab, die explizit ausgeschlossen werden sollen.

    Args:
        exclude_file_path (str): Pfad zur Datei mit den auszuschließenden IDs.

    Returns:
        set: Ein Set von auszuschließenden OSM-Weg-IDs.
    """
    print(f"Lese manuell ausgeschlossene Wege aus {exclude_file_path}...")
    excluded_ids = read_way_ids_from_file(exclude_file_path)
    print(f"{len(excluded_ids)} Wege zum manuellen Ausschluss geladen.")
    return excluded_ids

def get_included_ways(include_file_path='./data/include_ways.txt'):
    """
    Ruft die IDs der Wege ab, die explizit eingeschlossen werden sollen.

    Args:
        include_file_path (str): Pfad zur Datei mit den einzuschließenden IDs.

    Returns:
        set: Ein Set von einzuschließenden OSM-Weg-IDs.
    """
    print(f"Lese manuell eingeschlossene Wege aus {include_file_path}...")
    included_ids = read_way_ids_from_file(include_file_path)
    print(f"{len(included_ids)} Wege zum manuellen Einschluss geladen.")
    return included_ids


def parse_override_entry(line, line_num):
    """
    Parst eine einzelne Override-Zeile im Format:
    tilda_id|element_nr|ri|attributes_json
    
    Args:
        line (str): Die zu parsende Zeile
        line_num (int): Zeilennummer für Fehlerausgabe
    
    Returns:
        dict oder None: Dictionary mit Override-Informationen oder None bei Fehler
        {
            'tilda_id': str,          # z.B. "way/123456"
            'element_nr': str,        # Element-Nummer als String
            'ri': int,                # Richtung (0 oder 1)
            'force_match': bool,      # Ob Match erzwungen werden soll
            'attributes': dict        # Zu überschreibende Attribute
        }
    """
    try:
        parts = line.split('|')
        if len(parts) != 4:
            logging.warning(
                f"Zeile {line_num}: Ungültiges Format (erwartet 4 Teile durch | getrennt): {line}"
            )
            return None
        
        tilda_id, element_nr, ri_str, attributes_json = parts
        
        # Validiere tilda_id Format (sollte "way/123" oder "relation/456" sein)
        tilda_id = tilda_id.strip()
        if not tilda_id or '/' not in tilda_id:
            logging.warning(
                f"Zeile {line_num}: Ungültige tilda_id (erwartet Format 'way/123456'): {tilda_id}"
            )
            return None
        
        # Parse element_nr (als String belassen)
        element_nr = element_nr.strip()
        if not element_nr:
            logging.warning(f"Zeile {line_num}: Leere element_nr: {line}")
            return None
        
        # Parse ri (muss 0 oder 1 sein)
        try:
            ri = int(ri_str.strip())
            if ri not in [0, 1]:
                logging.warning(
                    f"Zeile {line_num}: ri muss 0 oder 1 sein, ist aber {ri}: {line}"
                )
                return None
        except ValueError:
            logging.warning(
                f"Zeile {line_num}: ri muss eine Zahl sein (0 oder 1): {ri_str}"
            )
            return None
        
        # Parse JSON-Attribute
        try:
            attributes = json.loads(attributes_json.strip())
            if not isinstance(attributes, dict):
                logging.warning(
                    f"Zeile {line_num}: attributes_json muss ein JSON-Objekt sein: {attributes_json}"
                )
                return None
        except json.JSONDecodeError as e:
            logging.warning(
                f"Zeile {line_num}: Ungültiges JSON: {attributes_json} (Fehler: {e})"
            )
            return None
        
        # Extrahiere force_match Flag
        force_match = attributes.pop('force_match', False)
        if not isinstance(force_match, bool):
            # Versuche String zu Boolean zu konvertieren
            if isinstance(force_match, str):
                force_match = force_match.lower() in ['true', '1', 'yes']
            else:
                force_match = bool(force_match)
        
        return {
            'tilda_id': tilda_id,
            'element_nr': element_nr,
            'ri': ri,
            'force_match': force_match,
            'attributes': attributes
        }
        
    except Exception as e:
        logging.warning(
            f"Zeile {line_num}: Unerwarteter Fehler beim Parsen: {e} - {line}"
        )
        return None


def load_override_geopackage(override_gpkg_path='./data/override_ways.gpkg', crs=None):
    """
    Lädt Override-Konfigurationen aus einer GeoPackage-Datei.
    
    Die GeoPackage muss folgende Struktur haben:
    - geometry: LineString (Geometrie des zu überschreibenden Wegs im RVN)
    - tilda_id: Optional - wenn gesetzt, erzwingt diese TILDA-ID (force_match)
    - force_match: Optional Boolean - explizit force_match setzen
    - fuehr, pflicht, breite, ofm, farbe, protek, trennstreifen, nutz_beschr, Kommentar: Optional
    - override_reason: Optional Text - Begründung für Override
    
    Args:
        override_gpkg_path (str): Pfad zur Override-GeoPackage
        crs (str oder int): Ziel-CRS für Transformation
    
    Returns:
        GeoDataFrame oder None: GeoDataFrame mit Override-Informationen oder None wenn Datei nicht existiert
    """
    if not os.path.exists(override_gpkg_path):
        logging.info(f"Keine Override-GeoPackage gefunden: {override_gpkg_path}")
        return None
    
    try:
        import geopandas as gpd
        
        logging.info(f"Lade Override-GeoPackage aus {override_gpkg_path}...")
        gdf = gpd.read_file(override_gpkg_path)
        
        if len(gdf) == 0:
            logging.info(f"Override-GeoPackage ist leer: {override_gpkg_path}")
            return None
        
        # Transformiere zu Ziel-CRS falls angegeben
        if crs and gdf.crs != crs:
            logging.info(f"Transformiere Override-GeoPackage von {gdf.crs} zu {crs}")
            gdf = gdf.to_crs(crs)
        
        # Validiere dass geometry vorhanden ist
        if 'geometry' not in gdf.columns or gdf.geometry is None:
            logging.error(f"Override-GeoPackage hat keine gültige Geometrie-Spalte: {override_gpkg_path}")
            return None
        
        # Erstelle räumlichen Index für effiziente Suche
        gdf.sindex
        
        logging.info(f"✔  Override-GeoPackage geladen: {len(gdf)} Override-Einträge")
        
        # Logge vorhandene Override-Spalten
        override_attrs = []
        possible_attrs = ['tilda_id', 'force_match', 'fuehr', 'pflicht', 'breite', 'ofm', 
                         'farbe', 'protek', 'trennstreifen', 'nutz_beschr', 'Kommentar']
        for attr in possible_attrs:
            if attr in gdf.columns:
                non_null = gdf[attr].notna().sum()
                if non_null > 0:
                    override_attrs.append(f"{attr}({non_null})")
        
        if override_attrs:
            logging.info(f"  Verfügbare Override-Attribute: {', '.join(override_attrs)}")
        
        return gdf
        
    except Exception as e:
        logging.error(f"Fehler beim Laden der Override-GeoPackage: {e}")
        return None


def get_override_ways(override_file_path='./data/override_ways.txt'):
    """
    Lädt Override-Konfigurationen aus einer Textdatei.
    
    Format pro Zeile: tilda_id|element_nr|ri|attributes_json
    
    Beispiele:
    - way/123456|12345|0|{"force_match": true}
    - way/789012|67890|1|{"fuehr": "Radfahrstreifen", "pflicht": "ja"}
    
    Args:
        override_file_path (str): Pfad zur Override-Datei
    
    Returns:
        dict: Dictionary mit Override-Informationen, strukturiert als:
        {
            (element_nr, ri): {
                'tilda_id': str,
                'force_match': bool,
                'attributes': dict
            }
        }
    """
    if not os.path.exists(override_file_path):
        logging.info(f"Keine Override-Datei gefunden: {override_file_path}")
        return {}
    
    logging.info(f"Lese Override-Konfiguration aus {override_file_path}...")
    
    overrides = {}
    valid_count = 0
    error_count = 0
    
    with open(override_file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Überspringe leere Zeilen und Kommentare
            if not line or line.startswith('#'):
                continue
            
            parsed = parse_override_entry(line, line_num)
            if parsed:
                # Verwende (element_nr, ri) als Schlüssel
                key = (parsed['element_nr'], parsed['ri'])
                
                # Prüfe auf Duplikate
                if key in overrides:
                    logging.warning(
                        f"Zeile {line_num}: Duplikat für element_nr={parsed['element_nr']}, "
                        f"ri={parsed['ri']} - überschreibe vorherigen Eintrag"
                    )
                
                overrides[key] = {
                    'tilda_id': parsed['tilda_id'],
                    'force_match': parsed['force_match'],
                    'attributes': parsed['attributes']
                }
                valid_count += 1
                
                # Logge geladene Override-Informationen
                override_type = []
                if parsed['force_match']:
                    override_type.append("FORCE_MATCH")
                if parsed['attributes']:
                    override_type.append(f"ATTRS: {list(parsed['attributes'].keys())}")
                
                logging.debug(
                    f"  Override geladen: element_nr={parsed['element_nr']}, "
                    f"ri={parsed['ri']}, tilda_id={parsed['tilda_id']}, "
                    f"Typ=[{', '.join(override_type)}]"
                )
            else:
                error_count += 1
    
    if valid_count > 0:
        logging.info(
            f"✔  Override-Konfiguration geladen: {valid_count} gültige Einträge, "
            f"{error_count} Fehler"
        )
    else:
        logging.info(f"Keine gültigen Override-Einträge gefunden in {override_file_path}")
    
    return overrides


def find_spatial_override(segment_geometry, override_gdf, min_overlap_ratio=0.8):
    """
    Findet räumlich übereinstimmende Override-Einträge für ein Segment.
    
    Verwendet räumliche Überlappung (intersection) und prüft, ob mindestens
    min_overlap_ratio der Segment-Länge vom Override abgedeckt wird.
    
    Args:
        segment_geometry: Shapely LineString Geometrie des Segments
        override_gdf: GeoDataFrame mit Override-Einträgen
        min_overlap_ratio: Minimaler Überlappungsgrad (0.0-1.0), Standard: 0.8 (80%)
    
    Returns:
        dict oder None: Override-Informationen falls Match gefunden, sonst None
        {
            'tilda_id': str oder None,
            'force_match': bool,
            'attributes': dict,
            'override_reason': str oder None,
            'overlap_ratio': float
        }
    """
    if override_gdf is None or len(override_gdf) == 0:
        return None
    
    # Verwende räumlichen Index für effiziente Suche
    try:
        possible_matches_idx = list(override_gdf.sindex.intersection(segment_geometry.bounds))
    except Exception:
        # Fallback wenn sindex nicht verfügbar
        possible_matches_idx = list(range(len(override_gdf)))
    
    if not possible_matches_idx:
        return None
    
    # Prüfe alle möglichen Übereinstimmungen
    best_match = None
    best_overlap_ratio = 0.0
    
    segment_length = segment_geometry.length
    if segment_length == 0:
        return None
    
    for idx in possible_matches_idx:
        override_geom = override_gdf.iloc[idx].geometry
        
        # Berechne Überlappung
        try:
            intersection = segment_geometry.intersection(override_geom)
            overlap_length = intersection.length
            overlap_ratio = overlap_length / segment_length
            
            # Prüfe ob Schwellwert überschritten
            if overlap_ratio >= min_overlap_ratio and overlap_ratio > best_overlap_ratio:
                best_overlap_ratio = overlap_ratio
                best_match = override_gdf.iloc[idx]
                
        except Exception as e:
            logging.debug(f"Fehler bei räumlicher Überlappungsberechnung: {e}")
            continue
    
    if best_match is None:
        return None
    
    # Extrahiere Override-Attribute
    override_info = {
        'overlap_ratio': best_overlap_ratio,
        'force_match': False,
        'attributes': {},
        'tilda_id': None,
        'override_reason': None
    }
    
    # Extrahiere tilda_id falls vorhanden
    if 'tilda_id' in best_match and best_match['tilda_id'] is not None and str(best_match['tilda_id']).strip():
        override_info['tilda_id'] = str(best_match['tilda_id']).strip()
        override_info['force_match'] = True  # tilda_id impliziert force_match
    
    # Explizites force_match Flag (überschreibt implizites)
    if 'force_match' in best_match and best_match['force_match'] is not None:
        try:
            override_info['force_match'] = bool(best_match['force_match'])
        except Exception:
            pass
    
    # Extrahiere Override-Attribute
    possible_attrs = ['fuehr', 'pflicht', 'breite', 'ofm', 'farbe', 'protek', 
                     'trennstreifen', 'nutz_beschr', 'Kommentar']
    
    for attr in possible_attrs:
        if attr in best_match and best_match[attr] is not None:
            value = best_match[attr]
            # Überspringe leere Strings
            if isinstance(value, str) and not value.strip():
                continue
            override_info['attributes'][attr] = value
    
    # Extrahiere override_reason
    if 'override_reason' in best_match and best_match['override_reason'] is not None:
        reason = str(best_match['override_reason']).strip()
        if reason:
            override_info['override_reason'] = reason
    
    # Nur zurückgeben wenn mindestens tilda_id oder Attribute vorhanden
    if override_info['tilda_id'] or override_info['attributes']:
        return override_info
    
    return None
