import { parseAsJson, useQueryState } from 'nuqs'

export type ColorFilters = {
  [layerId: string]: {
    [colorOrLabel: string]: boolean
  }
}

/**
 * Hook to manage color filters for layers.
 * Returns the current color filters and functions to update them.
 */
export const useColorFilters = () => {
  const [colorFilters, setColorFilters] = useQueryState<ColorFilters>(
    'colorFilters',
    parseAsJson<ColorFilters>((value) => value as ColorFilters).withDefault({}),
  )

  const toggleColor = (layerId: string, colorOrLabel: string) => {
    setColorFilters((prev) => {
      const layerFilters = prev[layerId] || {}
      const newLayerFilters = {
        ...layerFilters,
        [colorOrLabel]: !layerFilters[colorOrLabel],
      }
      return {
        ...prev,
        [layerId]: newLayerFilters,
      }
    })
  }

  const getActiveColors = (layerId: string): string[] => {
    const layerFilters = colorFilters[layerId] || {}
    // Return colors that are explicitly set to true
    return Object.entries(layerFilters)
      .filter(([, isActive]) => isActive)
      .map(([color]) => color)
  }

  const isColorActive = (layerId: string, colorOrLabel: string): boolean => {
    const layerFilters = colorFilters[layerId] || {}
    // If no filters set for this layer, all colors are active
    const hasAnyFilters = Object.values(layerFilters).some((v) => v === true)
    if (!hasAnyFilters) return true
    // Otherwise, only active if explicitly set to true
    return layerFilters[colorOrLabel] === true
  }

  const hasActiveFilters = (layerId: string): boolean => {
    const layerFilters = colorFilters[layerId] || {}
    return Object.values(layerFilters).some((v) => v === true)
  }

  return {
    colorFilters,
    toggleColor,
    getActiveColors,
    isColorActive,
    hasActiveFilters,
  }
}
