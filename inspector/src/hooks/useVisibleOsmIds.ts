import { useCallback, useEffect, useState } from 'react'
import { useMap } from 'react-map-gl/maplibre'

type OsmIdWithType = {
  osmId: number
  osmType: string
}

type UseVisibleOsmIdsParams = {
  enabled?: boolean
  debounceMs?: number
}

/**
 * Hook that extracts OSM IDs from currently visible features on the map
 * Debounces viewport changes to avoid excessive queries
 */
export const useVisibleOsmIds = ({
  enabled = true,
  debounceMs = 500,
}: UseVisibleOsmIdsParams = {}) => {
  const { current: map } = useMap()
  const [osmIds, setOsmIds] = useState<OsmIdWithType[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const extractOsmIds = useCallback(() => {
    if (!map || !enabled) {
      setOsmIds([])
      return
    }

    setIsLoading(true)

    try {
      // Query all rendered features
      const allFeatures = map.queryRenderedFeatures()

      // Filter features from our data sources
      const dataSources = ['roads', 'roadsPathClasses', 'bikelanes']
      const relevantFeatures = allFeatures.filter((feature) => dataSources.includes(feature.source))

      // Extract OSM IDs and deduplicate
      const osmIdSet = new Set<string>()
      const extractedIds: OsmIdWithType[] = []

      for (const feature of relevantFeatures) {
        const osmId = feature.properties?.osm_id
        const osmType = feature.properties?.osm_type

        if (osmId && osmType) {
          const key = `${osmType}:${osmId}`
          if (!osmIdSet.has(key)) {
            osmIdSet.add(key)
            extractedIds.push({
              osmId: Number(osmId),
              osmType: String(osmType),
            })
          }
        }
      }

      setOsmIds(extractedIds)
    } catch (error) {
      console.error('Failed to extract OSM IDs from map:', error)
      setOsmIds([])
    } finally {
      setIsLoading(false)
    }
  }, [map, enabled])

  useEffect(() => {
    if (!map || !enabled) {
      return
    }

    // Debounced extraction
    const timeoutId = setTimeout(extractOsmIds, debounceMs)

    // Listen to map events that change visible features
    const handleMapChange = () => {
      clearTimeout(timeoutId)
      setTimeout(extractOsmIds, debounceMs)
    }

    map.on('moveend', handleMapChange)
    map.on('zoomend', handleMapChange)
    map.on('resize', handleMapChange)

    // Initial extraction
    extractOsmIds()

    return () => {
      clearTimeout(timeoutId)
      map.off('moveend', handleMapChange)
      map.off('zoomend', handleMapChange)
      map.off('resize', handleMapChange)
    }
  }, [map, enabled, debounceMs, extractOsmIds])

  return {
    osmIds,
    isLoading,
    refetch: extractOsmIds,
  }
}
