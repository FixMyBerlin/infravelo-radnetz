import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const BUFFER_RIGHT_MISSING = '#800080' // purple - buffer_right missing
export const BUFFER_OR_MARKING_MISSING = '#FFC0CB' // pink - buffer or marking missing
export const MARKING_MISSING = '#8B0000' // dark red - marking missing
export const BUFFER_MISSING_WITH_MARKING = '#4B0000' // darker red - buffer missing when marking present
export const NO_ATTRIBUTES_EXPECTED = '#404040' // dark gray - no attributes expected or given
export const UNEXPECTED_ATTRIBUTES = '#000000' // black - unexpected attributes found
export const DEFAULT_COLOR = '#808080' // gray - default

export const getBufferMarkingOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getBufferMarkingStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // Case 1: cyclewayOnHighway needs buffer_right
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'cyclewayOnHighway_exclusive'],
      ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
    ],
    ['!', ['has', 'buffer_right']],
  ],
  BUFFER_RIGHT_MISSING,

  // Case 2: protectedCyclewayOnHighway needs buffer and marking
  [
    'all',
    ['==', ['get', 'category'], 'protectedCyclewayOnHighway'],
    [
      'any',
      // Missing any buffer
      [
        'all',
        ['!', ['has', 'buffer_right']],
        ['!', ['has', 'buffer_left']],
        ['!', ['has', 'buffer_both']],
      ],
      // Missing any marking
      [
        'all',
        ['!', ['has', 'marking_right']],
        ['!', ['has', 'marking_left']],
        ['!', ['has', 'marking_both']],
      ],
    ],
  ],
  BUFFER_OR_MARKING_MISSING,

  // Case 3: bicycleRoad needs marking
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    [
      'all',
      ['!', ['has', 'marking_right']],
      ['!', ['has', 'marking_left']],
      ['!', ['has', 'marking_both']],
    ],
  ],
  MARKING_MISSING,

  // Case 4: bicycleRoad with marking needs buffer
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    [
      'any',
      ['has', 'marking_right'],
      ['has', 'marking_left'],
      ['has', 'marking_both'],
    ],
    ['!=', ['get', 'marking'], 'no'],
    [
      'all',
      ['!', ['has', 'buffer_right']],
      ['!', ['has', 'buffer_left']],
      ['!', ['has', 'buffer_both']],
    ],
  ],
  BUFFER_MISSING_WITH_MARKING,

  // Case 5: All other categories - no attributes expected
  [
    'all',
    ['!', ['has', 'marking_right']],
    ['!', ['has', 'marking_left']],
    ['!', ['has', 'marking_both']],
    ['!', ['has', 'buffer_right']],
    ['!', ['has', 'buffer_left']],
    ['!', ['has', 'buffer_both']],
    ['!', ['has', 'separation_right']],
    ['!', ['has', 'separation_left']],
    ['!', ['has', 'separation_both']],
  ],
  NO_ATTRIBUTES_EXPECTED,

  // Case 6: Other categories with unexpected attributes
  [
    'any',
    ['has', 'marking_right'],
    ['has', 'marking_left'],
    ['has', 'marking_both'],
    ['has', 'buffer_right'],
    ['has', 'buffer_left'],
    ['has', 'buffer_both'],
    ['has', 'separation_right'],
    ['has', 'separation_left'],
    ['has', 'separation_both'],
  ],
  UNEXPECTED_ATTRIBUTES,

  // Default case
  DEFAULT_COLOR,
]

export const getBufferMarkingLegend = (): LayerLegend => ({
  items: [
    { color: BUFFER_RIGHT_MISSING, label: '"buffer_right" nötig' },
    { color: BUFFER_OR_MARKING_MISSING, label: '"buffer_SIDE", "marking_SIDE" nötig' },
    { color: MARKING_MISSING, label: '"marking_SIDE" nötig, ggf. dann buffer' },
    { color: BUFFER_MISSING_WITH_MARKING, label: '"buffer_SIDE" nötig' },
    { color: NO_ATTRIBUTES_EXPECTED, label: 'Keine Angaben erwartet und keine gegeben' },
    { color: UNEXPECTED_ATTRIBUTES, label: 'Keine Angaben erwartet aber Angabe gefunden' },
  ],
})
