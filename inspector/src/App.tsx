import { Square3Stack3DIcon, XMarkIcon } from '@heroicons/react/24/outline'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { parseAsArrayOf, parseAsString, parseAsStringLiteral, useQueryState } from 'nuqs'
import { Protocol } from 'pmtiles'
import { Fragment, useEffect, useState } from 'react'
import Map, {
  Layer,
  MapProvider,
  NavigationControl,
  Source,
  type MapGeoJSONFeature,
  type MapLayerMouseEvent,
  type MapSourceDataEvent,
  type ViewStateChangeEvent,
} from 'react-map-gl/maplibre'
import { AddMapImage } from './components/AddMapImage'
import { BackgroundLayer } from './components/BackgroundLayer'
import { DataLayer } from './components/DataLayer'
import { Inspector } from './components/Inspector'
import { StaticLayers } from './components/StaticLayers'
import { useMapParam } from './components/useMapParam/useMapParam'

const TILE_URLS = {
  Production: 'https://tiles.tilda-geo.de',
  Staging: 'https://staging-tiles.tilda-geo.de',
  Development: 'http://localhost:3000',
} as const

const baseMapStyle =
  'https://api.maptiler.com/maps/08357855-50d4-44e1-ac9f-ea099d9de4a5/style.json?key=ECOoUBmpqklzSCASXxcu'

