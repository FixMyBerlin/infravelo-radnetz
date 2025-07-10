export type LegendItem = {
  color: string
  label: string
  // pattern?: 'solid' | 'dashed' | 'dotted'
}

export type LayerLegend = {
  items: LegendItem[]
}
