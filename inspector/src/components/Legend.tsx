import { useColorFilters } from '../hooks/useColorFilters'
import { type LayerLegend } from './shared/types'

type Props = {
  legend: LayerLegend | null
  layerId?: string
}

export const Legend = ({ legend, layerId }: Props) => {
  const { isColorActive, toggleColor } = useColorFilters()

  if (!legend) return null

  const { items } = legend
  const isInteractive = !!layerId

  return (
    <div className="mt-1 mb-3 ml-6">
      <div className="space-y-1">
        {items.map((item, i) => {
          const isActive = isInteractive ? isColorActive(layerId, item.label) : true

          if (!isInteractive) {
            // Non-interactive legend item
            return (
              <div key={i} className="flex items-center gap-2">
                <div className="flex items-center gap-2">
                  <div
                    className="h-1 w-6"
                    style={{
                      backgroundColor: item.color,
                    }}
                  />
                </div>
                <span className="text-xs text-gray-600">{item.label}</span>
              </div>
            )
          }

          // Interactive legend item
          return (
            <button
              key={i}
              className="flex w-full items-center gap-2 text-left hover:bg-gray-100 rounded px-1 py-0.5 transition-colors"
              onClick={() => toggleColor(layerId, item.label)}
              type="button"
            >
              <div className="flex items-center gap-2">
                <div
                  className="h-1 w-6 transition-opacity"
                  style={{
                    backgroundColor: item.color,
                    opacity: isActive ? 1 : 0.3,
                  }}
                />
              </div>
              <span
                className="text-xs text-gray-600 transition-opacity"
                style={{ opacity: isActive ? 1 : 0.5 }}
              >
                {item.label}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
