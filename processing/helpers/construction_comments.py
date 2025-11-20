#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
construction_comments.py
------------------------
Hilfsfunktionen für die Generierung und Aktualisierung von Baustellen-Kommentaren.

Diese Funktionen werden sowohl in der TILDA-Übersetzung als auch im Snapping verwendet,
um konsistente Kommentare für Baustellen zu generieren.
"""

import logging


def collect_todo_attributes(row, attribute_names: list) -> list:
    """
    Sammelt alle Attribute die einen [TODO] Wert enthalten.
    
    Args:
        row: Datenzeile mit RVN-Attributen (pandas Series oder dict-like)
        attribute_names: Liste der zu prüfenden Attributnamen
    
    Returns:
        Liste von Attributnamen, die TODO enthalten
    """
    todo_attrs = []
    
    for attr in attribute_names:
        # Prüfe ob das Attribut existiert (sowohl für Series.index als auch dict-like)
        if hasattr(row, 'index') and attr in row.index:
            value = str(row.get(attr, "")).strip()
        elif attr in row:
            value = str(row.get(attr, "")).strip()
        else:
            continue
            
        if value and "[TODO]" in value.upper():
            todo_attrs.append(attr)
    
    return todo_attrs


def update_construction_comments(gdf, attribute_names: list = None):
    """
    Aktualisiert Kommentare für Baustellen-Segmente um fehlende TODO-Attribute zu ergänzen.
    Diese Funktion kann in verschiedenen Verarbeitungsschritten aufgerufen werden,
    um die Kommentare zu aktualisieren wenn neue TODO-Werte hinzugefügt wurden.
    
    Args:
        gdf: GeoDataFrame mit Segmenten
        attribute_names: Liste der zu prüfenden Attributnamen. 
                        Falls None, werden Standard-RVN-Attribute verwendet.
    
    Returns:
        Anzahl der aktualisierten Kommentare
    """
    if attribute_names is None:
        # Standard RVN-Attribute
        attribute_names = ["pflicht", "breite", "ofm", "farbe", "protek", 
                          "trennstreifen", "nutz_beschr", "fuehr", "verkehrsri"]
    
    # Prüfe ob Kommentar-Spalte existiert
    if 'Kommentar' not in gdf.columns:
        logging.warning("Spalte 'Kommentar' nicht gefunden - überspringe Aktualisierung")
        return 0
    
    # Finde alle Segmente mit Baustellen-Kommentar
    has_baustelle = gdf['Kommentar'].notna() & gdf['Kommentar'].astype(str).str.contains('Baustelle', case=False, na=False)
    
    if has_baustelle.sum() == 0:
        return 0
    
    update_count = 0
    
    for idx in gdf[has_baustelle].index:
        # Sammle alle TODO-Attribute für dieses Segment
        row = gdf.loc[idx]
        todo_attrs = collect_todo_attributes(row, attribute_names)
        
        # Wenn TODO-Attribute gefunden wurden, aktualisiere Kommentar
        if todo_attrs:
            current_comment = str(gdf.loc[idx, 'Kommentar'])
            
            # Prüfe ob bereits Attribut-Kommentare vorhanden sind
            has_attr_comments = "Attribut fehlt aufgrund von Baustelle" in current_comment
            
            if not has_attr_comments:
                # Füge Attribut-Kommentare hinzu
                attr_comments = []
                for attr in todo_attrs:
                    attr_display = attr.capitalize()
                    attr_comments.append(f"{attr_display} Attribut fehlt aufgrund von Baustelle")
                
                # Füge die neuen Kommentare hinzu
                updated_comment = current_comment + "; " + "; ".join(attr_comments)
                gdf.loc[idx, 'Kommentar'] = updated_comment
                update_count += 1
    
    if update_count > 0:
        logging.info(f"Aktualisiert: {update_count} Baustellen-Kommentare mit fehlenden TODO-Attributen")
    
    return update_count
