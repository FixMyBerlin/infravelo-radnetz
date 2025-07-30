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
    
    Gibt nur die Teile der Straßen zurück, die nicht im Buffer (BUFFER_METERS) 
    um Radwege liegen. Ein Buffer wird um alle Radwege gelegt, und alle Straßen, 
    die diesen Buffer schneiden, werden entfernt.
    
    Args:
        streets_gdf (GeoDataFrame): GeoDataFrame mit Straßengeometrien
        bikelanes_gdf (GeoDataFrame): GeoDataFrame mit Radweggeometrien
        target_crs (str, optional): Ziel-CRS für Projektion vor Pufferung (z.B. 'EPSG:25833').
                                   Wenn None, wird nicht reprojiziert.
    
    Returns:
        GeoDataFrame: Straßen ohne Überschneidung mit Radwegen-Buffern
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
    
    # Alle Buffer zu einer Geometrie vereinen für effiziente Differenzberechnung
    bikelanes_union = bikelanes_buffer.unary_union
    
    # Differenz berechnen: Straßengeometrien minus Radwege-Buffer
    logging.info("Berechne Differenz: Entferne Linien im Radwege/Straßen-Buffer...")
    diff_geoms = streets_gdf.geometry.apply(
        lambda geom: geom.difference(bikelanes_union) if not geom.is_empty else geom
    )
    
    # Ergebnis-GeoDataFrame erstellen
    result_gdf = streets_gdf.copy()
    result_gdf["geometry"] = diff_geoms
    
    # Leere Geometrien entfernen
    result_gdf = result_gdf[~result_gdf.geometry.is_empty & result_gdf.geometry.notnull()]
    
    return result_gdf


def get_or_create_difference_fgb(streets_gdf, bikelanes_gdf, output_path, target_crs=None):
    """
    Berechnet die Differenz zwischen Straßen und Radwegen und speichert sie als FlatGeobuf.
    
    Berechnet immer neu um Cache-Probleme zu vermeiden und aktuelle Daten zu gewährleisten.
    
    Args:
        streets_gdf (GeoDataFrame): GeoDataFrame mit Straßengeometrien
        bikelanes_gdf (GeoDataFrame): GeoDataFrame mit Radweggeometrien
        output_path (str): Pfad zur Ausgabedatei (FlatGeobuf)
        target_crs (str, optional): Ziel-CRS für Projektion vor Pufferung
    
    Returns:
        GeoDataFrame: Straßen ohne Überschneidung mit Radwegen-Buffern
    """
    # Differenz immer neu berechnen um Cache-Probleme zu vermeiden
    logging.info("Berechne Differenz: nur Straßen ohne Radwege...")
    diff_gdf = difference_streets_without_bikelanes(streets_gdf, bikelanes_gdf, target_crs=target_crs)
    
    # Ergebnis als FlatGeobuf speichern
    diff_gdf.to_file(output_path, driver='FlatGeobuf')
    logging.info(f'Differenz gespeichert als {output_path} ({len(diff_gdf)} Features)')
    
    return diff_gdf
