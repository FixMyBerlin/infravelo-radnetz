import { getAgeLegend } from './ageBasedStyle'
import { getBufferMarkingLegend } from './bufferMarkingStyle'
import type { CategoryId } from './categories'
import { getCategoryLegend } from './categoryStyle'
import { getCyclewayNoLayerLegend } from './cyclewayNoStyle'
import { getDualCarrigewayLegend } from './dualCarrigewayStyle'
import { getMapillaryLegend } from './mapillaryStyle'
import { getBikeLaneOnewayLegend, getRoadOnewayLegend } from './onewayBasedStyle'
import { getSurfaceColorLegend } from './surfaceColorStyle'
import { getSurfaceSettLegend } from './surfaceSettStyle'
import { getTrafficSignLegend } from './trafficSignStyle'
import type { LayerLegend } from './types'
import { getUpdateSourceLegend } from './updateSourceStyle'
import { getWidthLegend } from './widthStyle'

export const getOsmUpdateContextLegend = (): LayerLegend => ({
  items: [
    { color: '#800080', label: 'Nach TILDA-Datenstand aktualisiert' },
    { color: '#4169E1', label: 'Vor TILDA-Datenstand / unverändert' },
    { color: '#808080', label: 'Daten nicht verfügbar' },
  ],
})

export const LAYER_LEGENDS: Record<CategoryId, LayerLegend | null> = {
  // Bike lanes and their variants
  bikelanes: null,
  bikelanesAge: getAgeLegend(),
  bikelanesBufferMarking: getBufferMarkingLegend(),
  bikelanesCategory: getCategoryLegend(),
  bikelanesOneway: getBikeLaneOnewayLegend(),
  bikelanesSurface: getSurfaceSettLegend(),
  bikelanesSurfaceColor: getSurfaceColorLegend(),
  bikelanesWidth: getWidthLegend(),
  bikelanesTrafficSign: getTrafficSignLegend(),
  bikelanesMapillary: getMapillaryLegend(),
  bikelanesUpdateSource: getUpdateSourceLegend(),

  // Roads and their variants
  roads: null,
  roadsAge: getAgeLegend(),
  roadsOneway: getRoadOnewayLegend(),
  roadsSurface: getSurfaceSettLegend(),
  roadsCyclewayNo: getCyclewayNoLayerLegend(),
  roadDualCarriageway: getDualCarrigewayLegend(),
  roadsUpdateSource: getUpdateSourceLegend(),

  // Road paths and their variants
  roadsPath: null,
  roadsPathAge: getAgeLegend(),
  roadsPathOneway: getBikeLaneOnewayLegend(),
  roadsPathSurface: getSurfaceSettLegend(),
  roadsPathsUpdateSource: getUpdateSourceLegend(),
}
