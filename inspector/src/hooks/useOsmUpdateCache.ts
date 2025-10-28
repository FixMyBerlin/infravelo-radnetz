import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchOsmElements } from '../utils/overpassApi'

type OsmIdWithType = {
  osmId: number
  osmType: string
}

type OsmElement = {
  type: string
  id: number
  timestamp: string
  user: string
  changeset: number
}

type OsmUpdateStatus = {
  osmId: number
  osmType: string
  timestamp: string
  user: string
  changeset: number
  isOsmNewer: boolean
}

type UseOsmUpdateCacheParams = {
  osmIds: OsmIdWithType[]
  tildaDataDate: Date | null
  enabled?: boolean
}

// Simple in-memory cache for OSM elements - persists for entire session
const osmElementCache = new Map<string, OsmElement>()

/**
 * Hook that fetches OSM element metadata and compares with TILDA data date
 * Uses simple Map-based caching to avoid re-fetching already known data
 */
export const useOsmUpdateCache = ({
  osmIds,
  tildaDataDate,
  enabled = true,
}: UseOsmUpdateCacheParams) => {
  // Split OSM IDs into cached and uncached
  const { cachedIds, uncachedIds } = useMemo(() => {
    const cachedIds = new Set<OsmIdWithType>()
    const uncachedIds = new Set<OsmIdWithType>()

    for (const osmId of osmIds) {
      const cacheKey = `${osmId.osmType}:${osmId.osmId}`
      const cachedData = osmElementCache.get(cacheKey)

      if (cachedData) {
        cachedIds.add(osmId)
      } else {
        uncachedIds.add(osmId)
      }
    }

    return { cachedIds, uncachedIds }
  }, [osmIds])

  // Fetch only uncached OSM IDs
  const uncachedQuery = useQuery({
    queryKey: [
      'osmUpdateCache',
      'uncached',
      Array.from(uncachedIds)
        .map((id) => `${id.osmType}:${id.osmId}`)
        .sort(),
    ],
    queryFn: async () => {
      if (!tildaDataDate || uncachedIds.size === 0) {
        return {}
      }

      const elementsMap = await fetchOsmElements(Array.from(uncachedIds))

      const result: Record<number, OsmUpdateStatus> = {}

      for (const { osmId, osmType } of Array.from(uncachedIds)) {
        const element = elementsMap[osmId]

        if (element) {
          const osmTimestamp = new Date(element.timestamp)
          const isOsmNewer = osmTimestamp > tildaDataDate

          result[osmId] = {
            osmId,
            osmType,
            timestamp: element.timestamp,
            user: element.user,
            changeset: element.changeset,
            isOsmNewer,
          }

          // Cache individual OSM element for future use
          osmElementCache.set(`${osmType}:${osmId}`, element)
        }
        // Skip elements not found in OSM (deleted or invalid ID)
      }

      return result
    },
    enabled: enabled && uncachedIds.size > 0 && !!tildaDataDate,
    staleTime: 1000 * 60 * 15, // 15 minutes
    retry: 2,
    retryDelay: 2000,
  })

  // Combine cached and uncached data
  const combinedData = useMemo(() => {
    const result: OsmUpdateStatus[] = []

    // Add cached data
    for (const { osmId, osmType } of Array.from(cachedIds)) {
      const cacheKey = `${osmType}:${osmId}`
      const cachedElement = osmElementCache.get(cacheKey)

      if (cachedElement && tildaDataDate) {
        const osmTimestamp = new Date(cachedElement.timestamp)
        const isOsmNewer = osmTimestamp > tildaDataDate

        result.push({
          osmId,
          osmType,
          timestamp: cachedElement.timestamp,
          user: cachedElement.user,
          changeset: cachedElement.changeset,
          isOsmNewer,
        })
      }
    }

    // Add uncached data
    if (uncachedQuery.data) {
      result.push(...Object.values(uncachedQuery.data))
    }

    return result
  }, [cachedIds, uncachedQuery.data, tildaDataDate])

  return {
    data: combinedData,
    isLoading: uncachedQuery.isLoading,
    error: uncachedQuery.error,
    isFetching: uncachedQuery.isFetching,
  }
}
