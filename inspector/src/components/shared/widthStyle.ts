import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const WIDTH_COMPLETE = '#32CD32' // green - width and source present
export const WIDTH_MISSING = '#FF0000' // red - width missing
export const WIDTH_MISSING_LOW_PRIORITY = '#1E90FF' // blue - width missing but not priority
export const WIDTH_SOURCE_MISSING = '#914ec7ff' // dark red - width present but source missing

export const getWidthOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getWidthStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // First check if width and source are both present
  ['all', ['has', 'width'], ['has', 'width_source']],
  WIDTH_COMPLETE,
  // Then check if width is present but source is missing
  ['all', ['has', 'width'], ['!', ['has', 'width_source']]],
  WIDTH_SOURCE_MISSING,
  // Then check if width is missing AND it's a low priority category
  [
    'all',
    ['!', ['has', 'width']],
    [
      'any',
      ['==', ['get', 'category'], 'sharedBusLaneBusWithBike'],
      ['==', ['get', 'category'], 'sharedBusLaneBikeWithBus'],
      ['==', ['get', 'category'], 'bicycleRoad'],
      ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ],
  ],
  WIDTH_MISSING_LOW_PRIORITY,
  // Otherwise width is missing
  WIDTH_MISSING,
]

export const getWidthLegend = (): LayerLegend => ({
  items: [
    {
      color: WIDTH_COMPLETE,
      label: 'Breite und Quelle vorhanden',
      filterExpression: ['all', ['has', 'width'], ['has', 'width_source']],
    },
    {
      color: WIDTH_SOURCE_MISSING,
      label: '[TODO] Quellenangabe der Breite fehlt',
      filterExpression: ['all', ['has', 'width'], ['!', ['has', 'width_source']]],
    },
    {
      color: WIDTH_MISSING,
      label: '[TODO] Breitenangeabe fehlt',
      filterExpression: [
        'all',
        ['!', ['has', 'width']],
        [
          '!',
          [
            'any',
            ['==', ['get', 'category'], 'sharedBusLaneBusWithBike'],
            ['==', ['get', 'category'], 'sharedBusLaneBikeWithBus'],
            ['==', ['get', 'category'], 'bicycleRoad'],
            ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
          ],
        ],
      ],
    },
    {
      color: WIDTH_MISSING_LOW_PRIORITY,
      label: 'Breiten Nacherhebung',
      filterExpression: [
        'any',
        ['==', ['get', 'category'], 'sharedBusLaneBusWithBike'],
        ['==', ['get', 'category'], 'sharedBusLaneBikeWithBus'],
        ['==', ['get', 'category'], 'bicycleRoad'],
        ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
      ],
    },
  ],
})
