import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const SURFACE_COLOR_PRESENT = '#32CD32' // green - surface color is present
export const SURFACE_COLOR_MISSING = '#FF0000' // red - surface color is missing where expected
export const SURFACE_COLOR_NA = '#808080' // gray - surface color not expected

export const getSurfaceColorOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getSurfaceColorStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // If it's a bicycle street or pedestrian street, show as gray (no color expected)
  [
    'any',
    ['==', ['get', 'category'], 'bicycleRoad_vehicleDestination'],
    ['==', ['get', 'category'], 'sharedBusLaneBusWithBike'],
    ['==', ['get', 'category'], 'pedestrianAreaBicycleYes'],
    ['==', ['get', 'category'], 'footAndCyclewayShared_adjoining'],
    ['==', ['get', 'category'], 'footAndCyclewayShared_isolated'],
    ['==', ['get', 'category'], 'footAndCyclewayShared_adjoiningOrIsolated'],
  ],
  SURFACE_COLOR_NA,
  // For all other categories, check if surface color is present
  ['has', 'surface_color'],
  SURFACE_COLOR_PRESENT,
  // If surface color is missing, show as red (needs to be added)
  SURFACE_COLOR_MISSING,
]

export const getSurfaceColorLegend = (): LayerLegend => ({
  items: [
    { color: SURFACE_COLOR_PRESENT, label: 'Surface color present' },
    { color: SURFACE_COLOR_MISSING, label: '[TODO] Surface color missing' },
    { color: SURFACE_COLOR_NA, label: 'No surface color expected' },
  ],
})
