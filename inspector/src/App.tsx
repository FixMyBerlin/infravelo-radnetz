import { Square3Stack3DIcon, XMarkIcon } from '@heroicons/react/24/outline'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import maplibregl, { type MapSourceDataEvent } from 'maplibre-gl'
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
  type ViewStateChangeEvent,
} from 'react-map-gl/maplibre'
import { AddMapImage } from './components/AddMapImage'
import { BackgroundLayer } from './components/BackgroundLayer'
import { BikeLaneAgeLayer } from './components/BikeLaneAgeLayer'
import { BikeLaneLayer } from './components/BikeLaneLayer'
import { BikeLaneMapillaryLayer } from './components/BikeLaneMapillaryLayer'
import { BikeLaneOnewayLayer } from './components/BikeLaneOnewayLayer'
import { BikelaneSurfaceColorLayer } from './components/BikelaneSurfaceColorLayer'
import { BikeLaneSurfaceSettLayer } from './components/BikeLaneSurfaceSettLayer'
import { BikeLaneTrafficSignLayer } from './components/BikeLaneTrafficSignLayer'
import { BikelaneWidthLayer } from './components/BikelaneWidthLayer'
import { Inspector } from './components/Inspector'
import { Legend } from './components/Legend'
import { RoadAgeLayer } from './components/RoadAgeLayer'
import { RoadCyclewayNoLayer } from './components/RoadCyclewayNoLayer'
import { RoadDualCarriagewayLayer } from './components/RoadDualCarriagewayLayer'
import { RoadLayer } from './components/RoadLayer'
import { RoadOnewayLayer } from './components/RoadOnewayLayer'
import { RoadPathAgeLayer } from './components/RoadPathAgeLayer'
import { RoadPathLayer } from './components/RoadPathLayer'
import { RoadPathOnewayLayer } from './components/RoadPathOnewayLayer'
import { RoadPathSurfaceSettLayer } from './components/RoadPathSurfaceSettLayer'
import { RoadSurfaceSettLayer } from './components/RoadSurfaceSettLayer'
import {
  getInteractionLineColor,
  getInteractionLineWidth,
} from './components/shared/interactionStyle'
import { LAYER_LEGENDS } from './components/shared/legends'
import { StaticLayers } from './components/StaticLayers'
import { TildaUpdateInfo } from './components/TildaUpdateInfo'
import { useMapParam } from './components/useMapParam/useMapParam'

const TILE_URLS = {
  Production: 'https://tiles.tilda-geo.de',
  Staging: 'https://staging-tiles.tilda-geo.de',
  Development: 'http://localhost:3000',
} as const

const baseMapStyle =
  'https://api.maptiler.com/maps/08357855-50d4-44e1-ac9f-ea099d9de4a5/style.json?key=ECOoUBmpqklzSCASXxcu'

const arrowImageId = 'arrow-image'

const categories = [
  // Bike lanes and their variants
  { id: 'bikelanes', source: 'bikelanes' },
  { id: 'bikelanesAge', source: 'bikelanes', inspectorHighlightTags: ['updated_at'] },
  { id: 'bikelanesOneway', source: 'bikelanes', inspectorHighlightTags: ['oneway', 'oneway_bike'] },
  {
    id: 'bikelanesSurface',
    source: 'bikelanes',
    inspectorHighlightTags: ['surface'],
  },
  {
    id: 'bikelanesWidth',
    source: 'bikelanes',
    inspectorHighlightTags: ['width', 'width_source', 'category'],
  },
  {
    id: 'bikelanSurfaceColor',
    source: 'bikelanes',
    inspectorHighlightTags: ['surface_color'],
  },
  {
    id: 'bikelanesTrafficSign',
    source: 'bikelanes',
    inspectorHighlightTags: ['traffic_sign'],
  },
  {
    id: 'bikelanesMapillary',
    source: 'bikelanes',
    inspectorHighlightTags: [
      'mapillary',
      'mapillary_left',
      'mapillary_right',
      'mapillary_traffic_sign',
      'traffic_sign',
    ],
  },

  // Roads and their variants
  { id: 'roads', source: 'roads' },
  { id: 'roadsAge', source: 'roads' },
  { id: 'roadsOneway', source: 'roads' },
  { id: 'roadsSurface', source: 'roads' },
  { id: 'roadsCyclewayNo', source: 'roads' },
  { id: 'roadDualCarriageway', source: 'roads' },

  // Road paths and their variants
  { id: 'roadsPath', source: 'roadsPathClasses' },
  { id: 'roadsPathAge', source: 'roadsPathClasses' },
  { id: 'roadsPathOneway', source: 'roadsPathClasses' },
  { id: 'roadsPathSurface', source: 'roadsPathClasses' },
] as const

