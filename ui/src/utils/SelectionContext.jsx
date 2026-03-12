// SelectionContext.jsx
// Global context that carries whatever the user last clicked in any plot.
// Also manages the active FilteringSQL indices on the backend so that all
// plots re-fetch scoped to the correct rows.

import { createContext, useContext, useState, useCallback } from "react";

export const SelectionContext = createContext(null);

/**
 * Shape of selection state:
 * {
 *   table:         string          — DB table name
 *   viewType:      "heatmap" | "barchart" | "scatterplot"
 *   cols:          string[]        — [xCol] for barchart, [xCol, yCol] for heatmap/scatter
 *   data:          object[]        — raw bin/point objects from the plot
 *   scaleX:        object          — histogram scaleX descriptor
 *   scaleY:        object | null   — histogram scaleY descriptor (null for barchart)
 *   filterIndices: number[]        — backend FilteringSQL indices for this selection
 * }
 *
 * filterVersion increments every time the active filter changes.
 * Plots include it in their useEffect deps so they re-fetch automatically.
 */
export function SelectionProvider({ children }) {
  const [selection, setSelectionState] = useState(null);
  const [filterVersion, setFilterVersion] = useState(0);

  /**
   * Called by a plot when the user clicks/brushes a bin or point.
   * Sends the selection to the backend to register a SQL filter,
   * then stores the returned filterIndices so clearFilters can clean them up.
   */
  const addFilter = useCallback(async (meta) => {
    // Optimistic update — show selection immediately
    setSelectionState({ ...meta, filterIndices: [] });

    try {
      const response = await fetch("/api/filter/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ table: meta.table, selection: meta }),
      });
      const result = await response.json();

      if (result.success) {
        setSelectionState(prev => prev
          ? { ...prev, filterIndices: result.filterIndices }
          : null
        );
        setFilterVersion(v => v + 1);
      } else {
        console.error("[SelectionContext] filter/add failed:", result.error);
      }
    } catch (err) {
      console.error("[SelectionContext] filter/add error:", err);
    }
  }, []);

  /**
   * Clears all active filters on the backend and wipes local selection.
   * Passing specific indices clears only those; passing nothing clears all.
   */
  const clearFilters = useCallback(async (indices = []) => {
    setSelectionState(null);

    try {
      const response = await fetch("/api/filter/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filterIndices: indices }),
      });
      const result = await response.json();

      if (result.success) {
        setFilterVersion(v => v + 1);
      } else {
        console.error("[SelectionContext] filter/clear failed:", result.error);
      }
    } catch (err) {
      console.error("[SelectionContext] filter/clear error:", err);
    }
  }, []);

  return (
    <SelectionContext.Provider value={{ selection, filterVersion, addFilter, clearFilters }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  return useContext(SelectionContext);
}
