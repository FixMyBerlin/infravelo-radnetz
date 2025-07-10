import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const MAPILLARY_PRESENT = '#32CD32' // green - mapillary reference exists
export const MAPILLARY_MISSING_SIGN = '#FF0000' // red - traffic sign exists but no mapillary reference
export const MAPILLARY_MISSING_ANY = '#8B0000' // dark red - no mapillary reference at all

export const getMapillaryOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getMapillaryStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // First check if there's a traffic sign that needs a mapillary reference
  [
    'all',
    ['has', 'traffic_sign'],
    ['!=', ['get', 'traffic_sign'], 'none'],
    ['!', ['has', 'mapillary_traffic_sign']],
  ],
  MAPILLARY_MISSING_SIGN,
  // Then check if any mapillary reference is present
  ['any', ['has', 'mapillary'], ['has', 'mapillary_left'], ['has', 'mapillary_right']],
  MAPILLARY_PRESENT,
  // Otherwise mark as missing all references
  MAPILLARY_MISSING_ANY,
]

export const getMapillaryLegend = (): LayerLegend => ({
  items: [
    { color: MAPILLARY_MISSING_SIGN, label: '[TODO] Kein Mapillary fürs Verkehrszeichen' },
    { color: MAPILLARY_MISSING_ANY, label: '[TODO] Keine Mapillary Referenz' },
    { color: MAPILLARY_PRESENT, label: 'Mapillary Referenz vorhanden' },
  ],
})
