import { getFeature } from 'osm-api'
import { useState } from 'react'
import type { MapGeoJSONFeature } from 'react-map-gl/maplibre'

type Props = {
  feature: MapGeoJSONFeature
}

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

export const OsmTagsLoader = ({ feature }: Props) => {
  const [osmData, setOsmData] = useState<OsmFeature | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadOsmTags = async () => {
    if (!feature.properties.osm_id || !feature.properties.osm_type) {
      setError('OSM ID or type not available')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      // Transform short OSM type codes to full names
      const osmTypeMap: Record<string, 'node' | 'way' | 'relation'> = {
        N: 'node',
        W: 'way',
        R: 'relation',
        node: 'node',
        way: 'way',
        relation: 'relation',
      }

      const osmType = osmTypeMap[feature.properties.osm_type.toUpperCase()]
      if (!osmType) {
        setError(`Unknown OSM type: ${feature.properties.osm_type}`)
        return
      }

      const osmId = feature.properties.osm_id

      const data = await getFeature(osmType, osmId)
      // getFeature returns an array, take the first element
      const firstElement = Array.isArray(data) ? data[0] : data
      setOsmData(firstElement as unknown as OsmFeature)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load OSM data')
    } finally {
      setIsLoading(false)
    }
  }

  if (osmData) {
    return (
      <div className="mt-4">
        <h3 className="mb-2 font-semibold">OSM-Tags</h3>
        {/* <pre>{JSON.stringify(osmData, undefined, 2)}</pre> */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse border border-gray-300 text-xs">
            <thead>
              <tr className="bg-gray-100">
                <th className="border border-gray-300 px-2 py-1 text-left font-semibold">Key</th>
                <th className="border border-gray-300 px-2 py-1 text-left font-semibold">Value</th>
              </tr>
            </thead>
            <tbody>
              {osmData.tags &&
                Object.entries(osmData.tags).map(([key, value]) => (
                  <tr key={key} className="hover:bg-gray-50">
                    <td className="border border-gray-300 px-2 py-1 font-mono">{key}</td>
                    <td className="border border-gray-300 px-2 py-1 font-mono">{value}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 text-xs text-gray-500">
          <p>
            Type: {osmData.type} | ID: {osmData.id} | Version: {osmData.version}
          </p>
          <p>
            Last edited by {osmData.user} in changeset {osmData.changeset}
          </p>
          <p>Timestamp: {new Date(osmData.timestamp).toLocaleString()}</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mt-4">
        <button
          onClick={loadOsmTags}
          disabled={isLoading}
          className="text-blue-500 hover:underline disabled:opacity-50"
        >
          OSM-Tags anzeigen
        </button>
        <div className="mt-2 text-xs text-red-500">{error}</div>
      </div>
    )
  }

  return (
    <div className="mt-4">
      <button
        onClick={loadOsmTags}
        disabled={isLoading}
        className="text-blue-500 hover:underline disabled:opacity-50"
      >
        {isLoading ? 'Loading...' : 'OSM-Tags anzeigen'}
      </button>
    </div>
  )
}
