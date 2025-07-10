import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const SETT_COLOR = '#FF0000' // red - for generic sett
export const SPECIFIC_SETT_COLOR = '#0000FF' // blue - for specific sett types
export const OTHER_COLOR = '#808080' // gray - for other surfaces

// Default opacity
export const getSurfaceSettOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getSurfaceSettColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['!', ['has', 'surface']],
  OTHER_COLOR,
  [
    'match',
    ['get', 'surface'],
    'sett',
    SETT_COLOR,
    ['mosaic_sett', 'small_sett', 'large_sett'],
    SPECIFIC_SETT_COLOR,
    OTHER_COLOR,
  ],
]

export const getSurfaceSettLegend = (): LayerLegend => ({
  items: [
    { color: SETT_COLOR, label: '[TODO] Pflaster (allgemein)' },
    { color: SPECIFIC_SETT_COLOR, label: 'Spezifisches Pflaster (Mosaik, klein, groß)' },
    { color: OTHER_COLOR, label: 'Andere oder keine Oberfläche' },
  ],
})
