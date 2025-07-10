import { Legend } from './Legend'
import { type LayerLegend } from './shared/types'

type Props = {
  activeCategories: string[]
  legends: { [key: string]: LayerLegend }
}

export const LayerLegends = ({ activeCategories, legends }: Props) => {
  return (
    <div className="absolute bottom-4 left-4 z-10 space-y-2">
      {activeCategories.map((category) => {
        const legend = legends[category]
        if (!legend) return null
        return <Legend key={category} legend={legend} />
      })}
    </div>
  )
}
