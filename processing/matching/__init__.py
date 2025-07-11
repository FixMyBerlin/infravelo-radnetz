"""
Matching-Algorithmen für OSM-Daten.

Dieses Modul enthält Algorithmen zum Matching von OSM-Daten mit Referenzdaten:
- difference: Differenzbildung zwischen Straßen und Radwegen
- manual_interventions: Manuelle Eingriffe in den Matching-Prozess
- orthogonal_filter: Orthogonalitätsfilter für kurze Segmente
"""

# Lazy imports to avoid dependency issues
__all__ = [
    'get_or_create_difference_fgb',
    'difference_streets_without_bikelanes',
    'get_excluded_ways',
    'get_included_ways',
    'process_and_filter_short_segments'
]

def __getattr__(name):
    if name in ('get_or_create_difference_fgb', 'difference_streets_without_bikelanes'):
        from .difference import get_or_create_difference_fgb, difference_streets_without_bikelanes
        if name == 'get_or_create_difference_fgb':
            return get_or_create_difference_fgb
        elif name == 'difference_streets_without_bikelanes':
            return difference_streets_without_bikelanes
    elif name in ('get_excluded_ways', 'get_included_ways'):
        from .manual_interventions import get_excluded_ways, get_included_ways
        if name == 'get_excluded_ways':
            return get_excluded_ways
        elif name == 'get_included_ways':
            return get_included_ways
    elif name == 'process_and_filter_short_segments':
        from .orthogonal_filter import process_and_filter_short_segments
        return process_and_filter_short_segments
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
