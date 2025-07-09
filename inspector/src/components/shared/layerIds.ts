// Interactive layer IDs used by the map
export const INTERACTIVE_LAYER_IDS = [
  'roads-line',
  'roadsPath-line',
  'bikelanes-line',
  'roads-age-line',
  'roadsPath-age-line',
  'bikelanes-age-line',
] as const

export type InteractiveLayerId = (typeof INTERACTIVE_LAYER_IDS)[number]
