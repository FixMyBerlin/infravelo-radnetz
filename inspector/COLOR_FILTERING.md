# Color Filtering Feature

## Overview

This feature allows users to toggle individual colors/categories within each layer, making it easier to focus on specific data characteristics.

## Implementation Strategy

The implementation uses a **filter-based approach** with the following components:

### 1. **Color Filter State Management** (`useColorFilters` hook)
- Stores active color filters in URL query parameters for shareability
- Manages toggle state for each color in each layer
- Returns helper functions to check if colors are active

### 2. **Layer Filter Hook** (`useLayerFilter`)
- Converts active color selections into MapLibre filter expressions
- Integrates with layer legends to determine which features to show/hide
- Returns null when no filtering is active (shows all features)

### 3. **Interactive Legends**
- Legend items are now clickable buttons
- Visual feedback: inactive colors are shown with reduced opacity
- Each legend item can have a `filterExpression` property

### 4. **Filter Expression Generation** (`colorFilterUtils`)
- Creates MapLibre-compatible filter expressions from legend items
- Combines multiple active filters with OR logic (`any` operator)
- Returns null when all items are active (optimization)

## How It Works

1. **User clicks a color in the legend** → `toggleColor()` is called
2. **Color filter state is updated** → stored in URL query params
3. **Layer re-renders** → `useLayerFilter()` generates new filter expression
4. **MapLibre filters features** → only matching features are displayed

## Extending to New Layers

To add color filtering to a new layer:

1. **Add `filterExpression` to legend items** in the corresponding style file:
   ```typescript
   export const getMyLegend = (): LayerLegend => ({
     items: [
       {
         color: '#FF0000',
         label: 'Red items',
         filterExpression: ['==', ['get', 'category'], 'red'],
       },
       // ... more items
     ],
   })
   ```

2. **Use the filter hook in the layer component**:
   ```typescript
   import { useLayerFilter } from '../hooks/useLayerFilter'

   export const MyLayer = ({ sourceLayer }: Props) => {
     const filter = useLayerFilter('myLayerId')

     return (
       <Layer
         // ... other props
         filter={filter ?? undefined}
       />
     )
   }
   ```

3. **Pass layerId to Legend component** in App.tsx:
   ```typescript
   <Legend legend={LAYER_LEGENDS[layer.id]} layerId={layer.id} />
   ```

## Benefits

- ✅ **Minimal code changes** - only requires filter expressions in legends
- ✅ **No layer duplication** - uses MapLibre's native filtering
- ✅ **Shareable state** - filters are stored in URL
- ✅ **Performant** - leverages MapLibre's optimized filtering
- ✅ **Modular** - easy to extend to new layers

## Currently Supported Layers

### Bike Lanes (Radinfrastruktur)
- ✅ **Category** (Führungsform) - Filter by clarification status
- ✅ **Buffer/Marking** (Puffer und Markierung) - Filter by configuration correctness
- ✅ **Age** (Alter der Daten) - Filter by update date
- ✅ **Surface (Sett)** (Oberfläche) - Filter by surface type
- ✅ **Oneway** (Einbahnstraße) - Filter by one-way status
- ✅ **Traffic Sign** (Verkehrszeichen) - Filter by traffic sign presence and status
- ✅ **Mapillary** - Filter by Mapillary reference availability
- ✅ **Update Source** (Letzte Bearbeitung) - Filter by update source (FMC vs others)

### Roads (Straßen)
- ✅ **Age** (Alter der Daten) - Filter by update date
- ✅ **Surface (Sett)** (Oberfläche) - Filter by surface type
- ✅ **Oneway** (Einbahnstraße) - Filter by one-way and bicycle rules
- ✅ **Update Source** (Letzte Bearbeitung) - Filter by update source (FMC vs others)

### Road Paths (Wege)
- ✅ **Age** (Alter der Daten) - Filter by update date
- ✅ **Surface (Sett)** (Oberfläche) - Filter by surface type
- ✅ **Oneway** (Einbahnstraße) - Filter by one-way status
- ✅ **Update Source** (Letzte Bearbeitung) - Filter by update source (FMC vs others)

### Not Yet Implemented
The following layers have legends but no filter expressions yet:
- ⏳ Width (Breite)
- ⏳ Surface Color (Oberflächenfarbe)
- ⏳ Cycleway No
- ⏳ Dual Carriageway

Additional layers can be extended following the pattern described above.
