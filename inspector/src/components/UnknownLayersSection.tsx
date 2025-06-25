import type { Dispatch, SetStateAction } from 'react'

type Props = {
  activeLayers: string[]
  layers: string[]
  setActiveLayers: Dispatch<SetStateAction<string[]>>
}

export const UnknownLayersSection = ({ activeLayers, layers, setActiveLayers }: Props) => {
  const unknownLayers = activeLayers.filter((l) => !layers.includes(l))
  if (unknownLayers.length === 0) return null

  return (
    <details className="mt-4">
      <summary className="font-bold cursor-pointer select-none">
        Unknown layers in the URL ({unknownLayers.length})
      </summary>
      <ul className="mt-2 mb-2">
        {unknownLayers.map((unknownLayer) => (
          <li key={unknownLayer} className="flex items-center gap-2 py-1">
            <span className="truncate">{unknownLayer}</span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="text-xs text-red-600 border border-red-200 rounded px-3 py-1 hover:bg-red-50"
        onClick={() => setActiveLayers((prev) => prev.filter((l) => layers.includes(l)))}
      >
        Remove all from URL
      </button>
    </details>
  )
}