const string2RandColor = (str: string) => {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  const r = (hash >> 24) & 0xff
  const g = (hash >> 16) & 0xff
  const b = (hash >> 8) & 0xff
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`
}

const typeStyles = [
  {
    type: 'circle',
    geoType: 'Point',
    alpha: 0.8,
    styles: {},
  },
  {
    type: 'line',
    geoType: 'LineString',
    alpha: 0.8,
    styles: { 'line-width': 3 },
  },
  {
    type: 'fill',
    geoType: 'Polygon',
    alpha: 0.4,
    styles: {},
  },
] as const

const arrowImageId = 'arrow-image'

const FIXED_LAYERS = [
  { key: 'bikelanes', color: '#1E90FF' },
  { key: 'roads', color: '#32CD32' },
  { key: 'roadsPathClasses', color: '#FF8C00' },
] as const

const App = () => {
  const sources = ['Production', 'Staging', 'Development'] as const
  const [source, setSource] = useQueryState(
    'source',
    parseAsStringLiteral(sources).withDefault('Production'),
  )
  const { mapParam, setMapParam } = useMapParam()
  const [activeLayers, setActiveLayers] = useQueryState(
    'layers',
    parseAsArrayOf(parseAsString).withDefault([]),
  )
  const [layers, setLayers] = useState<string[]>([])
  const [sourceLayerMap, setSourceLayerMap] = useState<Record<string, string>>({})
  const [mapLoaded, setMapLoaded] = useState(false)
  const [searchTerm, setSearchTerm] = useQueryState('search', parseAsString.withDefault(''))
  const [showLayerPanel, setShowLayerPanel] = useState(true)

  useEffect(() => {
    // Register pmtiles protocol globally for all maplibre usage
    const protocol = new Protocol()
    maplibregl.addProtocol('pmtiles', protocol.tile)
    return () => {
      maplibregl.removeProtocol('pmtiles')
    }
  }, [])

  useEffect(() => {
    const fetchLayers = async () => {
      try {
        const response = await fetch(`${TILE_URLS[source]}/catalog`)
        const catalog = await response.json()
        // Only use the fixed layers that are present in the catalog
        const available = Object.keys(catalog.tiles)
        setLayers(FIXED_LAYERS.map((l) => l.key).filter((key) => available.includes(key)))
      } catch (error) {
        console.error('Error fetching layers:', error)
      }
    }
    fetchLayers()
  }, [source])

  // Filtered layers based on search
  const filteredLayers = layers
    .filter((layer) => layer.toLowerCase().includes(searchTerm.toLowerCase()))
    .sort((a, b) => a.localeCompare(b))

  const toggleLayer = (layer: string) => {
    setActiveLayers((prev) =>
      prev.includes(layer) ? prev.filter((l) => l !== layer) : [...prev, layer],
    )
  }

  const handleSourcesLoaded = (event: MapSourceDataEvent) => {
    // Get the layerId
    // @ts-expect-error this is fine
    let layerId = event?.style?.sourceCaches?.[event.sourceId]?._source?.vectorLayerIds?.[0]
    // Special treatment for function
    layerId = layerId || event.sourceId.replace('atlas_generalized_', '')

    setSourceLayerMap((prev) => {
      prev[event.sourceId] = layerId
      return prev
    })

    if (!sourceColor[event.sourceId]) {
      handleColorChange(event.sourceId, string2RandColor(event.sourceId))
    }
  }

  // Set initial color for each fixed layer
  const [sourceColor, setSourceColors] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const { key, color } of FIXED_LAYERS) {
      initial[key] = color
    }
    return initial
  })
  const handleColorChange = (layer: string, color: string) => {
    setSourceColors((prev) => ({
      ...prev,
      [layer]: color,
    }))
  }

  const handleMoveEnd = (event: ViewStateChangeEvent) => {
    const { latitude, longitude, zoom } = event.viewState
    void setMapParam({ zoom, lat: latitude, lng: longitude }, { history: 'replace' })
  }

  const handleLoad = () => {
    // Only when `loaded` all `Map` feature are actually usable (https://github.com/visgl/react-map-gl/issues/2123)
    setMapLoaded(true)
  }

  const [inspectorFeatures, setInspectorFeatures] = useState<MapGeoJSONFeature[]>([])
  const handleMapClick = ({ features, target: map }: MapLayerMouseEvent) => {
    inspectorFeatures.forEach((feature) => {
      map.setFeatureState(
        { source: feature.source, sourceLayer: sourceLayerMap[feature.source], id: feature.id },
        { selected: false },
      )
    })

    if (features && features.length > 0) {
      setInspectorFeatures(features)

      features.forEach((feature) => {
        map.setFeatureState(
          { source: feature.source, sourceLayer: sourceLayerMap[feature.source], id: feature.id },
          { selected: true },
        )
      })
    } else {
      setInspectorFeatures([])
    }
  }

  const [hoverFeatures, setHoverFeatures] = useState<MapGeoJSONFeature[]>([])
  const handleFeatureHover = (
    features: MapLayerMouseEvent['features'],
    map: MapLayerMouseEvent['target'],
  ) => {
    hoverFeatures.forEach((feature) => {
      map.setFeatureState(
        { source: feature.source, sourceLayer: sourceLayerMap[feature.source], id: feature.id },
        { hover: false },
      )
    })

    if (features && features.length > 0) {
      setHoverFeatures(features)

      features.forEach((feature) => {
        map.setFeatureState(
          { source: feature.source, sourceLayer: sourceLayerMap[feature.source], id: feature.id },
          { hover: true },
        )
      })
    } else {
      setHoverFeatures([])
    }
  }

  const [cursorStyle, setCursorStyle] = useState('grab')
  const handleMouseMove = ({ features, target: map }: MapLayerMouseEvent) => {
    setCursorStyle(features?.length ? 'pointer' : 'grab')
    handleFeatureHover(features, map)
  }

  const handleMouseLeave = ({ target: map }: MapLayerMouseEvent) => {
    setCursorStyle('grab')
    handleFeatureHover([], map)
  }

  return (
    <MapProvider>
      <main className="flex h-screen">
        {/* Layer panel toggle button */}
        {!showLayerPanel && (
          <button
            className="absolute top-4 left-4 z-50 cursor-pointer rounded-full bg-white p-2 shadow hover:bg-blue-200"
            onClick={() => setShowLayerPanel(true)}
            aria-label="Show layers"
          >
            <Square3Stack3DIcon className="h-6 w-6 text-gray-700" />
          </button>
        )}
        {/* Layer List Panel */}
        {showLayerPanel && (
          <nav className="relative w-1/4 overflow-y-auto bg-gray-100 p-4 text-sm inset-shadow-inherit">
            <button
              className="absolute top-4 right-4 z-10 cursor-pointer rounded-full bg-white p-1 hover:bg-blue-200"
              onClick={() => setShowLayerPanel(false)}
              aria-label="Close layers panel"
            >
              <XMarkIcon className="h-5 w-5 text-gray-700" />
            </button>
            <section className="mb-4">
              <h2 className="font-bold">Tile Sources</h2>
              <ul className="flex items-center gap-3">
                {Object.keys(TILE_URLS).map((key) => (
                  <li key={key}>
                    <label className="flex w-full items-center gap-1">
                      <input
                        type="radio"
                        name="source"
                        value={key}
                        checked={source === key}
                        // @ts-expect-error that is fine
                        onChange={() => setSource(key)}
                      />
                      {key}
                      {source === key && (
                        <a
                          href={`${TILE_URLS[source]}/catalog`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[0.5rem] text-blue-500 hover:underline"
                        >
                          View Catalog
                        </a>
                      )}
                    </label>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h2 className="font-bold">Layers</h2>
                <input
                  type="text"
                  placeholder="Search layers..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="rounded border px-2 py-1 text-sm"
                />
              </div>
              <ul>
                {filteredLayers.map((layer) => (
                  <li key={layer} className="flex items-center justify-between">
                    <label className="flex w-full items-center gap-2">
                      <input
                        type="checkbox"
                        checked={activeLayers.includes(layer)}
                        onChange={() => toggleLayer(layer)}
                      />
                      {layer}

                      {activeLayers.includes(layer) && (
                        <a
                          href={`${TILE_URLS[source]}/${layer}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[0.5rem] whitespace-nowrap text-blue-500 hover:underline"
                        >
                          Tile JSON
                        </a>
                      )}
                    </label>
                    <input
                      type="color"
                      defaultValue={sourceColor[layer]}
                      onChange={(e) => handleColorChange(layer, e.target.value)}
                      className="size-5 flex-none overflow-clip rounded-4xl"
                    />
                  </li>
                ))}
              </ul>
            </section>
          </nav>
        )}

        <div className="relative flex-1">
          <Map
            id="myMap"
            initialViewState={{
              longitude: mapParam.lng,
              latitude: mapParam.lat,
              zoom: mapParam.zoom,
            }}
            minZoom={9}
            interactiveLayerIds={activeLayers
              .map((l) => typeStyles.map(({ type }) => `${l}-${type}`))
              .flat()}
            cursor={cursorStyle}
            onMoveEnd={handleMoveEnd}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            onClick={handleMapClick}
            onSourceData={handleSourcesLoaded}
            onLoad={handleLoad}
            style={{ width: '100%', height: '100%' }}
            // mapStyle="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
            mapStyle={baseMapStyle}
          >
            <AddMapImage name={arrowImageId} url="/map-style-line-direction-arrow.png" sdf={true} />

            <NavigationControl position="bottom-right" />

            <BackgroundLayer />

            <DataLayer />
            <StaticLayers />

            {layers.map((layer) => (
              <Source
                key={layer}
                id={layer}
                type="vector"
                url={`${TILE_URLS[source]}/${layer}`}
                promoteId="id"
              />
            ))}

            {mapLoaded == true &&
              activeLayers.map((layer) => (
                <Fragment key={layer}>
                  {typeStyles.map(({ type, geoType, alpha, styles }) => {
                    if (!sourceLayerMap[layer]) {
                      console.log(
                        'ERROR: `sourceLayerMap` does not know the source-layer for the current layer',
                        layer,
                        sourceLayerMap,
                      )
                      return null
                    }

                    return (
                      <Fragment key={`${layer}-${type}`}>
                        {/* @ts-expect-error the `...styles` does not work for TS */}
                        <Layer
                          key={`${layer}-${type}`}
                          id={`${layer}-${type}`}
                          type={type}
                          source={layer}
                          paint={{
                            [`${type}-color`]: [
                              'case',
                              ['boolean', ['feature-state', 'hover'], false],
                              'black',
                              ['boolean', ['feature-state', 'selected'], false],
                              'red',
                              sourceColor[layer],
                            ],
                            [`${type}-opacity`]: [
                              'case',
                              ['boolean', ['feature-state', 'selected'], false],
                              1,
                              alpha,
                            ],
                            ...styles,
                          }}
                          filter={['==', '$type', geoType]}
                          source-layer={sourceLayerMap[layer]}
                        />

                        {type === 'line' && (
                          <Layer
                            key={`${layer}-arrow`}
                            id={`${layer}-arrow`}
                            type="symbol"
                            source={layer}
                            layout={{
                              'symbol-placement': 'line',
                              'icon-image': arrowImageId,
                              'icon-size': 0.25,
                              'icon-allow-overlap': true,
                              'icon-ignore-placement': true,
                              'icon-rotation-alignment': 'map',
                            }}
                            paint={{
                              'icon-color': [
                                'case',
                                ['boolean', ['feature-state', 'hover'], false],
                                'black',
                                ['boolean', ['feature-state', 'selected'], false],
                                'red',
                                sourceColor[layer],
                              ],
                            }}
                            filter={['==', '$type', geoType]}
                            source-layer={sourceLayerMap[layer]}
                          />
                        )}
                      </Fragment>
                    )
                  })}
                </Fragment>
              ))}
          </Map>
        </div>

        {/* Sidebar Panel */}
        <Inspector inspectorFeatures={inspectorFeatures} />
      </main>
    </MapProvider>
  )
}

export default App
