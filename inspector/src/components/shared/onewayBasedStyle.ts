import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'

// Color constants
const ONEWAY_YES_COLOR = '#0000FF' // blue
const ONEWAY_NO_COLOR = '#32CD32' // green
const ONEWAY_MISSING_COLOR = '#FF0000' // red
const ONEWAY_NEUTRAL_COLOR = '#808080' // gray

// Style for bikelanes and paths
export const getBikeLaneOnewayColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['boolean', ['feature-state', 'hover'], false],
  'black',
  ['boolean', ['feature-state', 'selected'], false],
  'red',
  [
    'case',
    // Allow implicit_yes for advisory or exclusive cycleways
    [
      'all',
      ['has', 'oneway'],
      ['==', ['get', 'oneway'], 'implicit_yes'],
      [
        'any',
        ['==', ['get', 'category'], 'cyclewayOnHighway_advisory'],
        ['==', ['get', 'category'], 'cyclewayOnHighway_exclusive'],
        ['==', ['get', 'category'], 'cyclewayOnHighwayProtected'],
      ],
    ],
    ONEWAY_YES_COLOR,
    // Normal oneway handling
    ['has', 'oneway'],
    [
      'match',
      ['get', 'oneway'],
      'yes',
      ONEWAY_YES_COLOR,
      'no',
      ONEWAY_NO_COLOR,
      ONEWAY_MISSING_COLOR,
    ],
    ONEWAY_MISSING_COLOR,
  ],
]

// Style for roads with bicycle specific oneway rules
export const getRoadOnewayColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['boolean', ['feature-state', 'hover'], false],
  'black',
  ['boolean', ['feature-state', 'selected'], false],
  'red',
  [
    'case',
    ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes'], ['has', 'oneway_bicycle']],
    ONEWAY_YES_COLOR,
    ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes']],
    ONEWAY_MISSING_COLOR,
    ONEWAY_NEUTRAL_COLOR,
  ],
]

export const getOnewayOpacity: DataDrivenPropertyValueSpecification<number> = [
  'case',
  ['boolean', ['feature-state', 'selected'], false],
  1,
  ['boolean', ['feature-state', 'hover'], false],
  1,
  0.8,
]
