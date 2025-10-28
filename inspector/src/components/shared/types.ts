export type LegendItem = {
  color: string
  label: string
  // Optional property expression to match against for filtering
  // This will be used to generate the MapLibre filter expression
  filterExpression?: unknown
  // pattern?: 'solid' | 'dashed' | 'dotted'
}

export type LayerLegend = {
  items: LegendItem[]
}
