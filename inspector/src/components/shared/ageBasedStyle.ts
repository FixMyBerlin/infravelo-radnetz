import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Project cutoff date
export const CUTOFF_DATE = '2025-07-01'

// Calculate cutoff timestamp in seconds since epoch
const cutoffDate = new Date(CUTOFF_DATE)
export const CUTOFF_TIMESTAMP = Math.floor(cutoffDate.getTime() / 1000)

const FRESH_COLOR = '#32CD32' // green
const OLD_COLOR = '#8B4513' // rust-brown

export const getAgeColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['>=', ['get', 'updated_at'], CUTOFF_TIMESTAMP],
  FRESH_COLOR,
  OLD_COLOR,
]

export const getAgeOpacity: DataDrivenPropertyValueSpecification<number> = [
  'case',
  ['boolean', ['feature-state', 'selected'], false],
  1,
  ['boolean', ['feature-state', 'hover'], false],
  1,
  0.8,
]

export const getAgeLegend = (): LayerLegend => ({
  items: [
    { color: FRESH_COLOR, label: `Nach ${CUTOFF_DATE.split('-').join('.')} aktualisiert` },
    { color: OLD_COLOR, label: `Vor ${CUTOFF_DATE.split('-').join('.')} aktualisiert` },
  ],
})
