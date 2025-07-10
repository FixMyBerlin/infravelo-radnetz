import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const WIDTH_COMPLETE = '#32CD32' // green - width and source present
export const WIDTH_MISSING = '#FF0000' // red - width missing
export const WIDTH_MISSING_LOW_PRIORITY = '#FFE4E1' // very light red - width missing but not priority
export const WIDTH_SOURCE_MISSING = '#8B0000' // dark red - width present but source missing

export const getWidthOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getWidthStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // First check if it's a category where width is not a priority
  [
    'any',
    ['==', ['get', 'category'], 'sharedBusLaneBusWithBike'],
    ['==', ['get', 'category'], 'sharedBusLaneBikeWithBus'],
    ['==', ['get', 'category'], 'bicycleRoad'],
    ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
  ],
  WIDTH_MISSING_LOW_PRIORITY,
  // Then check if width is completely missing
  ['!', ['has', 'width']],
  WIDTH_MISSING,
  // Then check if width source is missing
  ['!', ['has', 'width_source']],
  WIDTH_SOURCE_MISSING,
  // Otherwise width and source are present
  WIDTH_COMPLETE,
]

export const getWidthLegend = (): LayerLegend => ({
  items: [
    { color: WIDTH_COMPLETE, label: 'Breite und Quelle vorhanden' },
    { color: WIDTH_SOURCE_MISSING, label: '[TODO] Quellenangabe der Breite fehlt' },
    { color: WIDTH_MISSING, label: '[TODO] Breitenangeabe fehlt' },
    { color: WIDTH_MISSING_LOW_PRIORITY, label: 'Breitenangabe fehlt aber auch keine Priorität' },
  ],
})
