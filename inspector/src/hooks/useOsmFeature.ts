import { skipToken, useQuery } from '@tanstack/react-query'
import { getFeature } from 'osm-api'

type OsmFeatureType = 'node' | 'way' | 'relation'

type OsmFeature = {
  tags?: Record<string, string>
  type: string
  id: number
  version: number
  changeset: number
  timestamp: string
  uid: number
  user: string
}

type UseOsmFeatureParams = {
  osmType: OsmFeatureType | null
  osmId: number | null
}

export const useOsmFeature = ({ osmType, osmId }: UseOsmFeatureParams) => {
  return useQuery({
    queryKey: ['osmFeature', osmType, osmId],
    queryFn:
      osmType && osmId
        ? async () => {
            const data = await getFeature(osmType, osmId)
            // getFeature returns an array, take the first element
            const firstElement = Array.isArray(data) ? data[0] : data
            return firstElement as OsmFeature
          }
        : skipToken,
    // We use skipToken instead https://tanstack.com/query/v5/docs/framework/react/guides/disabling-queries#typesafe-disabling-of-queries-using-skiptoken
    // enabled: !!osmType && !!osmId
    staleTime: 1000 * 60 * 15, // 15 minutes no-revalidate as requested
  })
}
