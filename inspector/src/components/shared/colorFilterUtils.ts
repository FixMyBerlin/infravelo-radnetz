import type { ExpressionSpecification } from 'maplibre-gl'
import type { LegendItem } from './types'

/**
 * Creates a MapLibre filter expression based on active legend items.
 * This allows filtering features by their visual representation (color).
 *
 * @param items - All legend items with their filter expressions
 * @param activeLabels - Labels of active/visible items
 * @returns A MapLibre filter expression, or null if all items are active
 */
export const createColorFilter = (
  items: LegendItem[],
  activeLabels: string[],
): ExpressionSpecification | null => {
  // If no active filters or all items are active, show everything
  if (activeLabels.length === 0 || activeLabels.length === items.length) {
    return null
  }

  // Get filter expressions for active items
  const activeExpressions = items
    .filter((item) => activeLabels.includes(item.label))
    .map((item) => item.filterExpression)
    .filter((expr): expr is ExpressionSpecification => expr !== undefined)

  // If no filter expressions defined, we can't filter
  if (activeExpressions.length === 0) {
    return null
  }

  // If only one active expression, return it directly
  if (activeExpressions.length === 1) {
    return activeExpressions[0] as ExpressionSpecification
  }

  // Otherwise, combine with 'any' (OR logic)
  return ['any', ...activeExpressions] as ExpressionSpecification
}
