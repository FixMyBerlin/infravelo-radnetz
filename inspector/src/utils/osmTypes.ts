export const longOsmType = {
  W: 'way',
  N: 'node',
  R: 'relation',
  w: 'way',
  n: 'node',
  r: 'relation',
  // Just so we can use this for both format
  way: 'way',
  node: 'node',
  relation: 'relation',
} as const

export type OsmTypeKey = keyof typeof longOsmType
export type OsmTypeValue = (typeof longOsmType)[OsmTypeKey]
