import { parseAsStringLiteral, useQueryState } from 'nuqs'
import { Layer, Source } from 'react-map-gl/maplibre'

const backgroundMaps = [
  {
    id: 'none',
    name: 'Basemap (MapTiler)',
    tiles: '',
    tileSize: 256,
    maxzoom: null,
    minzoom: null,
    attributionHtml: '',
  },
  {
    id: 'areal2025',
    name: 'Berlin: Luftbilder 2025',
    tiles: 'https://tiles.codefor.de/berlin/geoportal/luftbilder/2025-dop20rgb/{z}/{x}/{y}.png',
    tileSize: 256,
    maxzoom: 21,
    minzoom: 10,
    attributionHtml: '',
  },
  {
    id: 'areal2024',
    name: 'Berlin: Luftbilder 2024',
    tiles: 'https://tiles.codefor.de/berlin-2024-dop20rgbi/{z}/{x}/{y}.png',
    tileSize: 256,
    maxzoom: 21,
    minzoom: 10,
    attributionHtml: '',
  },
  {
    id: 'strassenbefahrung',
    name: 'Berlin: Straßenbefahrung 2014',
    tiles: 'https://mapproxy.codefor.de/tiles/1.0.0/strassenbefahrung/mercator/{z}/{x}/{y}.png',
    tileSize: 256,
    maxzoom: 21,
    minzoom: 10,
    attributionHtml:
      '<a target="_blank" href="https://fbinter.stadt-berlin.de/fb/berlin/service_intern.jsp?id=k_StraDa@senstadt&type=WMS">Geoportal Berlin Straßenbefahrung 2014</a>',
  },
  {
    id: 'parkraumkarte_neukoelln',
    name: 'Berlin: Parkraumkarte Neukoelln',
    tiles: 'https://tiles.osm-berlin.org/parkraumkarte/{z}/{x}/{y}.jpg',
    tileSize: 256,
    maxzoom: 20,
    minzoom: 10,
    attributionHtml: '',
  },
]

export const BackgroundLayer = () => {
  const [selectedLayer, setSelectedLayer] = useQueryState(
    'background',
    parseAsStringLiteral(backgroundMaps.map((s) => s.id)).withDefault('none'),
  )

  return (
    <>
      <div className="absolute bottom-2.5 left-2.5">
        <select
          value={selectedLayer || 'none'}
          onChange={(e) => setSelectedLayer(e.target.value)}
          className="rounded border bg-white/30 px-2 py-1 text-sm"
        >
          {backgroundMaps.map((map) => (
            <option key={map.id} value={map.id}>
              {map.name}
            </option>
          ))}
        </select>
      </div>
      <SourceLayer selectedLayer={selectedLayer} />
    </>
  )
}

const SourceLayer = ({ selectedLayer }: { selectedLayer: string }) => {
  const layer = backgroundMaps.find((map) => map.id === selectedLayer)

  if (!layer || layer.id === 'none') return null

  const { id, tiles, tileSize, maxzoom, minzoom, attributionHtml } = layer
  const backgroundId = `background-layer-${id}`
  const enhancedAttributionHtml = attributionHtml || ''

  return (
    <Source
      id={backgroundId}
      key={backgroundId}
      type="raster"
      tiles={[tiles]}
      attribution={enhancedAttributionHtml}
      {...(maxzoom ? { maxzoom } : {})}
      {...(minzoom ? { minzoom } : {})}
      {...(tileSize ? { tileSize } : {})}
    >
      <Layer id={id} type="raster" source={backgroundId} beforeId="roadname_minor" />
    </Source>
  )
}
