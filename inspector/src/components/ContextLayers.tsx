import { Fragment } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import { useContextLayers } from '../hooks/useContextLayers'
import { MapillaryAllLayers, MapillaryFMCLayers } from './MapillaryLayers'
import { OsmUpdateContextControls } from './OsmUpdateContextControls'
import { OsmUpdateContextLayers } from './OsmUpdateContextLayers'

export const ContextLayerControls = () => {
  const { contextLayers, toggle } = useContextLayers()

  return (
    <section className="mt-6">
      <h2 className="mb-2 font-bold">Kontext-Layer</h2>
      <ul className="space-y-2">
        <li>
          <label className="flex w-full items-center gap-2">
            <input
              type="checkbox"
              checked={contextLayers.includes('vorrangnetz')}
              onChange={() => toggle('vorrangnetz')}
            />
            Vorrangnetz (Maske)
          </label>
        </li>
        <li>
          <label className="flex w-full items-center gap-2">
            <input
              type="checkbox"
              checked={contextLayers.includes('bezirke')}
              onChange={() => toggle('bezirke')}
            />
            Bezirksgrenzen
          </label>
        </li>
        <li>
          <label className="flex w-full items-center gap-2">
            <input
              type="checkbox"
              checked={contextLayers.includes('ortsteile')}
              onChange={() => toggle('ortsteile')}
            />
            Ortsteil-Grenzen
          </label>
        </li>
        <li>
          <label className="flex w-full items-center gap-2">
            <input
              type="checkbox"
              checked={contextLayers.includes('mapillary')}
              onChange={() => toggle('mapillary')}
            />
            Mapillary (Alles)
          </label>
        </li>
        <li>
          <label className="flex w-full items-center gap-2">
            <input
              type="checkbox"
              checked={contextLayers.includes('mapillary_fmc')}
              onChange={() => toggle('mapillary_fmc')}
            />
            Mapillary FMC Befahrung
          </label>
        </li>
        <OsmUpdateContextControls />
      </ul>
    </section>
  )
}

export const ContextMapLayers = ({ activeLayers }: { activeLayers: string[] }) => {
  const { contextLayers } = useContextLayers()

  return (
    <Fragment>
      {/* Marker layer to ensure context layers are on top and to allow beforeId references */}
      <Layer id="static-layers-start" type="background" paint={{ 'background-opacity': 0 }} />

      {/* Marker layer to position Vorrangnetz below Bezirke */}
      <Layer id="bezirke-layers-start" type="background" paint={{ 'background-opacity': 0 }} />

      {/* Vorrangnetz (mask) - always positioned before bezirke-layers-start */}
      {contextLayers.includes('vorrangnetz') && (
        <Fragment>
          <Source
            id="vorrangnetz-mask"
            type="vector"
            url="pmtiles://https://tilda-geo.de/api/uploads/radverkehrsnetz-vorrangnetz-mask"
          />
          <Layer
            id="vorrangnetz-mask-border"
            type="line"
            source="vorrangnetz-mask"
            source-layer="default"
            filter={['==', '$type', 'Polygon']}
            paint={{
              'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, 1],
              'line-color': '#27272a',
              'line-opacity': 0.8,
              'line-offset': ['interpolate', ['linear'], ['zoom'], 0, 0, 12.5, 0, 13, -0.5],
            }}
            beforeId="bezirke-layers-start"
          />
          <Layer
            id="vorrangnetz-mask-fill"
            type="fill"
            source="vorrangnetz-mask"
            source-layer="default"
            filter={['==', '$type', 'Polygon']}
            paint={{
              'fill-color': '#27272a',
              'fill-opacity': ['interpolate', ['linear'], ['zoom'], 0, 0.99, 13.5, 0.95, 14, 0.7],
            }}
            beforeId="bezirke-layers-start"
          />
        </Fragment>
      )}

      {/* Bezirke */}
      {contextLayers.includes('bezirke') && (
        <Fragment>
          <Source
            id="context-bezirke"
            type="vector"
            url="pmtiles://https://tilda-geo.de/api/uploads/berlin-bezirke"
          />
          <Layer
            id="context-bezirke-border"
            type="line"
            source="context-bezirke"
            filter={['==', '$type', 'Polygon']}
            paint={{
              'line-width': 6,
              'line-color': '#fbbf24',
              'line-opacity': 0.9,
              'line-offset': -3,
            }}
            source-layer="default"
          />
          <Layer
            id="context-bezirke-label"
            type="symbol"
            source="context-bezirke"
            paint={{
              'text-color': '#fffbeb',
              'text-halo-color': '#fbbf24',
              'text-halo-width': 3,
              'text-opacity': 1,
            }}
            layout={{
              'text-line-height': 1.1,
              'text-size': 14,
              'text-radial-offset': 0,
              'text-allow-overlap': true,
              'symbol-avoid-edges': true,
              'text-ignore-placement': true,
              'symbol-placement': 'line',
              'text-justify': 'auto',
              'text-padding': 0,
              'text-offset': [0, 0.7],
              'text-field': ['concat', ['to-string', ['get', 'Gemeinde_name']]],
            }}
            source-layer="default"
          />
        </Fragment>
      )}

      {/* Ortsteile */}
      {contextLayers.includes('ortsteile') && (
        <Fragment>
          <Source
            id="context-ortsteile"
            type="vector"
            url="pmtiles://https://tilda-geo.de/api/uploads/berlin-bezirke-ortsteile"
          />
          <Layer
            id="context-ortsteile-border"
            type="line"
            source="context-ortsteile"
            filter={['==', '$type', 'Polygon']}
            paint={{
              'line-width': 6,
              'line-color': '#fbbf24',
              'line-opacity': 0.9,
              'line-offset': -3,
            }}
            source-layer="default"
            beforeId={
              contextLayers.includes('vorrangnetz')
                ? 'vorrangnetz-mask-fill'
                : 'static-layers-start'
            }
          />
          <Layer
            id="context-ortsteile-label"
            type="symbol"
            source="context-ortsteile"
            paint={{
              'text-color': '#fffbeb',
              'text-halo-color': '#fbbf24',
              'text-halo-width': 3,
              'text-opacity': 1,
            }}
            layout={{
              'text-line-height': 1.1,
              'text-size': 14,
              'text-radial-offset': 0,
              'text-allow-overlap': true,
              'symbol-avoid-edges': true,
              'text-ignore-placement': true,
              'symbol-placement': 'line',
              'text-justify': 'auto',
              'text-padding': 0,
              'text-offset': [0, 0.7],
              'text-field': ['concat', ['to-string', ['get', 'OTEIL']]],
            }}
            source-layer="default"
            beforeId={
              contextLayers.includes('vorrangnetz')
                ? 'vorrangnetz-mask-fill'
                : 'static-layers-start'
            }
          />
        </Fragment>
      )}

      {/* Mapillary (Alles) */}
      {contextLayers.includes('mapillary') && <MapillaryAllLayers />}

      {/* Mapillary FMC Befahrung */}
      {contextLayers.includes('mapillary_fmc') && <MapillaryFMCLayers />}

      {/* OSM Update Status Context Layer */}
      <OsmUpdateContextLayers activeLayers={activeLayers} />
    </Fragment>
  )
}
