import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const IMPRECISE_CATEGORY_COLOR = '#FF0000' // red - category is imprecise
export const DEFAULT_COLOR = '#808080' // gray - no issues

export const getCategoryOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getCategoryStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  [
    'any',
    ['has', '_advisoryOrExclusive', ['get', 'category']],
    ['has', '_adjoiningOrIsolated', ['get', 'category']],
  ],
  IMPRECISE_CATEGORY_COLOR,
  DEFAULT_COLOR,
]

export const getCategoryLegend = (): LayerLegend => ({
  items: [
    {
      color: IMPRECISE_CATEGORY_COLOR,
      label: '[TODO] TILDA "bauliche Führung" unpräzise (siehe TILDA-Hinweis)',
    },
    {
      color: DEFAULT_COLOR,
      label: 'Alle anderen Kategorien',
    },
  ],
})
