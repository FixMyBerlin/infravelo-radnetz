import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const MAPILLARY_PRESENT = '#32CD32' // green - some mapillary reference exists
export const MAPILLARY_BOTH_PRESENT = '#006400' // dark green - general and traffic sign references exist
export const MAPILLARY_MISSING = '#FF8C00' // dark orange - no mapillary reference at all

export const getMapillaryOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getMapillaryStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // Dark green when (mapillary or mapillary_forward or mapillary_backward) AND mapillary_traffic_sign is present
  [
    'all',
    ['any', ['has', 'mapillary'], ['has', 'mapillary_forward'], ['has', 'mapillary_backward']],
    ['has', 'mapillary_traffic_sign'],
  ],
  MAPILLARY_BOTH_PRESENT,
  // Green when any mapillary OR mapillary_traffic_sign is present
  [
    'any',
    ['has', 'mapillary'],
    ['has', 'mapillary_forward'],
    ['has', 'mapillary_backward'],
    ['has', 'mapillary_traffic_sign'],
  ],
  MAPILLARY_PRESENT,
  // Red when nothing mapillary is present
  MAPILLARY_MISSING,
]

export const getMapillaryLegend = (): LayerLegend => ({
  items: [
    {
      color: MAPILLARY_MISSING,
      label: 'Keine Mapillary Referenz',
      filterExpression: [
        'all',
        ['!', ['has', 'mapillary']],
        ['!', ['has', 'mapillary_forward']],
        ['!', ['has', 'mapillary_backward']],
        ['!', ['has', 'mapillary_traffic_sign']],
      ],
    },
    {
      color: MAPILLARY_PRESENT,
      label: 'Mapillary vorhanden (Weg oder Verkehrszeichen)',
      filterExpression: [
        'all',
        // At least one mapillary reference exists
        [
          'any',
          ['has', 'mapillary'],
          ['has', 'mapillary_forward'],
          ['has', 'mapillary_backward'],
          ['has', 'mapillary_traffic_sign'],
        ],
        // But NOT both types present
        [
          '!',
          [
            'all',
            ['any', ['has', 'mapillary'], ['has', 'mapillary_forward'], ['has', 'mapillary_backward']],
            ['has', 'mapillary_traffic_sign'],
          ],
        ],
      ],
    },
    {
      color: MAPILLARY_BOTH_PRESENT,
      label: 'Mapillary für Weg und Verkehrszeichen vorhanden',
      filterExpression: [
        'all',
        ['any', ['has', 'mapillary'], ['has', 'mapillary_forward'], ['has', 'mapillary_backward']],
        ['has', 'mapillary_traffic_sign'],
      ],
    },
  ],
})
