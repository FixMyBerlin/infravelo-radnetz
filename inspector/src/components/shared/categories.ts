export type CategoryId = (typeof categories)[number]['id']

export const QA_CATEGORY = {
  BIKELANES: 'QA Radinfrastruktur',
  ROADS: 'QA Straßen',
  PATHS: 'QA Wege',
} as const

export type LayerCategory = (typeof QA_CATEGORY)[keyof typeof QA_CATEGORY]

export const categories = [
  // Bike lanes and their variants
  {
    id: 'bikelanes',
    source: 'bikelanes',
    title: 'Alle Radwege',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesCategory',
    source: 'bikelanes',
    inspectorHighlightTags: ['category'],
    title: 'Führungsform',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesBufferMarking',
    source: 'bikelanes',
    inspectorHighlightTags: [
      'category',
      'buffer_right',
      'buffer_left',
      'buffer_both',
      'marking_right',
      'marking_left',
      'marking_both',
      'separation_right',
      'separation_left',
      'separation_both',
    ],
    title: 'Puffer und Markierung',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesAge',
    source: 'bikelanes',
    inspectorHighlightTags: ['updated_at'],
    title: 'Alter der Daten',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesOneway',
    source: 'bikelanes',
    inspectorHighlightTags: ['oneway', 'oneway_bike'],
    title: 'Einbahnstraßen',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesSurface',
    source: 'bikelanes',
    inspectorHighlightTags: ['surface'],
    title: 'Oberfläche',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesWidth',
    source: 'bikelanes',
    inspectorHighlightTags: ['width', 'width_source', 'category'],
    title: 'Breite',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesSurfaceColor',
    source: 'bikelanes',
    inspectorHighlightTags: ['surface_color'],
    title: 'Farbige Markierung',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesTrafficSign',
    source: 'bikelanes',
    inspectorHighlightTags: ['traffic_sign'],
    title: 'Verkehrszeichen',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesMapillary',
    source: 'bikelanes',
    inspectorHighlightTags: [
      'mapillary',
      'mapillary_left',
      'mapillary_right',
      'mapillary_traffic_sign',
      'traffic_sign',
    ],
    title: 'Mapillary Fotos',
    category: QA_CATEGORY.BIKELANES,
  },
  {
    id: 'bikelanesUpdateSource',
    source: 'bikelanes',
    inspectorHighlightTags: ['updated_at', 'updated_by'],
    title: 'Letzte Bearbeitung',
    category: QA_CATEGORY.BIKELANES,
  },

  // Roads and their variants
  {
    id: 'roads',
    source: 'roads',
    title: 'Alle Straßen',
    category: QA_CATEGORY.ROADS,
  },
  {
    id: 'roadsAge',
    source: 'roads',
    title: 'Alter der Daten',
    category: QA_CATEGORY.ROADS,
  },
  {
    id: 'roadsOneway',
    source: 'roads',
    title: 'Einbahnstraßen',
    category: QA_CATEGORY.ROADS,
  },
  {
    id: 'roadsSurface',
    source: 'roads',
    title: 'Oberfläche',
    category: QA_CATEGORY.ROADS,
  },
  {
    id: 'roadsCyclewayNo',
    source: 'roads',
    title: 'Keine Radverkehrsanlagen',
    category: QA_CATEGORY.ROADS,
  },
  {
    id: 'roadDualCarriageway',
    source: 'roads',
    title: 'Getrennte Fahrbahnen',
    category: QA_CATEGORY.ROADS,
  },
  {
    id: 'roadsUpdateSource',
    source: 'roads',
    inspectorHighlightTags: ['updated_at', 'updated_by'],
    title: 'Letzte Bearbeitung',
    category: QA_CATEGORY.ROADS,
  },

  // Road paths and their variants
  {
    id: 'roadsPath',
    source: 'roadsPathClasses',
    title: 'Alle Wege',
    category: QA_CATEGORY.PATHS,
  },
  {
    id: 'roadsPathAge',
    source: 'roadsPathClasses',
    title: 'Alter der Daten',
    category: QA_CATEGORY.PATHS,
  },
  {
    id: 'roadsPathOneway',
    source: 'roadsPathClasses',
    title: 'Einbahnwege',
    category: QA_CATEGORY.PATHS,
  },
  {
    id: 'roadsPathSurface',
    source: 'roadsPathClasses',
    title: 'Oberfläche',
    category: QA_CATEGORY.PATHS,
  },
  {
    id: 'roadsPathsUpdateSource',
    source: 'roadsPathClasses',
    inspectorHighlightTags: ['updated_at', 'updated_by'],
    title: 'Letzte Bearbeitung',
    category: QA_CATEGORY.PATHS,
  },
] as const
