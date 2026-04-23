// SelectionContext.jsx
// Global context shared by all plots and the RepairPanel.
//
// highlightedRowIds  – row IDs currently lit up across all charts (null = nothing)
// highlightedCols    – the column name(s) involved in the selection (for imputation)
//                      [colX] for histogram, [colX, colY] for heatmap/scatterplot

import { createContext, useContext, useState, useCallback } from "react";

export const SelectionContext = createContext(null);

/**
 * Shape of selectionMeta (kept for RepairPanel back-compat):
 * {
 *   table:    string
 *   viewType: "heatmap" | "barchart" | "scatterplot"
 *   cols:     string[]
 *   data:     object[]
 *   scaleX:   object
 *   scaleY:   object | null
 * }
 */
export function SelectionProvider({ children }) {
  const [selection, setSelectionState] = useState(null);
  const [highlightedRowIds, setHighlightedRowIdsState] = useState(null);
  const [highlightedCols, setHighlightedColsState] = useState(null);
  const [selectionSource, setSelectionSourceState] = useState(null);
  const [highlightRevision, setHighlightRevision] = useState(0);

  const setSelection = useCallback((meta) => {
    setSelectionState(meta);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectionState(null);
  }, []);

  /**
   * Set the cross-chart highlight.
   * @param {number[]} ids    – row IDs to highlight (pass null/[] to clear)
   * @param {string[]} cols   – columns involved (for preview / imputation)
   * @param {string|null} source – "histogram" | "heatmap" | "scatterplot" | null
   */
  const setHighlightedRowIds = useCallback((ids, cols, source = null) => {
    setHighlightedRowIdsState(ids && ids.length > 0 ? ids : null);
    setHighlightedColsState(cols && cols.length > 0 ? cols : null);
    setSelectionSourceState(source);
    setHighlightRevision(rev => rev + 1);
  }, []);

  const clearHighlight = useCallback(() => {
    setHighlightedRowIdsState(null);
    setHighlightedColsState(null);
    setSelectionSourceState(null);
    setHighlightRevision(rev => rev + 1);
  }, []);

  return (
    <SelectionContext.Provider value={{
      selection, setSelection, clearSelection,
      highlightedRowIds, highlightedCols,
      selectionSource, highlightRevision,
      setHighlightedRowIds, clearHighlight,
    }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  return useContext(SelectionContext);
}
