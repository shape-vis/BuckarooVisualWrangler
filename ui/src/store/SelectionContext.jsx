// SelectionContext.jsx
// Global context shared by all plots and the RepairPanel.
//
// highlightedRowIds  – row IDs currently lit up across all charts (null = nothing)
// highlightedCols    – the column name(s) involved in the selection (for imputation)
//                      [colX] for histogram, [colX, colY] for heatmap/scatterplot

import { createContext, useContext, useState, useCallback } from "react";
import { logInteractionEvent } from "../utils/interactionLogger.jsx";

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
  const [selectionNotice, setSelectionNotice] = useState(null);

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
  const setHighlightedRowIds = useCallback((ids, cols, source = null, meta = {}) => {
    const nextIds = ids && ids.length > 0 ? ids : null;
    const nextCols = cols && cols.length > 0 ? cols : null;
    const previousIds = highlightedRowIds || [];
    const previousSet = new Set(previousIds.map(String));
    const nextSet = new Set((nextIds || []).map(String));
    const addedCount = [...nextSet].filter(id => !previousSet.has(id)).length;
    const removedCount = [...previousSet].filter(id => !nextSet.has(id)).length;

    setHighlightedRowIdsState(nextIds);
    setHighlightedColsState(nextCols);
    setSelectionSourceState(source);
    setHighlightRevision(rev => rev + 1);

    let message = "";
    if (!nextIds) {
      message = "Selection cleared";
    } else if (meta.action === "double_click_add") {
      message = "Added 1 row";
    } else if (meta.action === "double_click_remove") {
      message = "Removed 1 row";
    } else if (meta.action === "shift_brush") {
      message = addedCount > 0
        ? `Added ${addedCount} row${addedCount === 1 ? "" : "s"}`
        : `${nextIds.length} row${nextIds.length === 1 ? "" : "s"} selected`;
    } else if (meta.action === "brush") {
      message = `Selected ${nextIds.length} row${nextIds.length === 1 ? "" : "s"}`;
    } else if (addedCount > 0 || removedCount > 0) {
      message = `Selected ${nextIds.length} row${nextIds.length === 1 ? "" : "s"}`;
    }

    if (message) {
      setSelectionNotice({
        id: Date.now(),
        message,
      });
    }

    logInteractionEvent("selection_changed", {
      source,
      cols: nextCols,
      rowIds: nextIds || [],
      rowCount: nextIds?.length || 0,
      ...meta,
    });
  }, [highlightedRowIds]);

  const clearHighlight = useCallback((reason = "clear_highlight", meta = {}) => {
    const hadSelection = highlightedRowIds?.length > 0;
    setHighlightedRowIdsState(null);
    setHighlightedColsState(null);
    setSelectionSourceState(null);
    setHighlightRevision(rev => rev + 1);
    if (hadSelection) {
      setSelectionNotice({
        id: Date.now(),
        message: "Selection cleared",
      });
    }
    logInteractionEvent("selection_cleared", {
      reason,
      ...meta,
    });
  }, [highlightedRowIds]);

  const clearSelectionNotice = useCallback(() => {
    setSelectionNotice(null);
  }, []);

  return (
    <SelectionContext.Provider value={{
      selection, setSelection, clearSelection,
      highlightedRowIds, highlightedCols,
      selectionSource, highlightRevision,
      selectionNotice,
      setHighlightedRowIds, clearHighlight,
      clearSelectionNotice,
    }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  return useContext(SelectionContext);
}
