import type { LayerLegend } from './types'

export const PRESENT_COLOR = '#32CD32' // green - both sides are marked as not expected/no
export const CANDIDATE_COLOR = '#0000FF'

export const getDualCarrigewayLegend = (): LayerLegend => ({
  items: [
    { color: PRESENT_COLOR, label: 'dual_carriagewy=yes' },
    { color: CANDIDATE_COLOR, label: 'Kandidat da oneway=yes aber kein dual_carriagewy=yes' },
  ],
})
