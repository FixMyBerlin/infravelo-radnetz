import type { DataDrivenPropertyValueSpecification } from 'maplibre-gl'
import type { LayerLegend } from './types'

// Color constants
export const TRAFFIC_SIGN_NONE = '#0000FF' // blue - explicitly marked as none
export const TRAFFIC_SIGN_PRESENT = '#32CD32' // green - traffic sign is present
export const TRAFFIC_SIGN_DAMAGE = 'purple'
export const TRAFFIC_SIGN_MISSING = '#FF0000' // red - traffic sign is missing

export const getTrafficSignOpacity: DataDrivenPropertyValueSpecification<number> = 0.8

export const getTrafficSignStyle: DataDrivenPropertyValueSpecification<string> = [
  'case',
  // First check if traffic_sign is explicitly "none"
  ['all', ['has', 'traffic_sign'], ['==', ['get', 'traffic_sign'], 'none']],
  TRAFFIC_SIGN_NONE,
  // Then check for damage indicators in traffic_sign
  [
    'all',
    ['has', 'traffic_sign'],
    [
      'any',
      ['in', 'schäden', ['get', 'traffic_sign']],
      ['in', 'Schäden', ['get', 'traffic_sign']],
      ['in', 'schaeden', ['get', 'traffic_sign']],
      ['in', 'Schaeden', ['get', 'traffic_sign']],
    ],
  ],
  TRAFFIC_SIGN_DAMAGE,
  // Then check if any traffic_sign is present
  ['has', 'traffic_sign'],
  TRAFFIC_SIGN_PRESENT,
  // If no traffic_sign, mark as missing
  TRAFFIC_SIGN_MISSING,
]

export const getTrafficSignLegend = (): LayerLegend => ({
  items: [
    { color: TRAFFIC_SIGN_NONE, label: 'Kein Verkehrszeichen (explizit)' },
    { color: TRAFFIC_SIGN_PRESENT, label: 'Verkehrszeichen angegeben' },
    { color: TRAFFIC_SIGN_DAMAGE, label: 'Verkehrszeichen angegeben mit Hinweis Schäden' },
    { color: TRAFFIC_SIGN_MISSING, label: '[TODO] Verkehrszeichen fehlt' },
  ],
})
