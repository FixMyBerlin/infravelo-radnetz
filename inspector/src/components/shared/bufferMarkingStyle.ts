import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const GREEN_COLOR = '#00FF00' // green - correct cases
export const RED_COLOR = '#FF0000' // red - error cases
export const DARK_RED_COLOR = '#8B0000' // dark red - values to check
export const PINK_COLOR = '#FF69B4' // pink - other cases
export const GRAY_COLOR = '#808080' // gray - default

export const getBufferMarkingOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getBufferMarkingStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',

  // Green cases for cyclewayOnHighway_advisory with traffic_mode_right=parking + buffer_right=number
  [
    'all',
    ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
    ['==', ['get', 'traffic_mode_right'], 'parking'],
    ['has', 'buffer_right'],
  ],
  GREEN_COLOR,
  [
    'all',
    ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
    ['==', ['get', 'buffer_left'], 0],
    ['==', ['get', 'buffer_right'], 0],
  ],
  GREEN_COLOR,

  // Green cases for bicycleRoad categories with both markings
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['has', 'marking_left'],
    ['has', 'marking_right'],
  ],
  GREEN_COLOR,

  // Green cases for bicycleRoad categories with both buffers
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['has', 'buffer_left'],
    ['has', 'buffer_right'],
  ],
  GREEN_COLOR,

  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['!', ['has', 'marking_left']],
    ['!', ['has', 'marking_right']],
  ],
  RED_COLOR,

  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['has', 'marking_left'],
    ['has', 'marking_right'],
    ['!', ['has', 'buffer_left']],
    ['!', ['has', 'buffer_right']],
  ],
  RED_COLOR,
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['==', ['get', 'traffic_mode_left'], 'parking'],
    ['!', ['has', 'buffer_left']],
  ],
  RED_COLOR,
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['==', ['get', 'traffic_mode_right'], 'parking'],
    ['!', ['has', 'buffer_right']],
  ],
  RED_COLOR,

  // Dark red cases: cyclewayOnHighway_advisory with any left-side values (to check - probably wrong)
  [
    'all',
    ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
    [
      'any',
      ['all', ['has', 'buffer_left'], ['!=', ['get', 'buffer_left'], 0]],
      ['==', ['get', 'traffic_mode_left'], 'parking'],
    ],
  ],
  DARK_RED_COLOR,

  // Red cases: cyclewayOnHighway_advisory with marking_right and missing buffer_right
  [
    'all',
    ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
    ['has', 'marking_right'],
    ['!', ['has', 'buffer_right']],
  ],
  RED_COLOR,

  // Red cases: cyclewayOnHighway_advisory with traffic_mode_right=parking and no buffer_right
  [
    'all',
    ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
    ['==', ['get', 'traffic_mode_right'], 'parking'],
    ['!', ['has', 'buffer_right']],
  ],
  RED_COLOR,

  // Red cases: bicycleRoad with traffic_mode_left=parking and no buffer_left
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['==', ['get', 'traffic_mode_left'], 'parking'],
    ['!', ['has', 'buffer_left']],
  ],
  RED_COLOR,

  // Red cases: bicycleRoad with traffic_mode_right=parking and no buffer_right
  [
    'all',
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
    ['==', ['get', 'traffic_mode_right'], 'parking'],
    ['!', ['has', 'buffer_right']],
  ],
  RED_COLOR,

  // Pink cases: cyclewayOnHighway_advisory that doesn't match green or red cases
  ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
  PINK_COLOR,

  // Pink cases: bicycleRoad categories that don't match green or red cases
  [
    'any',
    ['==', ['get', 'category'], 'bicycleRoad'],
    ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
  ],
  PINK_COLOR,

  // Default: everything else is gray
  GRAY_COLOR,
]

export const getBufferMarkingLegend = (): LayerLegend => ({
  items: [
    {
      color: GREEN_COLOR,
      label: 'Korrekt konfiguriert',
      filterExpression: [
        'any',
        // Green cases for cyclewayOnHighway_advisory
        [
          'all',
          ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
          ['==', ['get', 'traffic_mode_right'], 'parking'],
          ['has', 'buffer_right'],
        ],
        [
          'all',
          ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
          ['==', ['get', 'buffer_left'], 0],
          ['==', ['get', 'buffer_right'], 0],
        ],
        // Green cases for bicycleRoad categories
        [
          'all',
          [
            'any',
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
          ['has', 'marking_left'],
          ['has', 'marking_right'],
        ],
        [
          'all',
          [
            'any',
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
          ['has', 'buffer_left'],
          ['has', 'buffer_right'],
        ],
      ],
    },
    {
      color: RED_COLOR,
      label: 'Fehler - Buffer oder Marking fehlt',
      filterExpression: [
        'any',
        // Red cases for bicycleRoad
        [
          'all',
          [
            'any',
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
          ['!', ['has', 'marking_left']],
          ['!', ['has', 'marking_right']],
        ],
        [
          'all',
          [
            'any',
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
          ['has', 'marking_left'],
          ['has', 'marking_right'],
          ['!', ['has', 'buffer_left']],
          ['!', ['has', 'buffer_right']],
        ],
        [
          'all',
          [
            'any',
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
          ['==', ['get', 'traffic_mode_left'], 'parking'],
          ['!', ['has', 'buffer_left']],
        ],
        [
          'all',
          [
            'any',
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
          ['==', ['get', 'traffic_mode_right'], 'parking'],
          ['!', ['has', 'buffer_right']],
        ],
        // Red cases for cyclewayOnHighway_advisory
        [
          'all',
          ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
          ['has', 'marking_right'],
          ['!', ['has', 'buffer_right']],
        ],
        [
          'all',
          ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
          ['==', ['get', 'traffic_mode_right'], 'parking'],
          ['!', ['has', 'buffer_right']],
        ],
      ],
    },
    {
      color: DARK_RED_COLOR,
      label: 'Zu prüfen: Werte "left" vermutlich falsch',
      filterExpression: [
        'all',
        ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
        [
          'any',
          ['all', ['has', 'buffer_left'], ['!=', ['get', 'buffer_left'], 0]],
          ['==', ['get', 'traffic_mode_left'], 'parking'],
        ],
      ],
    },
    {
      color: PINK_COLOR,
      label: 'Unklar – Buffer fehlt vielleicht',
      filterExpression: [
        'any',
        ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
        ['==', ['get', 'category'], 'bicycleRoad'],
        ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
      ],
    },
    {
      color: GRAY_COLOR,
      label: 'Buffer wahrscheinlich nicht relevant',
      // Everything else - no specific filter needed, this is the default
    },
  ],
})
