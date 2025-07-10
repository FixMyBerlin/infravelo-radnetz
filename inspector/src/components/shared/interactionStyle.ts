import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'

export const getInteractionLineColor: DataDrivenPropertyValueSpecification<string> = [
  'case',
  ['boolean', ['feature-state', 'hover'], false],
  'black',
  ['boolean', ['feature-state', 'selected'], false],
  'red',
  'rgba(0, 0, 0, 0)', // transparent by default
]

export const getInteractionLineWidth = 7 // wider than the actual line for easier interaction
