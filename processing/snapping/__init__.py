"""
Snapping-Algorithmen für OSM-Daten.

Dieses Modul enthält Algorithmen zum Snapping von OSM-Daten auf Referenznetzwerke:
- snap_and_cut: Snapping von OSM-Wegen auf Zielnetzwerke
- enrich_streetnet_with_osm: Anreicherung von Straßennetzen mit OSM-Attributen
"""

# Lazy imports to avoid dependency issues
__all__ = [
    'snap_and_cut',
    'get_projected_substring',
    'calculate_snapping_percentage',
    'enrich_network_with_osm',
    'process_network_edges'
]

def __getattr__(name):
    if name in ('snap_and_cut', 'get_projected_substring', 'calculate_snapping_percentage'):
        from .snap_and_cut import snap_and_cut, get_projected_substring, calculate_snapping_percentage
        if name == 'snap_and_cut':
            return snap_and_cut
        elif name == 'get_projected_substring':
            return get_projected_substring
        elif name == 'calculate_snapping_percentage':
            return calculate_snapping_percentage
    elif name in ('enrich_network_with_osm', 'process_network_edges'):
        from .enrich_streetnet_with_osm import enrich_network_with_osm, process_network_edges
        if name == 'enrich_network_with_osm':
            return enrich_network_with_osm
        elif name == 'process_network_edges':
            return process_network_edges
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
