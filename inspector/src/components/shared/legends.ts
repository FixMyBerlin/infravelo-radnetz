import { getAgeLegend } from './ageBasedStyle'
import { getCategoryLegend } from './categoryStyle'
import { getCyclewayNoLayerLegend } from './cyclewayNoStyle'
import { getDualCarrigewayLegend } from './dualCarrigewayStyle'
import { getMapillaryLegend } from './mapillaryStyle'
import { getBikeLaneOnewayLegend, getRoadOnewayLegend } from './onewayBasedStyle'
import { getSurfaceColorLegend } from './surfaceColorStyle'
import { getSurfaceSettLegend } from './surfaceSettStyle'
import { getTrafficSignLegend } from './trafficSignStyle'
import { getWidthLegend } from './widthStyle'

export const LAYER_LEGENDS = {
  bikelanesAge: getAgeLegend(),
  bikelanesCategory: getCategoryLegend(),
  bikelanesOneway: getBikeLaneOnewayLegend(),
  bikelanesSurface: getSurfaceSettLegend(),
  bikelanesSurfaceColor: getSurfaceColorLegend(),
  bikelanesWidth: getWidthLegend(),
  bikelanesTrafficSign: getTrafficSignLegend(),
  bikelanesMapillary: getMapillaryLegend(),
  roadsAge: getAgeLegend(),
  roadsOneway: getRoadOnewayLegend(),
  roadsSurface: getSurfaceSettLegend(),
  roadsCyclewayNo: getCyclewayNoLayerLegend(),
  roadDualCarriageway: getDualCarrigewayLegend(),
  roadsPathAge: getAgeLegend(),
  roadsPathOneway: getBikeLaneOnewayLegend(),
  roadsPathSurface: getSurfaceSettLegend(),
}
