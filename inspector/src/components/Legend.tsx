import { type LayerLegend } from './shared/types'

type Props = {
  legend: LayerLegend | null
}

export const Legend = ({ legend }: Props) => {
  if (!legend) return null

  const { items } = legend

  return (
    <div className="mt-1 mb-3 ml-6">
      <div className="space-y-1">
        {items.map((item, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="flex items-center gap-2">
              <div
                className="h-1 w-6"
                style={{
                  backgroundColor: item.color,
                  // borderStyle:
                  //   item.pattern === 'dashed'
                  //     ? 'dashed'
                  //     : item.pattern === 'dotted'
                  //       ? 'dotted'
                  //       : 'solid',
                  // borderWidth: item.pattern ? 1 : 0,
                  // borderColor: item.pattern ? item.color : undefined,
                }}
              />
            </div>
            <span className="text-xs text-gray-600">{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
