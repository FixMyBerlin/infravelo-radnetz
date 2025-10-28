import { formatDistanceToNow } from 'date-fns'
import { useSource } from '../hooks/useSource'
import { useTildaUpdateInfo } from '../hooks/useTildaUpdateInfo'

export const TildaUpdateInfo = () => {
  const { source } = useSource()
  const { data, isLoading, error } = useTildaUpdateInfo(source)

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
