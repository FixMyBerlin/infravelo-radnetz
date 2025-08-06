"""
Modul zur Berechnung der Differenz zwischen Straßen und Radwegen.

Dieses Modul enthält Funktionen zur Identifikation von Straßenabschnitten,
die nicht im Buffer-Bereich um Radwege liegen. Dies ist nützlich für die
Analyse von Straßen ohne dedizierte Radinfrastruktur.

Input:
- Straßen-GeoDataFrame
- Radwege-GeoDataFrame

Output:
- Bereinigte Straßen ohne Radwege-Überschneidungen (FlatGeobuf)
"""

import os
import logging
import geopandas as gpd
from helpers.globals import DEFAULT_CRS

# Konstanten
BUFFER_METERS = 10  # Buffer-Radius in Metern für die Differenzbildung


def difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf, target_crs=None):
    """
    Berechnet die Differenz zwischen Straßen und Radwegen.
    
    Entfernt vollständig alle Straßen, die zu 80% oder mehr im Buffer (BUFFER_METERS) 
    um Radwege liegen. Straßen mit weniger als 80% Überschneidung bleiben vollständig erhalten.
    
    Args:
        streets_gdf (GeoDataFrame): GeoDataFrame mit Straßengeometrien
        bikelanes_gdf (GeoDataFrame): GeoDataFrame mit Radweggeometrien
        target_crs (str, optional): Ziel-CRS für Projektion vor Pufferung (z.B. 'EPSG:25833').
                                   Wenn None, wird nicht reprojiziert.
    
    Returns:
        GeoDataFrame: Straßen mit weniger als 80% Überschneidung mit Radwegen-Buffern
    """
    # Sicherstellen, dass beide GeoDataFrames im projizierten CRS vorliegen für korrekte Pufferung
    if target_crs is not None:
        if streets_gdf.crs != target_crs:
            streets_gdf = streets_gdf.to_crs(target_crs)
        if bikelanes_gdf.crs != target_crs:
            bikelanes_gdf = bikelanes_gdf.to_crs(target_crs)
    else:
        target_crs = f"EPSG:{DEFAULT_CRS}"
    
    # Buffer um Radwege erstellen
    logging.info(f"Erzeuge {BUFFER_METERS}m Buffer um Radwege...")
    bikelanes_buffer = bikelanes_gdf.buffer(BUFFER_METERS, cap_style='flat')
    
    # Alle Buffer zu einer Geometrie vereinen für effiziente Berechnung
    bikelanes_union = bikelanes_buffer.unary_union
    
    # Berechne für jede Straße den Anteil, der im Buffer liegt
    logging.info("Berechne Überschneidungsanteile: Entferne Straßen mit >80% Überschneidung...")
    
    def calculate_overlap_ratio(geom):
        """Berechnet den Anteil einer Geometrie, der im Buffer liegt."""
        if geom.is_empty:
            return 0.0
        
        intersection = geom.intersection(bikelanes_union)
        if intersection.is_empty:
            return 0.0
        
        # Verhältnis der Längen berechnen
        return intersection.length / geom.length if geom.length > 0 else 0.0
    
    # Überschneidungsanteile berechnen
    overlap_ratios = streets_gdf.geometry.apply(calculate_overlap_ratio)
    
    # Nur Straßen behalten, die weniger als 80% im Buffer liegen
    threshold = 0.8
    keep_mask = overlap_ratios < threshold
    result_gdf = streets_gdf[keep_mask].copy()
    
    logging.info(f"Von {len(streets_gdf)} Straßen bleiben {len(result_gdf)} erhalten "
                f"(entfernt: {len(streets_gdf) - len(result_gdf)} mit ≥{threshold*100}% Überschneidung)")
    
    return result_gdf


def get_or_create_difference_fgb(streets_gdf, bikelanes_gdf, output_path, target_crs=None):
    """
    Berechnet die Differenz zwischen Straßen und Radwegen und speichert sie als FlatGeobuf.
    
    Entfernt vollständig alle Straßen, die zu 80% oder mehr im Buffer um Radwege liegen.
    Berechnet immer neu um Cache-Probleme zu vermeiden und aktuelle Daten zu gewährleisten.
    
    Args:
        streets_gdf (GeoDataFrame): GeoDataFrame mit Straßengeometrien
        bikelanes_gdf (GeoDataFrame): GeoDataFrame mit Radweggeometrien
        output_path (str): Pfad zur Ausgabedatei (FlatGeobuf)
        target_crs (str, optional): Ziel-CRS für Projektion vor Pufferung
    
    Returns:
        GeoDataFrame: Straßen mit weniger als 80% Überschneidung mit Radwegen-Buffern
    """
    # Differenz immer neu berechnen um Cache-Probleme zu vermeiden
    logging.info("Berechne Differenz: entferne Straßen mit ≥80% Überschneidung mit Radwegen...")
    diff_gdf = difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf, target_crs=target_crs)
    
    # Ergebnis als FlatGeobuf speichern
    diff_gdf.to_file(output_path, driver='FlatGeobuf')
    logging.info(f'Differenz gespeichert als {output_path} ({len(diff_gdf)} Features)')
    
    return diff_gdf
