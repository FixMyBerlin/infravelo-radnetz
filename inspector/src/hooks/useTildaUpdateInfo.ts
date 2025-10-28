import { useQuery } from '@tanstack/react-query'
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

type Source = keyof typeof API_URLS

const fetchProcessingDates = async (apiUrl: string) => {
  const response = await fetch(`${apiUrl}/processing-dates`)
  const data = await response.json()
  return DatesSchema.parse(data)
}

export const useTildaUpdateInfo = (source: Source) => {
  return useQuery({
    queryKey: ['tildaProcessingDates', source],
    queryFn: () => fetchProcessingDates(API_URLS[source]),
    staleTime: 1000 * 60 * 5, // Consider data fresh for 5 minutes
    refetchInterval: 1000 * 60 * 5, // Refetch every 5 minutes
  })
}
