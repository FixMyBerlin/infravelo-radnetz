import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'

const CUTOFF_DATE = '2025-07-01'
const FRESH_COLOR = '#32CD32' // green
const OLD_COLOR = '#8B4513' // rust-brown

export const getAgeColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['>', ['get', 'updated_at'], CUTOFF_DATE],
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
