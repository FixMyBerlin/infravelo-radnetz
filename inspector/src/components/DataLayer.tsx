import { parseAsArrayOf, parseAsString, useQueryState } from 'nuqs'
import { Fragment, useState } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import { staticLayerDefs } from './staticLayerDefs'

export const DataLayer = () => {
  // Active layers state in URL
  const [activeDataLayers, setActiveDataLayers] = useQueryState(
    'data',
    parseAsArrayOf(parseAsString).withDefault([]),
  )
  // Color state per layer, local only
  const [colors, setColors] = useState(() => {
    const initial: Record<string, string> = {}
    staticLayerDefs.forEach((l) => {
      initial[l.id] = l.defaultColor
    })
    return initial
  })
  const setColor = (id: string, color: string) => {
    setColors((prev) => ({ ...prev, [id]: color }))
  }

  const renderLayers = staticLayerDefs.filter((l) => activeDataLayers.includes(l.id))

  return (
    <Fragment>
      {newFunction(activeDataLayers, setActiveDataLayers, colors, setColor)}
      {renderLayers.map((layer) => {
        return (
          <Fragment key={layer.id}>
            <Source id={layer.id} type="vector" url={layer.url} />
            {layer.type === 'line' ? (
              <Layer
                id={`${layer.id}-layer`}
                type="line"
                source={layer.id}
                source-layer="default"
                paint={{
                  'line-color': colors[layer.id],
                  'line-width': 2,
                }}
              />
            ) : (
              <Layer
                id={`${layer.id}-layer`}
                type="fill"
                source={layer.id}
                source-layer="default"
                paint={{
                  'fill-color': colors[layer.id],
                  'fill-opacity': 0.3,
                }}
              />
            )}
          </Fragment>
        )
      })}
    </Fragment>
  )
}
function newFunction(activeDataLayers: string[], setActiveDataLayers, colors: Record<string, string>, setColor: (id: string, color: string) => void) {
  return <nav className="absolute top-1/2 left-4 z-40 flex -translate-y-1/2 flex-col gap-2 rounded bg-white/80 p-2 shadow">
    {staticLayerDefs.map((layer) => (
      <div key={layer.id} className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={activeDataLayers.includes(layer.id)}
          onChange={() => setActiveDataLayers(
            activeDataLayers.includes(layer.id)
              ? activeDataLayers.filter((l) => l !== layer.id)
              : [...activeDataLayers, layer.id]
          )} />
        <span className="font-mono text-xs">{layer.id}</span>
        <input
          type="color"
          value={colors[layer.id]}
          onChange={(e) => setColor(layer.id, e.target.value)}
          className="size-5 rounded"
          title="Layer color" />
      </div>
    ))}
  </nav>
}
