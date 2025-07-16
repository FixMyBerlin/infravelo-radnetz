import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { z } from 'zod'

const API_URLS = {
  Production: 'https://tilda-geo.de/api',
  Staging: 'https://staging.tilda-geo.de/api',
  Development: 'http://localhost:5173/api',
} as const

const DatesSchema = z.object({
  processed_at: z.coerce.date(),
  osm_data_from: z.coerce.date(),
})

type Props = {
  source: keyof typeof API_URLS
}

const fetchProcessingDates = async (apiUrl: string) => {
  const response = await fetch(`${apiUrl}/processing-dates`)
  const data = await response.json()
  return DatesSchema.parse(data)
}

export const TildaUpdateInfo = ({ source }: Props) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['tildaProcessingDates', source],
    queryFn: () => fetchProcessingDates(API_URLS[source]),
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
    <div className="text-xs text-gray-500">
      <abbr title={data.osm_data_from.toISOString()}>
        OSM data from: {formatDistanceToNow(data.osm_data_from)} ago
      </abbr>
      <br />
      <abbr title={data.processed_at.toISOString()}>
        TILDA update finished: {formatDistanceToNow(data.processed_at)} ago
      </abbr>
    </div>
  )
}