const queryClient = new QueryClient()

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
  const [layers, setLayers] = useState<Array<(typeof categories)[number]>>([])
  const [sourceLayerMap, setSourceLayerMap] = useState<Record<string, string>>({})
  const [mapLoaded, setMapLoaded] = useState(false)
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
        // Only use the fixed layers that have their source present in the catalog
        const available = Object.keys(catalog.tiles)
        setLayers(categories.filter((layer) => available.includes(layer.source)))
      } catch (error) {
        console.error('Error fetching layers:', error)
      }
    }
    fetchLayers()
  }, [source])

  const toggleLayer = (layer: (typeof categories)[number]) => {
    setActiveLayers((prev) =>
      prev.includes(layer.id) ? prev.filter((l) => l !== layer.id) : [...prev, layer.id],
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

  useEffect(() => {
    const protocol = new Protocol()
    maplibregl.addProtocol('pmtiles', protocol.tile)
    return () => {
      maplibregl.removeProtocol('pmtiles')
    }
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
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
                            href={`${TILE_URLS[source as keyof typeof TILE_URLS]}/catalog`}
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
                <h2 className="mb-2 font-bold">Layers</h2>
                <ul>
                  {layers.map((layer) => (
                    <li key={layer.id}>
                      <div className="flex items-center justify-between">
                        <label className="flex w-full items-center gap-2">
                          <input
                            type="checkbox"
                            checked={activeLayers.includes(layer.id)}
                            onChange={() => toggleLayer(layer)}
                          />
                          {layer.id}

                          {activeLayers.includes(layer.id) && (
                            <a
                              href={`${TILE_URLS[source as keyof typeof TILE_URLS]}/${layer.source}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[0.5rem] whitespace-nowrap text-blue-500 hover:underline"
                            >
                              Tile JSON
                            </a>
                          )}
                        </label>
                      </div>
                      {activeLayers.includes(layer.id) &&
                        LAYER_LEGENDS[layer.id as keyof typeof LAYER_LEGENDS] && (
                          <Legend legend={LAYER_LEGENDS[layer.id as keyof typeof LAYER_LEGENDS]} />
                        )}
                    </li>
                  ))}
                </ul>
                <div className="mt-2">
                  <TildaUpdateInfo />
                </div>
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
              interactiveLayerIds={[
                'roads-interaction',
                'roadsPathClasses-interaction',
                'bikelanes-interaction',
              ]}
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
              <AddMapImage
                name={arrowImageId}
                url="/map-style-line-direction-arrow.png"
                sdf={true}
              />
              <NavigationControl position="bottom-right" />
              <BackgroundLayer />

              {/* Group sources by unique source names to avoid duplicate sources */}
              {Array.from(new Set(layers.map((l) => l.source))).map((sourceId) => (
                <Source
                  key={sourceId}
                  id={sourceId}
                  type="vector"
                  url={`${TILE_URLS[source as keyof typeof TILE_URLS]}/${sourceId}`}
                  promoteId="id"
                />
              ))}

              {mapLoaded && (
                <Fragment>
                  {layers
                    .filter((layer) => activeLayers.includes(layer.id))
                    .map((layer) => {
                      const sourceLayer = sourceLayerMap[layer.source]
                      if (!sourceLayer) return null

                      switch (layer.id) {
                        case 'roads':
                          return <RoadLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsAge':
                          return <RoadAgeLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsPath':
                          return <RoadPathLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsPathAge':
                          return <RoadPathAgeLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'bikelanes':
                          return <BikeLaneLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'bikelanesAge':
                          return <BikeLaneAgeLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'bikelanesWidth':
                          return <BikelaneWidthLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'bikelanSurfaceColor':
                          return (
                            <BikelaneSurfaceColorLayer key={layer.id} sourceLayer={sourceLayer} />
                          )
                        case 'roadsOneway':
                          return <RoadOnewayLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsPathOneway':
                          return <RoadPathOnewayLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'bikelanesOneway':
                          return <BikeLaneOnewayLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsSurface':
                          return <RoadSurfaceSettLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsPathSurface':
                          return (
                            <RoadPathSurfaceSettLayer key={layer.id} sourceLayer={sourceLayer} />
                          )
                        case 'bikelanesSurface':
                          return (
                            <BikeLaneSurfaceSettLayer key={layer.id} sourceLayer={sourceLayer} />
                          )
                        case 'bikelanesTrafficSign':
                          return (
                            <BikeLaneTrafficSignLayer key={layer.id} sourceLayer={sourceLayer} />
                          )
                        case 'bikelanesMapillary':
                          return <BikeLaneMapillaryLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadsCyclewayNo':
                          return <RoadCyclewayNoLayer key={layer.id} sourceLayer={sourceLayer} />
                        case 'roadDualCarriageway':
                          return (
                            <RoadDualCarriagewayLayer key={layer.id} sourceLayer={sourceLayer} />
                          )
                      }
                    })}

                  {layers
                    .filter((layer) => activeLayers.includes(layer.id))
                    .map((layer) => {
                      const sourceLayer = sourceLayerMap[layer.source]
                      if (!sourceLayer) return null

                      // Interaction layer (hover/selected states)
                      switch (sourceLayer) {
                        case 'roads':
                          return (
                            <Layer
                              id="roads-interaction"
                              type="line"
                              source="roads"
                              paint={{
                                'line-color': getInteractionLineColor,
                                'line-width': getInteractionLineWidth,
                                'line-opacity': 0.5,
                              }}
                              source-layer={sourceLayer}
                            />
                          )
                        case 'roadsPathClasses':
                          return (
                            <Layer
                              id="roadsPathClasses-interaction"
                              type="line"
                              source="roadsPathClasses"
                              paint={{
                                'line-color': getInteractionLineColor,
                                'line-width': getInteractionLineWidth,
                                'line-opacity': 0.5,
                              }}
                              source-layer={sourceLayer}
                            />
                          )
                        case 'bikelanes':
                          return (
                            <Layer
                              id="bikelanes-interaction"
                              type="line"
                              source="bikelanes"
                              paint={{
                                'line-color': getInteractionLineColor,
                                'line-width': getInteractionLineWidth,
                                'line-opacity': 0.5,
                              }}
                              source-layer={sourceLayer}
                            />
                          )
                      }
                    })}
                </Fragment>
              )}
              <StaticLayers />
            </Map>
          </div>

          {/* Sidebar Panel */}
          <Inspector
            inspectorFeatures={inspectorFeatures}
            activeLayerConfigs={layers.filter((layer) => activeLayers.includes(layer.id))}
          />
        </main>
      </MapProvider>
    </QueryClientProvider>
  )
}

export default App
