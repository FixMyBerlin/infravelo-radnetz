import { getAgeLegend } from './ageBasedStyle'
import { getCyclewayNoLayerLegend } from './cyclewayNoStyle'
import { getBikeLaneOnewayLegend, getRoadOnewayLegend } from './onewayBasedStyle'
import { getSurfaceSettLegend } from './surfaceSettStyle'

export const LAYER_LEGENDS = {
  bikelanesAge: getAgeLegend(),
  bikelanesOneway: getBikeLaneOnewayLegend(),
  bikelanesSurface: getSurfaceSettLegend(),
  roadsAge: getAgeLegend(),
  roadsOneway: getRoadOnewayLegend(),
  roadsSurface: getSurfaceSettLegend(),
  roadsCyclewayNo: getCyclewayNoLayerLegend(),
  roadsPathAge: getAgeLegend(),
  roadsPathOneway: getBikeLaneOnewayLegend(),
  roadsPathSurface: getSurfaceSettLegend(),
}
