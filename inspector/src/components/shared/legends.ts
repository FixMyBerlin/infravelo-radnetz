import { getAgeLegend } from './ageBasedStyle'
import { getCyclewayNoLayerLegend } from './cyclewayNoStyle'
import { getDualCarrigewayLegend } from './dualCarrigewayStyle'
import { getBikeLaneOnewayLegend, getRoadOnewayLegend } from './onewayBasedStyle'
import { getSurfaceSettLegend } from './surfaceSettStyle'
import { getSurfaceColorLegend } from './surfaceColorStyle'
import { getTrafficSignLegend } from './trafficSignStyle'

export const LAYER_LEGENDS = {
  bikelanesAge: getAgeLegend(),
  bikelanesOneway: getBikeLaneOnewayLegend(),
  bikelanesSurface: getSurfaceSettLegend(),
  bikelanesSurfaceColor: getSurfaceColorLegend(),
  bikelanesTrafficSign: getTrafficSignLegend(),
  roadsAge: getAgeLegend(),
  roadsOneway: getRoadOnewayLegend(),
  roadsSurface: getSurfaceSettLegend(),
  roadsCyclewayNo: getCyclewayNoLayerLegend(),
  roadDualCarriageway: getDualCarrigewayLegend(),
  roadsPathAge: getAgeLegend(),
  roadsPathOneway: getBikeLaneOnewayLegend(),
  roadsPathSurface: getSurfaceSettLegend(),
}
