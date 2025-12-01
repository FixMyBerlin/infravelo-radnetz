#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
construction_comments.py
------------------------
Hilfsfunktionen für die Generierung und Aktualisierung von Baustellen- und 
temporäre Infrastruktur-Kommentaren.

Diese Funktionen werden sowohl in der TILDA-Übersetzung als auch im Snapping verwendet,
um konsistente Kommentare für Baustellen und temporäre Infrastruktur zu generieren.
"""

import logging

# Standard RVN-Attribute für TODO-Prüfung
DEFAULT_ATTRIBUTE_NAMES = ["pflicht", "breite", "ofm", "farbe", "protek", 
                           "trennstreifen", "nutz_beschr", "fuehr", "verkehrsri"]


def collect_todo_attributes(row, attribute_names: list, include_missing: bool = False) -> list:
    """
    Sammelt alle Attribute die einen fehlenden oder unvollständigen Wert haben.
    
    Erkannt werden:
    - Werte mit "[TODO]" im Text
    - Werte mit "fehlt" im Text (z.B. "Breite fehlt", "[TODO] Fehlt")
    - Bei include_missing=True zusätzlich: None, NaN, leere Strings
    
    Args:
        row: Datenzeile mit RVN-Attributen (pandas Series oder dict-like)
        attribute_names: Liste der zu prüfenden Attributnamen
        include_missing: Wenn True, werden auch fehlende/leere Werte (None, NaN, "") 
                        als fehlende Attribute gesammelt (z.B. für Baustellen)
    
    Returns:
        Liste von Attributnamen, die als fehlend erkannt wurden
    """
    todo_attrs = []
    
    for attr in attribute_names:
        # Prüfe ob das Attribut existiert (sowohl für Series.index als auch dict-like)
        if hasattr(row, 'index') and attr in row.index:
            raw_value = row.get(attr, None)
        elif attr in row:
            raw_value = row.get(attr, None)
        else:
            continue
        
        # Prüfe auf fehlende Werte (None, NaN, leere Strings)
        if include_missing:
            import pandas as pd
            if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
                todo_attrs.append(attr)
                continue
            value_str = str(raw_value).strip()
            if value_str in ["", "nan", "None", "none"]:
                todo_attrs.append(attr)
                continue
        
        # Prüfe auf [TODO] oder "fehlt" im Wert
        value_str = str(raw_value).strip().lower() if raw_value is not None else ""
        if value_str and ("[todo]" in value_str or "fehlt" in value_str):
            todo_attrs.append(attr)
    
    return todo_attrs


def _update_comments_for_pattern(gdf, search_pattern: str, reason_text: str, 
                                  log_label: str, attribute_names: list = None) -> int:
    """
    Generische Hilfsfunktion zum Aktualisieren von Kommentaren für Segmente,
    die ein bestimmtes Muster im Kommentar enthalten.
    
    Args:
        gdf: GeoDataFrame mit Segmenten
        search_pattern: Suchtext im Kommentar (z.B. 'Baustelle', 'Temporäre Markierungen')
        reason_text: Text für die Begründung (z.B. 'Baustelle', 'temporärer Infrastruktur')
        log_label: Label für Log-Meldungen (z.B. 'Baustellen', 'temporäre Infrastruktur')
        attribute_names: Liste der zu prüfenden Attributnamen
    
    Returns:
        Anzahl der aktualisierten Kommentare
    """
    if attribute_names is None:
        attribute_names = DEFAULT_ATTRIBUTE_NAMES
    
    # Prüfe ob Kommentar-Spalte existiert
    if 'Kommentar' not in gdf.columns:
        logging.warning("Spalte 'Kommentar' nicht gefunden - überspringe Aktualisierung")
        return 0
    
    # Finde alle Segmente mit passendem Kommentar
    has_pattern = gdf['Kommentar'].notna() & gdf['Kommentar'].astype(str).str.contains(search_pattern, case=False, na=False)
    
    if has_pattern.sum() == 0:
        return 0
    
    update_count = 0
    check_text = f"Attribut fehlt aufgrund von {reason_text}"
    
    for idx in gdf[has_pattern].index:
        # Sammle alle TODO-Attribute für dieses Segment
        # include_missing=True, da bei Baustellen/temporärer Infrastruktur auch fehlende Werte
        # (z.B. breite=None) als fehlende Attribute gelten
        row = gdf.loc[idx]
        todo_attrs = collect_todo_attributes(row, attribute_names, include_missing=True)
        
        # Wenn TODO-Attribute gefunden wurden, aktualisiere Kommentar
        if todo_attrs:
            current_comment = str(gdf.loc[idx, 'Kommentar'])
            
            # Prüfe ob bereits Attribut-Kommentare vorhanden sind
            if check_text not in current_comment:
                # Füge Attribut-Kommentare hinzu
                attr_comments = [f"{attr.capitalize()} Attribut fehlt aufgrund von {reason_text}" 
                                for attr in todo_attrs]
                
                # Füge die neuen Kommentare hinzu
                updated_comment = current_comment + "; " + "; ".join(attr_comments)
                gdf.loc[idx, 'Kommentar'] = updated_comment
                update_count += 1
    
    if update_count > 0:
        logging.info(f"Aktualisiert: {update_count} {log_label}-Kommentare mit fehlenden TODO-Attributen")
    
    return update_count


def update_construction_comments(gdf, attribute_names: list = None) -> int:
    """
    Aktualisiert Kommentare für Baustellen-Segmente um fehlende TODO-Attribute zu ergänzen.
    
    Args:
        gdf: GeoDataFrame mit Segmenten
        attribute_names: Liste der zu prüfenden Attributnamen
    
    Returns:
        Anzahl der aktualisierten Kommentare
    """
    return _update_comments_for_pattern(
        gdf, 
        search_pattern='Baustelle',
        reason_text='Baustelle',
        log_label='Baustellen',
        attribute_names=attribute_names
    )


def update_temporary_infrastructure_comments(gdf, attribute_names: list = None) -> int:
    """
    Aktualisiert Kommentare für temporäre Infrastruktur-Segmente um fehlende TODO-Attribute zu ergänzen.
    
    Args:
        gdf: GeoDataFrame mit Segmenten
        attribute_names: Liste der zu prüfenden Attributnamen
    
    Returns:
        Anzahl der aktualisierten Kommentare
    """
    return _update_comments_for_pattern(
        gdf,
        search_pattern='Temporäre Markierungen',
        reason_text='temporärer Infrastruktur',
        log_label='temporäre Infrastruktur',
        attribute_names=attribute_names
    )

