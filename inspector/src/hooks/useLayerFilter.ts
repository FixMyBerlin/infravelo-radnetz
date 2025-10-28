import type { ExpressionSpecification } from 'maplibre-gl'
import { LAYER_LEGENDS } from '../components/shared/legends'
import type { CategoryId } from '../components/shared/categories'
import { createColorFilter } from '../components/shared/colorFilterUtils'
import { useColorFilters } from './useColorFilters'

/**
 * Hook that provides the MapLibre filter expression for a given layer
 * based on active color filters.
 */
export const useLayerFilter = (layerId: CategoryId): ExpressionSpecification | null => {
  const { getActiveColors, hasActiveFilters } = useColorFilters()

  const legend = LAYER_LEGENDS[layerId]
  if (!legend) return null

  // If no filters are active for this layer, show everything
  if (!hasActiveFilters(layerId)) return null

  const activeColors = getActiveColors(layerId)
  return createColorFilter(legend.items, activeColors)
}
