// SelectionContext.jsx
// Global context that carries whatever the user last clicked in any plot.
// Consumed by RepairPanel to show previews and fire wrangles.

import { createContext, useContext, useState, useCallback } from "react";

export const SelectionContext = createContext(null);

/**
 * Shape of selectionMeta:
 * {
 *   table:    string          — DB table name
 *   viewType: "heatmap" | "barchart" | "scatterplot"
 *   cols:     string[]        — [xCol] for barchart, [xCol, yCol] for heatmap/scatter
 *   data:     object[]        — raw bin/point objects from the plot (the `selected` array)
 *   scaleX:   object          — histogram scaleX descriptor (for preview re-rendering)
 *   scaleY:   object | null   — histogram scaleY descriptor (null for barchart)
 * }
 */
export function SelectionProvider({ children }) {
  const [selection, setSelectionState] = useState(null);

  const setSelection = useCallback((meta) => {
    setSelectionState(meta);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectionState(null);
  }, []);

  return (
    <SelectionContext.Provider value={{ selection, setSelection, clearSelection }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  return useContext(SelectionContext);
}
