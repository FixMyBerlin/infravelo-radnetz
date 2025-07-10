import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { z } from 'zod'

const TILDA_API_URL = 'https://tilda-geo.de/api'

const DatesSchema = z.object({
  processed_at: z.coerce.date(),
  osm_data_from: z.coerce.date(),
})

const fetchProcessingDates = async () => {
  const response = await fetch(`${TILDA_API_URL}/processing-dates`)
  const data = await response.json()
  return DatesSchema.parse(data)
}

export const TildaUpdateInfo = () => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['tildaProcessingDates'],
    queryFn: fetchProcessingDates,
    staleTime: 1000 * 60 * 5, // Consider data fresh for 5 minutes
    refetchInterval: 1000 * 60 * 5, // Refetch every 5 minutes
  })

  if (isLoading) {
    return <div className="text-xs text-gray-500">Loading TILDA update info...</div>
  }
  if (error) {
    console.error('ERROR TildaUpdateInfo:', error)
    return <div className="text-xs text-red-500">Failed to load TILDA update info</div>
  }
  if (data === undefined) {
    console.info('ERROR TildaUpdateInfo:', data)
    return <div className="text-xs text-red-500">Failed to load TILDA update info</div>
  }

  return (
    <div className="text-xs text-gray-600">
      TILDA last updated: {formatDistanceToNow(data.processed_at)} ago
      <div className="text-[0.6rem] text-gray-400">
        OSM data from: {formatDistanceToNow(data.osm_data_from)} ago
      </div>
    </div>
  )
}
