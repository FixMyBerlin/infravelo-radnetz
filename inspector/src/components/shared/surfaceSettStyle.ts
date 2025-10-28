import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const SETT_COLOR = '#FF0000' // red - for generic sett
export const SPECIFIC_SETT_COLOR = '#0000FF' // blue - for specific sett types
export const NO_SURFACE_COLOR = '#FF8C00' // orange - for missing surface
export const OTHER_COLOR = '#808080' // gray - for other surfaces

// Default opacity
export const getSurfaceSettOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getSurfaceSettColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['!', ['has', 'surface']],
  NO_SURFACE_COLOR,
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
    {
      color: SETT_COLOR,
      label: '[TODO] Pflaster (allgemein)',
      filterExpression: [
        'all',
        ['has', 'surface'],
        ['==', ['get', 'surface'], 'sett'],
      ],
    },
    {
      color: SPECIFIC_SETT_COLOR,
      label: 'Spezifisches Pflaster (Mosaik, klein, groß)',
      filterExpression: [
        'in',
        ['get', 'surface'],
        ['literal', ['mosaic_sett', 'small_sett', 'large_sett']],
      ],
    },
    {
      color: NO_SURFACE_COLOR,
      label: 'Keine Oberfläche',
      filterExpression: ['!', ['has', 'surface']],
    },
    {
      color: OTHER_COLOR,
      label: 'Andere Oberfläche',
      filterExpression: [
        'all',
        ['has', 'surface'],
        ['!=', ['get', 'surface'], 'sett'],
        [
          '!',
          [
            'in',
            ['get', 'surface'],
            ['literal', ['mosaic_sett', 'small_sett', 'large_sett']],
          ],
        ],
      ],
    },
  ],
})
