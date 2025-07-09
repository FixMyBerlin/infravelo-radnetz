import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'

// Color constants
export const ONEWAY_YES_COLOR = '#0000FF' // blue
export const ONEWAY_NO_COLOR = '#32CD32' // green
export const ONEWAY_MISSING_COLOR = '#FF0000' // red
export const ONEWAY_NEUTRAL_COLOR = '#808080' // gray

// Default opacity for all oneway layers
export const DEFAULT_OPACITY = 0.8

// Style for bikelanes and paths
export const getBikeLaneOnewayColor: DataDrivenPropertyValueSpecification<string> = [
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
]

// Style for roads with bicycle specific oneway rules
export const getRoadOnewayColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes'], ['has', 'oneway_bicycle']],
  ONEWAY_YES_COLOR,
  ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes']],
  ONEWAY_MISSING_COLOR,
  ONEWAY_NEUTRAL_COLOR,
]
