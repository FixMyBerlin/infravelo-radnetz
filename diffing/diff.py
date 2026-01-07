#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff.py
-------
Compares two GeoJSON files based on element_nr and generates a diff report.

Usage:
    python diffing/diff.py OLD.geojson NEW.geojson

Outputs:
    - diffing/result/diff.geojson: GeoJSON with diff results
    - diffing/result/report.md: Summary report
"""

import argparse
import logging
import sys
import os
from datetime import datetime
from hashlib import sha256
import json
import math
import csv

import geopandas as gpd
from shapely.geometry import mapping, shape
from shapely import wkt


def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )


def get_file_mtime(filepath):
    """Get file modification time as formatted string."""
    if not os.path.exists(filepath):
        return "N/A"
    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')


def hash_geometry(geometry):
    """Hash a geometry using WKT representation."""
    wkt_str = geometry.wkt
    return sha256(wkt_str.encode('utf-8')).hexdigest()


def simplify_geometry(geometry, tolerance_meters=5):
    """Simplify geometry to remove nodes closer than tolerance_meters.

    Args:
        geometry: Shapely geometry object
        tolerance_meters: Tolerance in meters (default: 5)

    Returns:
        Simplified geometry
    """
    if geometry is None:
        return geometry

    # Convert to metric CRS for simplification (use EPSG:25833 for Berlin area)
    # Create a temporary GeoDataFrame for CRS conversion
    temp_gdf = gpd.GeoDataFrame([1], geometry=[geometry], crs='EPSG:4326')
    temp_gdf = temp_gdf.to_crs('EPSG:25833')

    # Simplify with tolerance in meters
    simplified_geom = temp_gdf.geometry.iloc[0].simplify(tolerance=tolerance_meters, preserve_topology=True)

    # Convert back to WGS84
    temp_gdf_simplified = gpd.GeoDataFrame([1], geometry=[simplified_geom], crs='EPSG:25833')
    temp_gdf_simplified = temp_gdf_simplified.to_crs('EPSG:4326')

    return temp_gdf_simplified.geometry.iloc[0]


def geometry_to_geojson_dict(geometry):
    """Convert Shapely geometry to GeoJSON geometry dict."""
    return mapping(geometry)


def get_type_name(value):
    """Get the type name of a value."""
    if value is None:
        return "None"
    return type(value).__name__


def format_value_for_diff(value):
    """Format a value for display in diff string."""
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    # For other types, convert to string
    return str(value)


def compare_properties(old_props, new_props):
    """Compare properties and return changed properties with _OLD and _NEW postfixes."""
    changed = {}
    all_keys = set(old_props.keys()) | set(new_props.keys())

    # Properties to exclude from diffing
    excluded_properties = {'element_nr', 'afid', 'tilda_link'}
    excluded_prefixes = ['prio_', 'angle_', 'value_']

    for key in all_keys:
        # Skip excluded properties
        if key in excluded_properties:
            continue

        # Skip properties with excluded prefixes
        if any(key.startswith(prefix) for prefix in excluded_prefixes):
            continue

        old_val = old_props.get(key)
        new_val = new_props.get(key)

        # Handle property added (exists in NEW but not in OLD)
        if old_val is None and new_val is not None:
            changed[f"{key}_NEW"] = new_val

        # Handle property removed (exists in OLD but not in NEW)
        elif old_val is not None and new_val is None:
            changed[f"{key}_OLD"] = old_val

        # Handle property changed (exists in both but different)
        elif old_val is not None and new_val is not None and old_val != new_val:
            changed[f"{key}_OLD"] = old_val
            changed[f"{key}_NEW"] = new_val

    return changed


def geometries_equal(geom1, geom2):
    """Check if two geometries are equal."""
    if geom1 is None and geom2 is None:
        return True
    if geom1 is None or geom2 is None:
        return False
    return geom1.equals(geom2)


def load_and_index_geojson(filepath):
    """Load GeoJSON and index by (element_nr, ri) composite key."""
    logging.info(f"Loading GeoJSON: {filepath}")
    gdf = gpd.read_file(filepath)

    # Ensure CRS is set (for geometry operations)
    if gdf.crs is None:
        logging.warning(f"No CRS found in {filepath}, assuming EPSG:4326")
        gdf.set_crs('EPSG:4326', inplace=True)

    # Index by (element_nr, ri) composite key
    indexed = {}
    missing_element_nr = 0
    missing_ri = 0

    for idx, row in gdf.iterrows():
        element_nr = row.get('element_nr')
        if element_nr is None:
            missing_element_nr += 1
            continue

        # Get ri value, default to 0 if missing
        ri = row.get('ri')
        if ri is None:
            ri = 0
            missing_ri += 1

        # Create composite key
        key = (element_nr, ri)

        if key in indexed:
            logging.warning(f"Duplicate (element_nr, ri) found: {element_nr}, ri={ri}")

        indexed[key] = row

    if missing_element_nr > 0:
        logging.warning(f"Found {missing_element_nr} features without element_nr")
    if missing_ri > 0:
        logging.warning(f"Found {missing_ri} features without ri (using 0 as default)")

    logging.info(f"Loaded {len(indexed)} features (indexed by element_nr and ri)")
    return indexed, gdf


def merge_delete_add_pairs(diff_features, stats, changed_property_keys):
    """Merge DELETE + ADD pairs with same element_nr into MODIFIED entries.

    When a feature is deleted and then added with the same element_nr,
    treat it as MODIFIED instead of separate DELETE + ADD actions.
    """
    # Group features by element_nr
    by_element_nr = {}
    for feature in diff_features:
        element_nr = feature['properties'].get('element_nr')
        if element_nr is None:
            continue
        if element_nr not in by_element_nr:
            by_element_nr[element_nr] = []
        by_element_nr[element_nr].append(feature)

    # Process each element_nr group
    merged_features = []
    processed_indices = set()

    for element_nr, features in by_element_nr.items():
        # Find DELETE and ADD features for this element_nr
        deleted_features = [f for f in features if f['properties'].get('_diff_action') == 'DELETED']
        added_features = [f for f in features if f['properties'].get('_diff_action') == 'ADDED']

        # Try to match DELETE + ADD pairs
        for del_feature in deleted_features:
            if id(del_feature) in processed_indices:
                continue

            del_props = del_feature['properties']
            del_ri = del_props.get('ri', 0)

            # Find matching ADD feature with same ri
            matching_add = None
            for add_feature in added_features:
                if id(add_feature) in processed_indices:
                    continue
                add_props = add_feature['properties']
                add_ri = add_props.get('ri', 0)

                if add_ri == del_ri:
                    # Extract base properties from DELETED (remove _OLD suffix)
                    del_base = {}
                    excluded = {'_diff_action', 'ri', 'element_nr', 'stroke', 'stroke-opacity',
                               'stroke-width', 'fill', 'fill-opacity'}
                    for k, v in del_props.items():
                        if k in excluded:
                            continue
                        if k.endswith('_OLD'):
                            base_key = k[:-4]  # Remove _OLD suffix
                            del_base[base_key] = v
                        elif not any(k.startswith(prefix) for prefix in ['prio_', 'angle_', 'value_']):
                            del_base[k] = v

                    # Extract base properties from ADDED (remove _NEW suffix)
                    add_base = {}
                    for k, v in add_props.items():
                        if k in excluded:
                            continue
                        if k.endswith('_NEW'):
                            base_key = k[:-4]  # Remove _NEW suffix
                            add_base[base_key] = v
                        elif not any(k.startswith(prefix) for prefix in ['prio_', 'angle_', 'value_']):
                            add_base[k] = v

                    # Compare base properties (excluding element_nr which is the same)
                    del_base_clean = {k: v for k, v in del_base.items() if k != 'element_nr'}
                    add_base_clean = {k: v for k, v in add_base.items() if k != 'element_nr'}

                    # If properties match (same feature), merge them into MODIFIED
                    # This handles cases where geometry changed but properties are the same
                    if del_base_clean == add_base_clean:
                        matching_add = add_feature
                        break

            if matching_add:
                # Merge into MODIFIED
                # Use the base properties we already extracted for comparison
                # Compare properties to find changes (geometry change is always present)
                changed_props = compare_properties(del_base, add_base)

                # Separate tilda_ and non-tilda_ changes
                tilda_changes = {}
                non_tilda_changes = {}

                for key, value in changed_props.items():
                    base_key = key
                    if key.endswith('_OLD') or key.endswith('_NEW'):
                        base_key = key[:-4]

                    if base_key.startswith('tilda_'):
                        tilda_changes[key] = value
                    else:
                        non_tilda_changes[key] = value

                # Create MODIFIED feature
                modified_props = {
                    '_diff_action': 'MODIFIED',
                    'element_nr': element_nr,
                    'ri': del_ri
                }
                modified_props.update(changed_props)

                # Convert GeoJSON dicts back to Shapely geometries
                old_geom = shape(del_feature['geometry'])
                new_geom = shape(matching_add['geometry'])

                # Add geometry hash and old geometry (geometry always changed in this case)
                modified_props['_geometry_hash'] = hash_geometry(new_geom)
                simplified_old_geom = simplify_geometry(old_geom, tolerance_meters=5)
                modified_props['_geometry_OLD'] = geometry_to_geojson_dict(simplified_old_geom)

                # Use NEW geometry
                simplified_new_geom = simplify_geometry(new_geom, tolerance_meters=5)

                # Track changed property keys
                for key in non_tilda_changes.keys():
                    base_key = key
                    if key.endswith('_OLD') or key.endswith('_NEW'):
                        base_key = key[:-4]
                    changed_property_keys[base_key] = changed_property_keys.get(base_key, 0) + 1

                merged_features.append({
                    'type': 'Feature',
                    'properties': modified_props,
                    'geometry': geometry_to_geojson_dict(simplified_new_geom)
                })

                # Mark both as processed
                processed_indices.add(id(del_feature))
                processed_indices.add(id(matching_add))

                # Update stats
                stats['deleted'] -= 1
                stats['added'] -= 1
                stats['modified'] += 1

    # Add all unprocessed features and merged features
    final_features = []
    for feature in diff_features:
        if id(feature) not in processed_indices:
            final_features.append(feature)
    final_features.extend(merged_features)

    return final_features, stats


def create_diff_features(old_indexed, new_indexed):
    """Create diff features comparing old and new GeoJSON."""
    diff_features = []
    stats = {
        'added': 0,
        'deleted': 0,
        'modified': 0,
        'unchanged': 0
    }
    changed_property_keys = {}  # Dictionary to track counts per property key

    # Find all (element_nr, ri) composite keys and sort for deterministic ordering
    all_keys = sorted(set(old_indexed.keys()) | set(new_indexed.keys()))

    for key in all_keys:
        old_row = old_indexed.get(key)
        new_row = new_indexed.get(key)

        # Extract element_nr and ri from key
        element_nr, ri = key

        if old_row is None and new_row is not None:
            # ADDED
            stats['added'] += 1
            props = dict(new_row.drop('geometry'))
            # Remove excluded properties
            excluded_properties = {'afid', 'tilda_link'}
            excluded_prefixes = ['prio_', 'angle_', 'value_']
            # Add _NEW postfix to all properties (except element_nr, ri, and _diff_action)
            new_props = {}
            for k, v in props.items():
                if k not in excluded_properties and not any(k.startswith(prefix) for prefix in excluded_prefixes):
                    if k in ['element_nr', 'ri']:
                        new_props[k] = v
                    else:
                        new_props[f"{k}_NEW"] = v
            new_props['_diff_action'] = 'ADDED'
            # Simplify geometry before adding
            simplified_geom = simplify_geometry(new_row.geometry, tolerance_meters=5)
            diff_features.append({
                'type': 'Feature',
                'properties': new_props,
                'geometry': geometry_to_geojson_dict(simplified_geom)
            })

        elif old_row is not None and new_row is None:
            # DELETED
            stats['deleted'] += 1
            props = dict(old_row.drop('geometry'))
            # Remove excluded properties
            excluded_properties = {'afid', 'tilda_link'}
            excluded_prefixes = ['prio_', 'angle_', 'value_']
            # Add _OLD postfix to all properties (except element_nr, ri, and _diff_action)
            old_props = {}
            for k, v in props.items():
                if k not in excluded_properties and not any(k.startswith(prefix) for prefix in excluded_prefixes):
                    if k in ['element_nr', 'ri']:
                        old_props[k] = v
                    else:
                        old_props[f"{k}_OLD"] = v
            old_props['_diff_action'] = 'DELETED'
            # Simplify geometry before adding
            simplified_geom = simplify_geometry(old_row.geometry, tolerance_meters=5)
            diff_features.append({
                'type': 'Feature',
                'properties': old_props,
                'geometry': geometry_to_geojson_dict(simplified_geom)
            })

        elif old_row is not None and new_row is not None:
            # Check if modified
            old_props = dict(old_row.drop('geometry'))
            new_props = dict(new_row.drop('geometry'))
            changed_props = compare_properties(old_props, new_props)

            # Check geometry
            geom_changed = not geometries_equal(old_row.geometry, new_row.geometry)

            if changed_props or geom_changed:
                # Separate tilda_ and non-tilda_ changes
                tilda_changes = {}
                non_tilda_changes = {}

                for key, value in changed_props.items():
                    # Extract base property name (remove _OLD or _NEW suffix)
                    base_key = key
                    if key.endswith('_OLD') or key.endswith('_NEW'):
                        base_key = key[:-4]  # Remove _OLD or _NEW

                    if base_key.startswith('tilda_'):
                        tilda_changes[key] = value
                    else:
                        non_tilda_changes[key] = value

                # Only include MODIFIED features if they have non-tilda_ changes or geometry changes
                if non_tilda_changes or geom_changed:
                    # MODIFIED
                    stats['modified'] += 1
                    props = {'_diff_action': 'MODIFIED', 'element_nr': element_nr, 'ri': ri}

                    # Add all changed properties (both tilda_ and non-tilda_)
                    props.update(changed_props)

                    # Track counts per property key (base names without _OLD/_NEW)
                    # Only track non-tilda_ properties for the report
                    for key in non_tilda_changes.keys():
                        # Extract base property name (remove _OLD or _NEW suffix)
                        base_key = key
                        if key.endswith('_OLD') or key.endswith('_NEW'):
                            base_key = key[:-4]  # Remove _OLD or _NEW
                        changed_property_keys[base_key] = changed_property_keys.get(base_key, 0) + 1

                    # Add geometry hash (always from NEW) - prefix with underscore
                    props['_geometry_hash'] = hash_geometry(new_row.geometry)

                    # Add old geometry if changed - prefix with underscore
                    if geom_changed:
                        simplified_old_geom = simplify_geometry(old_row.geometry, tolerance_meters=5)
                        props['_geometry_OLD'] = geometry_to_geojson_dict(simplified_old_geom)

                    # Simplify geometry before adding
                    simplified_new_geom = simplify_geometry(new_row.geometry, tolerance_meters=5)
                    diff_features.append({
                        'type': 'Feature',
                        'properties': props,
                        'geometry': geometry_to_geojson_dict(simplified_new_geom)
                    })
                else:
                    # Only tilda_ changes, no geometry changes - skip this feature
                    stats['unchanged'] += 1
            else:
                # UNCHANGED
                stats['unchanged'] += 1

    # Post-process: merge DELETE + ADD pairs with same element_nr into MODIFIED
    diff_features, stats = merge_delete_add_pairs(diff_features, stats, changed_property_keys)

    return diff_features, stats, changed_property_keys


def clean_json_value(value):
    """Clean a value for JSON serialization, handling NaN and Infinity."""
    if isinstance(value, float):
        if math.isnan(value):
            return None  # Convert NaN to null
        if math.isinf(value):
            return None  # Convert Infinity to null
    return value


def round_numbers(obj, precision=8):
    """Recursively round floating point numbers to specified precision."""
    if isinstance(obj, dict):
        return {k: round_numbers(v, precision) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [round_numbers(item, precision) for item in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return obj  # Will be handled by clean_json_value
        return round(obj, precision)
    else:
        return obj


def clean_json_object(obj):
    """Recursively clean a JSON-serializable object, replacing NaN and Infinity."""
    if isinstance(obj, dict):
        return {k: clean_json_object(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json_object(item) for item in obj]
    else:
        return clean_json_value(obj)


def calculate_geometry_centroid(geometry):
    """Calculate centroid of a geometry.

    Args:
        geometry: Shapely geometry object (LineString or MultiLineString)

    Returns:
        tuple: (lng, lat) with 6 decimal places, or None on error
    """
    try:
        if hasattr(geometry, 'geoms'):  # MultiLineString
            all_coords = []
            for line in geometry.geoms:
                all_coords.extend(list(line.coords))
        elif hasattr(geometry, 'coords'):
            all_coords = list(geometry.coords)
        else:
            return None

        if len(all_coords) < 1:
            return None

        lngs = [coord[0] for coord in all_coords]
        lats = [coord[1] for coord in all_coords]

        center_lng = round(sum(lngs) / len(lngs), 6)
        center_lat = round(sum(lats) / len(lats), 6)

        return (center_lng, center_lat)
    except Exception as e:
        logging.warning(f"Error calculating centroid: {e}")
        return None


def generate_tilda_link(geometry, zoom=17.4, dataset="infravelo-datensatz-c-fortlaufend"):
    """Generate TILDA link based on geometry.

    Args:
        geometry: Shapely geometry object (assumed to be in WGS84/EPSG:4326)
        zoom: Zoom level for the map (default: 17.4)
        dataset: Dataset identifier (default: "infravelo-datensatz-c-fortlaufend")

    Returns:
        str: Full TILDA link or None on error
    """
    try:
        centroid = calculate_geometry_centroid(geometry)
        if not centroid:
            return None

        center_lng, center_lat = centroid

        base_url = "https://tilda-geo.de/regionen/infravelo"
        map_param = f"map={zoom}/{center_lat}/{center_lng}"
        data_param = f"data={dataset}"
        full_url = f"{base_url}?{map_param}&{data_param}"

        return full_url
    except Exception as e:
        logging.warning(f"Error generating TILDA link: {e}")
        return None


def write_diff_csv(diff_features, output_path):
    """Write diff features to CSV file.

    Args:
        diff_features: List of diff feature dictionaries
        output_path: Path to output CSV file
    """
    logging.info(f"Writing diff CSV: {output_path}")

    if not diff_features:
        logging.warning("No features to write to CSV")
        return

    # Collect all property keys from all features
    all_keys = set()
    for feature in diff_features:
        all_keys.update(feature['properties'].keys())

    # Remove geometry-related keys and style keys
    excluded_keys = {'_geometry_hash', '_geometry_OLD', 'stroke', 'stroke-opacity',
                     'stroke-width', 'fill', 'fill-opacity'}
    filtered_keys = [k for k in all_keys if k not in excluded_keys]

    # Sort keys using the same order as GeoJSON properties:
    # 1. _-prefixed properties (sorted a-z)
    # 2. All other properties (not prefixed, sorted a-z)
    # 3. tilda_-prefixed properties (sorted a-z)
    # 4. prio_-prefixed properties (sorted a-z)
    underscore_keys = sorted([k for k in filtered_keys if k.startswith('_')])
    other_keys = sorted([k for k in filtered_keys if not k.startswith('_') and
                        not k.startswith('tilda_') and not k.startswith('prio_')])
    tilda_keys = sorted([k for k in filtered_keys if k.startswith('tilda_')])
    prio_keys = sorted([k for k in filtered_keys if k.startswith('prio_')])

    csv_keys = underscore_keys + other_keys + tilda_keys + prio_keys

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['TILDA_Link'] + csv_keys, extrasaction='ignore')
        writer.writeheader()

        for feature in diff_features:
            props = feature['properties'].copy()

            # Generate TILDA link from geometry
            geom = shape(feature['geometry'])
            tilda_link = generate_tilda_link(geom)

            # Prepare row data
            row = {'TILDA_Link': tilda_link or ''}

            # Add all properties, converting None to empty string and handling dicts
            for key in csv_keys:
                value = props.get(key)
                if value is None:
                    row[key] = ''
                elif isinstance(value, dict):
                    # For _geometry_OLD or other dicts, convert to JSON string
                    row[key] = json.dumps(value)
                elif isinstance(value, (int, float)):
                    # Handle NaN and Infinity
                    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                        row[key] = ''
                    else:
                        row[key] = value
                else:
                    row[key] = str(value)

            writer.writerow(row)

    logging.info(f"Written {len(diff_features)} diff features to {output_path}")


def sort_properties(props):
    """Sort properties according to specified order:
    1. _-prefixed properties (sorted a-z)
    2. All other properties (not prefixed, sorted a-z)
    3. tilda_-prefixed properties (sorted a-z)
    4. prio_-prefixed properties (sorted a-z)
    """
    underscore_props = {}
    tilda_props = {}
    prio_props = {}
    other_props = {}

    for k, v in props.items():
        if k.startswith('_'):
            underscore_props[k] = v
        elif k.startswith('tilda_'):
            tilda_props[k] = v
        elif k.startswith('prio_'):
            prio_props[k] = v
        else:
            other_props[k] = v

    # Sort each group alphabetically and combine in specified order
    sorted_props = {}
    sorted_props.update(sorted(underscore_props.items()))
    sorted_props.update(sorted(other_props.items()))
    sorted_props.update(sorted(tilda_props.items()))
    sorted_props.update(sorted(prio_props.items()))

    return sorted_props


def write_diff_geojson(diff_features, output_path):
    """Write diff features to GeoJSON file."""
    logging.info(f"Writing diff GeoJSON: {output_path}")

    # Remove null values from properties to keep output clean
    # Also filter out _geometry_OLD from null check since it's a dict
    cleaned_features = []
    for feature in diff_features:
        cleaned_props = {}
        for k, v in feature['properties'].items():
            # Keep _geometry_OLD even if it's a dict (it's always valid)
            if v is not None or k == '_geometry_OLD':
                cleaned_props[k] = v

        # Add style properties based on diff action and ri value
        diff_action = cleaned_props.get('_diff_action')
        ri = cleaned_props.get('ri', 0)

        # Set stroke color based on action
        if diff_action == 'ADDED':
            cleaned_props['stroke'] = '#0000FF'  # blue
        elif diff_action == 'DELETED':
            cleaned_props['stroke'] = '#FF0000'  # red
        elif diff_action == 'MODIFIED':
            cleaned_props['stroke'] = '#000000'  # black

        # Set stroke style properties
        cleaned_props['stroke-opacity'] = 1.0
        cleaned_props['stroke-width'] = 2

        # Sort properties according to specified order
        sorted_props = sort_properties(cleaned_props)

        cleaned_feature = {
            'type': feature['type'],
            'properties': sorted_props,
            'geometry': feature['geometry']
        }
        cleaned_features.append(cleaned_feature)

    feature_collection = {
        'type': 'FeatureCollection',
        'features': cleaned_features
    }

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Round numbers to 8 decimal places, then clean NaN and Infinity values
    rounded_collection = round_numbers(feature_collection, precision=8)
    cleaned_collection = clean_json_object(rounded_collection)

    # Write GeoJSON directly as JSON with custom encoder for 8 decimal precision
    with open(output_path, 'w', encoding='utf-8') as f:
        # Use custom formatting to ensure 8 decimal places max
        json_str = json.dumps(cleaned_collection, ensure_ascii=False, indent=2)
        # Replace all float numbers with 8 decimal precision
        import re
        def format_float(match):
            num = float(match.group(0))
            if math.isnan(num) or math.isinf(num):
                return 'null'
            formatted = f'{num:.8f}'.rstrip('0').rstrip('.')
            return formatted

        # Pattern to match floating point numbers in JSON
        float_pattern = r'-?\d+\.\d+'
        formatted_json = re.sub(float_pattern, format_float, json_str)
        f.write(formatted_json)

    logging.info(f"Written {len(diff_features)} diff features to {output_path}")


def filter_features_by_attribute(diff_features, attribute_name):
    """Filter features that have changes in a specific attribute.
    
    Args:
        diff_features: List of all diff features
        attribute_name: Name of the attribute to filter by (e.g., 'fuehr', 'breite')
    
    Returns:
        List of features where the specified attribute changed
    """
    filtered_features = []
    
    for feature in diff_features:
        props = feature['properties']
        action = props.get('_diff_action')
        
        # Check if the target attribute changed
        attribute_changed = f'{attribute_name}_OLD' in props or f'{attribute_name}_NEW' in props
        
        if attribute_changed:
            filtered_features.append(feature)
    
    return filtered_features


def filter_features_excluding_attributes(diff_features, excluded_attributes):
    """Filter features that have changes in properties other than the excluded attributes.
    
    Args:
        diff_features: List of all diff features
        excluded_attributes: List of attribute names to exclude (e.g., ['fuehr', 'breite'])
    
    Returns:
        List of features where properties other than excluded attributes changed
    """
    filtered_features = []
    
    for feature in diff_features:
        props = feature['properties']
        action = props.get('_diff_action')
        
        # Check if any other (non-excluded) properties changed
        other_changed = False
        for key in props.keys():
            if key not in ['_diff_action', 'element_nr', 'ri', '_geometry_hash', '_geometry_OLD',
                          'stroke', 'stroke-opacity', 'stroke-width', 'fill', 'fill-opacity']:
                # Extract base property name
                base_key = key
                if key.endswith('_OLD') or key.endswith('_NEW'):
                    base_key = key[:-4]
                
                # Check if this property is not in the excluded list
                if base_key not in excluded_attributes:
                    other_changed = True
                    break
        
        if other_changed:
            filtered_features.append(feature)
    
    return filtered_features


def write_report(stats, changed_property_keys, old_file, new_file,
                 diff_fuehr_path, diff_breite_path, diff_properties_path,
                 diff_fuehr_csv_path, diff_breite_csv_path, diff_properties_csv_path,
                 report_path, execution_time):
    """Write markdown report."""
    logging.info(f"Writing report: {report_path}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    # Write report first to get its mtime
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# GeoJSON Diff Report\n\n")
        f.write(f"**Diff executed:** {execution_time}\n\n")

        f.write("## Input Files\n\n")
        f.write(f"- **OLD:** `{old_file}`\n")
        f.write(f"  - Modified: {get_file_mtime(old_file)}\n")
        f.write(f"- **NEW:** `{new_file}`\n")
        f.write(f"  - Modified: {get_file_mtime(new_file)}\n\n")

        f.write("## Output Files\n\n")
        f.write(f"- **diff_fuehr.geojson:** `{diff_fuehr_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(diff_fuehr_path)}\n")
        f.write(f"- **diff_fuehr.csv:** `{diff_fuehr_csv_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(diff_fuehr_csv_path)}\n")
        f.write(f"- **diff_breite.geojson:** `{diff_breite_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(diff_breite_path)}\n")
        f.write(f"- **diff_breite.csv:** `{diff_breite_csv_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(diff_breite_csv_path)}\n")
        f.write(f"- **diff_properties.geojson:** `{diff_properties_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(diff_properties_path)}\n")
        f.write(f"- **diff_properties.csv:** `{diff_properties_csv_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(diff_properties_csv_path)}\n")
        f.write(f"- **report.md:** `{report_path}`\n")
        f.write(f"  - Modified: {get_file_mtime(report_path)}\n\n")

        f.write("## Summary Statistics\n\n")
        f.write(f"- **ADDED:** {stats['added']}\n")
        f.write(f"- **DELETED:** {stats['deleted']}\n")
        f.write(f"- **MODIFIED:** {stats['modified']}\n")
        f.write(f"- **UNCHANGED:** {stats['unchanged']}\n")
        f.write(f"- **TOTAL:** {sum(stats.values())}\n\n")

        if changed_property_keys:
            f.write("## Changed Property Keys\n\n")
            f.write("The following property keys were modified (values not shown):\n\n")
            # Sort by count (descending), then by key name
            sorted_keys = sorted(changed_property_keys.items(), key=lambda x: (-x[1], x[0]))
            for key, count in sorted_keys:
                f.write(f"- `{key}`: {count} feature(s)\n")
            f.write("\n")

    logging.info(f"Report written to {report_path}")


def main():
    """Main function."""
    setup_logging()

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Compare two GeoJSON files by element_nr and generate diff report."
    )
    parser.add_argument(
        'old_file',
        help='Path to OLD GeoJSON file'
    )
    parser.add_argument(
        'new_file',
        help='Path to NEW GeoJSON file'
    )
    parser.add_argument(
        '--output-dir',
        default='./diffing/result',
        help='Output directory for diff.geojson and report.md (default: ./diffing/result)'
    )

    args = parser.parse_args()

    # Validate input files
    if not os.path.exists(args.old_file):
        logging.error(f"OLD file not found: {args.old_file}")
        sys.exit(1)

    if not os.path.exists(args.new_file):
        logging.error(f"NEW file not found: {args.new_file}")
        sys.exit(1)

    # Record execution time
    execution_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        # Load and index GeoJSON files
        old_indexed, _ = load_and_index_geojson(args.old_file)
        new_indexed, _ = load_and_index_geojson(args.new_file)

        # Create diff features
        logging.info("Comparing features...")
        diff_features, stats, changed_property_keys = create_diff_features(
            old_indexed, new_indexed
        )

        # Split features into fuehr, breite, and properties diffs using modular functions
        logging.info("Splitting features by attribute changes...")
        fuehr_features = filter_features_by_attribute(diff_features, 'fuehr')
        breite_features = filter_features_by_attribute(diff_features, 'breite')
        properties_features = filter_features_excluding_attributes(diff_features, ['fuehr', 'breite'])

        # Output paths
        diff_fuehr_path = os.path.join(args.output_dir, 'diff_fuehr.geojson')
        diff_breite_path = os.path.join(args.output_dir, 'diff_breite.geojson')
        diff_properties_path = os.path.join(args.output_dir, 'diff_properties.geojson')
        diff_fuehr_csv_path = os.path.join(args.output_dir, 'diff_fuehr.csv')
        diff_breite_csv_path = os.path.join(args.output_dir, 'diff_breite.csv')
        diff_properties_csv_path = os.path.join(args.output_dir, 'diff_properties.csv')
        report_path = os.path.join(args.output_dir, 'report.md')

        # Write outputs
        write_diff_geojson(fuehr_features, diff_fuehr_path)
        write_diff_geojson(breite_features, diff_breite_path)
        write_diff_geojson(properties_features, diff_properties_path)
        write_diff_csv(fuehr_features, diff_fuehr_csv_path)
        write_diff_csv(breite_features, diff_breite_csv_path)
        write_diff_csv(properties_features, diff_properties_csv_path)
        write_report(stats, changed_property_keys, args.old_file, args.new_file,
                    diff_fuehr_path, diff_breite_path, diff_properties_path,
                    diff_fuehr_csv_path, diff_breite_csv_path, diff_properties_csv_path,
                    report_path, execution_time)

        logging.info("=" * 60)
        logging.info("✔ Diff completed successfully!")
        logging.info(f"  - Diff fuehr GeoJSON: {diff_fuehr_path} ({len(fuehr_features)} features)")
        logging.info(f"  - Diff fuehr CSV: {diff_fuehr_csv_path} ({len(fuehr_features)} features)")
        logging.info(f"  - Diff breite GeoJSON: {diff_breite_path} ({len(breite_features)} features)")
        logging.info(f"  - Diff breite CSV: {diff_breite_csv_path} ({len(breite_features)} features)")
        logging.info(f"  - Diff properties GeoJSON: {diff_properties_path} ({len(properties_features)} features)")
        logging.info(f"  - Diff properties CSV: {diff_properties_csv_path} ({len(properties_features)} features)")
        logging.info(f"  - Report: {report_path}")
        logging.info(f"  - Summary: {stats['added']} added, {stats['deleted']} deleted, "
                    f"{stats['modified']} modified, {stats['unchanged']} unchanged")
        logging.info("=" * 60)

    except Exception as e:
        logging.error(f"Error during diff: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
