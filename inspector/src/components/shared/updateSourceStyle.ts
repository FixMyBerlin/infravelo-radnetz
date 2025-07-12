import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import { DAYS_SINCE_CUTOFF } from './ageBasedStyle'
import type { LayerLegend } from './types'

// Color constants
export const FMC_UPDATED = '#32CD32' // green - FMC account updated
export const OTHER_RECENT_UPDATE = '#800080' // purple - other account, recent update
export const OTHER_OLD_UPDATE = '#FF0000' // red - other account, old update
export const DEFAULT_COLOR = '#808080' // gray - fallback

export const getUpdateSourceOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getUpdateSourceStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // First check if updated by FMC account
  ['in', 'fmc_', ['get', 'updated_by']],
  FMC_UPDATED,
  // Then check if recently updated by another account (using updated_age in days)
  ['<=', ['get', 'updated_age'], DAYS_SINCE_CUTOFF],
  OTHER_RECENT_UPDATE,
  // Otherwise it's an old update by another account
  OTHER_OLD_UPDATE,
]

export const getUpdateSourceLegend = (): LayerLegend => ({
  items: [
    { color: FMC_UPDATED, label: 'Zuletzt vom FMC Account bearbeitet' },
    { color: OTHER_RECENT_UPDATE, label: 'Von einem anderen Account nach Projektstart bearbeitet' },
    {
      color: OTHER_OLD_UPDATE,
      label: 'Von einem anderen Account bearbeitet und seit Projektstart noch nicht',
    },
  ],
})
