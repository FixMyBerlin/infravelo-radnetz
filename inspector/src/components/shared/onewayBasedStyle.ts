import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const BLUE = '#0000FF' // blue
export const BRIGHT_GREEN = '#32CD32' // green
export const ONEWAY_MISSING_COLOR = '#FF0000' // red
export const ONEWAY_NEUTRAL_COLOR = '#808080' // gray
export const DARK_GREEN = '#006400' // dark green

// Default opacity for all layers
export const getOnewayOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

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
      ['==', ['get', 'category'], 'footAndCyclewayShared_adjoining'],
    ],
  ],
  BLUE,
  [
    'all',
    ['has', 'oneway'],
    ['==', ['get', 'oneway'], 'assumed_no'],
    [
      'any',
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
      ['==', ['get', 'category'], 'pedestrianAreaBicycleYes'],
    ],
  ],
  BRIGHT_GREEN,
  // Normal oneway handling
  ['has', 'oneway'],
  [
    'match',
    ['get', 'oneway'],
    'yes',
    BLUE,
    'no',
    BRIGHT_GREEN,
    'car_not_bike',
    BRIGHT_GREEN,
    ONEWAY_MISSING_COLOR,
  ],
  ONEWAY_MISSING_COLOR,
]

// Style for roads with bicycle specific oneway rules
export const getRoadOnewayColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // Dual carriageway - no oneway:bicycle expected
  ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes_dual_carriageway']],
  BLUE,
  // Normal oneway with bicycle specification
  ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes'], ['has', 'oneway_bicycle']],
  DARK_GREEN,
  // Oneway without bicycle specification
  ['all', ['has', 'oneway'], ['==', ['get', 'oneway'], 'yes']],
  ONEWAY_MISSING_COLOR,
  ONEWAY_NEUTRAL_COLOR,
]

export const getBikeLaneOnewayLegend = (): LayerLegend => ({
  items: [
    { color: BLUE, label: 'Einbahnstraße (explizit oder implizit)' },
    { color: BRIGHT_GREEN, label: 'Keine Einbahnstraße (explizit oder nur für Autos)' },
    { color: ONEWAY_MISSING_COLOR, label: '[TODO] Keine oder fehlerhafte Angabe' },
  ],
})

export const getRoadOnewayLegend = (): LayerLegend => ({
  items: [
    {
      color: DARK_GREEN,
      label: 'Explizite Angabe Einbahnstraße (Auto) und oneway:bicycle',
    },
    {
      color: BLUE,
      label: 'Straße "dual_carriageway" daher kein oneway:bicycle erwartet',
    },
    {
      color: ONEWAY_MISSING_COLOR,
      label:
        '[TODO] Explizite Angabe Einbahnstraße (Auto) aber Angabe zu bicycle:oneway=yes|no oder dual_carriageway=yes fehlt',
    },
    { color: ONEWAY_NEUTRAL_COLOR, label: 'Keine Einbahnstraße' },
  ],
})
