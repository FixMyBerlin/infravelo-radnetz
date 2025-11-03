import clsx from 'clsx'
import { formatDistanceToNow } from 'date-fns'
import type { OsmFeatureType } from 'osm-api'
import type { MapGeoJSONFeature } from 'react-map-gl/maplibre'
import { useOsmFeature } from '../hooks/useOsmFeature'
import { useTildaUpdateInfo } from '../hooks/useTildaUpdateInfo'
import { longOsmType } from '../utils/osmTypes'

type Props = {
  feature: MapGeoJSONFeature
  source: 'Production' | 'Staging' | 'Development'
}

export const OsmUpdateNotice = ({ feature, source }: Props) => {
  const { osm_id, osm_type } = feature.properties

  let osmType: OsmFeatureType | null = null
  if (osm_type && longOsmType[osm_type.toUpperCase() as keyof typeof longOsmType]) {
    osmType = longOsmType[osm_type.toUpperCase() as keyof typeof longOsmType]
  }

  const {
    data: osmData,
    isLoading: osmLoading,
    error: osmError,
  } = useOsmFeature({
    osmType,
    osmId: Number(osm_id),
  })

  const { data: tildaData, isLoading: tildaLoading } = useTildaUpdateInfo(source)

  // Early return if osm_id or osm_type are missing (e.g., for Mapillary features)
  if (!osm_id || !osm_type) {
    return null
  }

  if (osmLoading || tildaLoading) {
    return (
      <div className="mb-4 rounded border border-gray-300 bg-gray-50 p-3 text-sm">
        Loading OSM update info...
      </div>
    )
  }

  if (osmError || !osmData || !tildaData) {
    return null
  }

  const osmTimestamp = new Date(osmData.timestamp)
  const tildaSourceDate = tildaData.osm_data_from

  // Compare timestamps to determine if OSM data is newer or older than TILDA source
  const isOsmNewer = osmTimestamp > tildaSourceDate
  const relativeTime = formatDistanceToNow(osmTimestamp, { addSuffix: true })
  const absoluteTime = osmTimestamp.toLocaleString('de-DE')

  return (
    <div
      className={clsx(
        'mb-4 rounded border p-3 text-sm',
        isOsmNewer
          ? 'border-purple-300 bg-purple-50 text-purple-800'
          : 'border-blue-300 bg-blue-50 text-blue-800',
      )}
    >
      {isOsmNewer ? (
        <div>
          <strong>TILDA Daten veraltet.</strong> Vor {relativeTime} aktualisiert von {osmData.user}{' '}
          in{' '}
          <a
            href={`https://www.openstreetmap.org/changeset/${osmData.changeset}`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:no-underline"
          >
            {osmData.changeset}
          </a>{' '}
          ({absoluteTime}).{' '}
          <a
            href={`https://osmcha.org/changesets/${osmData.changeset}`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:no-underline"
          >
            OSMCha
          </a>
        </div>
      ) : (
        <div>
          <strong>TILDA Daten aktuell.</strong> Zuletzt aktualisiert vor {relativeTime} (
          {absoluteTime}) von {osmData.user} in{' '}
          <a
            href={`https://www.openstreetmap.org/changeset/${osmData.changeset}`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:no-underline"
          >
            {osmData.changeset}
          </a>
        </div>
      )}
    </div>
  )
}
