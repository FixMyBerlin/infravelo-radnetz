import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const CLARIFICATION_NEEDED_COLOR = '#FF0000' // bright red - category needs clarification
export const IMPRECISE_CATEGORY_COLOR = '#FF69B4' // bright pink - category is imprecise
export const DEFAULT_COLOR = '#808080' // gray - no issues

export const getCategoryOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getCategoryStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // Bright red: Führung gar nicht erkannt
  ['==', ['get', 'category'], 'needsClarification'],
  CLARIFICATION_NEEDED_COLOR,
  // Dark red: Führung ungenau (existing imprecision rules)
  [
    'any',
    ['in', '_advisoryOrExclusive', ['get', 'category']],
    ['in', '_adjoiningOrIsolated', ['get', 'category']],
  ],
  IMPRECISE_CATEGORY_COLOR,
  // Default for the rest
  DEFAULT_COLOR,
]

export const getCategoryLegend = (): LayerLegend => ({
  items: [
    { color: CLARIFICATION_NEEDED_COLOR, label: 'Führung gar nicht erkannt' },
    { color: IMPRECISE_CATEGORY_COLOR, label: 'Führung ungenau' },
    { color: DEFAULT_COLOR, label: 'Alle anderen Kategorien' },
  ],
})
