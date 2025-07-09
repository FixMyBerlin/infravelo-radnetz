import type { LayerLegend } from './types'

export const PRESENT_COLOR = '#32CD32' // green - both sides are marked as not expected/no
export const MISSING_COLOR = '#FF0000' // red - at least one side is missing the marking
export const UNDEFINED_COLOR = '#808080' // gray - for other surfaces

export const getCyclewayNoLayerLegend = (): LayerLegend => ({
  items: [
    { color: MISSING_COLOR, label: '[TODO] Wahrscheinlich fehlt ein cycleway:SIDE=no' },
    { color: PRESENT_COLOR, label: 'Es gibt einen Radweg oder keiner ist erwartet' },
    { color: UNDEFINED_COLOR, label: 'Es liegen keine Daten vor' },
  ],
})
