import { Fragment, useEffect } from 'react'
import { Layer, useMap } from 'react-map-gl/maplibre'
import { useContextLayers } from '../hooks/useContextLayers'
import { useOsmUpdateCache } from '../hooks/useOsmUpdateCache'
import { useSource } from '../hooks/useSource'
import { useTildaUpdateInfo } from '../hooks/useTildaUpdateInfo'
import { useVisibleOsmIds } from '../hooks/useVisibleOsmIds'
import { categories } from './shared/categories'

type Props = {
  activeLayers: string[]
}

export const OsmUpdateContextLayers = ({ activeLayers }: Props) => {
  const { isActive } = useContextLayers()
  const { current: map } = useMap()
  const { source } = useSource()

  const isOsmUpdateActive = isActive('osm_update_status')

  // Determine which sources are active based on activeLayers
  const activeSources = new Set<string>()
  for (const layerId of activeLayers) {
    const layerConfig = categories.find((cat) => cat.id === layerId)
    if (layerConfig) {
      activeSources.add(layerConfig.source)
    }
  }

  const { osmIds } = useVisibleOsmIds({
    enabled: isOsmUpdateActive,
    debounceMs: 4000, // Debounce Overpass API calls for 4 seconds
  })

  const { data: tildaData } = useTildaUpdateInfo(source)

  const { data: updateStatuses } = useOsmUpdateCache({
    osmIds,
    tildaDataDate: tildaData?.osm_data_from || null,
    enabled: isOsmUpdateActive && osmIds.length > 0,
  })

  // Set feature state for OSM update status
  useEffect(() => {
    if (!map || !updateStatuses || !isOsmUpdateActive) {
      return
    }

    const allFeatures = map.queryRenderedFeatures()
    const dataSources = ['roads', 'roadsPathClasses', 'bikelanes']

    // Create a map of OSM ID to update status for quick lookup
    const updateStatusMap = new Map(
      updateStatuses.map((status) => [status.osmId, status.isOsmNewer]),
    )

    // Set tildaOutdated state for all features based on their OSM update status
    for (const feature of allFeatures) {
      if (dataSources.includes(feature.source) && feature.properties?.osm_id) {
        const osmId = feature.properties.osm_id
        const isOsmNewer = updateStatusMap.get(osmId) ?? false // Default to false if not found
        const sourceLayer =
          feature.source === 'roadsPathClasses' ? 'roadsPathClasses' : feature.source

        try {
          map.setFeatureState(
            {
              source: feature.source,
              sourceLayer: sourceLayer,
              id: feature.id,
            },
            { tildaOutdated: isOsmNewer },
          )
        } catch {
          // Feature might not exist anymore, ignore
        }
      }
    }
  }, [map, updateStatuses, isOsmUpdateActive])

  if (!isOsmUpdateActive) {
    return null
  }

  return (
    <Fragment>
      {/* OSM Update Context Layer for bikelanes */}
      {activeSources.has('bikelanes') && (
        <Layer
          id="osm-update-context-bikelanes"
          type="line"
          source="bikelanes"
          source-layer="bikelanes"
          paint={{
            'line-color': [
              'case',
              ['==', ['feature-state', 'tildaOutdated'], true],
              '#800080', // Purple for updated features
              ['==', ['feature-state', 'tildaOutdated'], false],
              '#4169E1', // Blue for unchanged features
              '#808080', // Gray for missing/unknown data
            ],
            'line-width': 2,
            'line-opacity': 0.8,
            'line-dasharray': [2, 2], // Dotted line pattern
            'line-offset': [
              'case',
              ['==', ['feature-state', 'tildaOutdated'], true],
              6, // Offset to the right for updated features
              -6, // Offset to the left for unchanged features
            ],
          }}
          // beforeId="static-layers-start"
        />
      )}

      {/* OSM Update Context Layer for roads */}
      {activeSources.has('roads') && (
        <Layer
          id="osm-update-context-roads"
          type="line"
          source="roads"
          source-layer="roads"
          paint={{
            'line-color': [
              'case',
              ['==', ['feature-state', 'tildaOutdated'], true],
              '#800080', // Purple for updated features
              ['==', ['feature-state', 'tildaOutdated'], false],
              '#4169E1', // Blue for unchanged features
              '#808080', // Gray for missing/unknown data
            ],
            'line-width': 2,
            'line-opacity': 0.8,
            'line-dasharray': [2, 2], // Dotted line pattern
            'line-offset': [
              'case',
              ['==', ['feature-state', 'tildaOutdated'], true],
              6, // Offset to the right for updated features
              -6, // Offset to the left for unchanged features
            ],
          }}
          // beforeId="static-layers-start"
        />
      )}

      {/* OSM Update Context Layer for roadsPathClasses */}
      {activeSources.has('roadsPathClasses') && (
        <Layer
          id="osm-update-context-roadsPathClasses"
          type="line"
          source="roadsPathClasses"
          source-layer="roadsPathClasses"
          paint={{
            'line-color': [
              'case',
              ['==', ['feature-state', 'tildaOutdated'], true],
              '#800080', // Purple for updated features
              ['==', ['feature-state', 'tildaOutdated'], false],
              '#4169E1', // Blue for unchanged features
              '#808080', // Gray for missing/unknown data
            ],
            'line-width': 2,
            'line-opacity': 0.8,
            'line-dasharray': [2, 2], // Dotted line pattern
            'line-offset': [
              'case',
              ['==', ['feature-state', 'tildaOutdated'], true],
              6, // Offset to the right for updated features
              -6, // Offset to the left for unchanged features
            ],
          }}
          // beforeId="static-layers-start"
        />
      )}
    </Fragment>
  )
}
