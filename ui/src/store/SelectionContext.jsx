// SelectionContext.jsx
// Global context shared by all plots and by Repair, which repairs what they select.
//
// highlightedRowIds  – row IDs currently lit up across all charts (null = nothing)
// highlightedCols    – the column name(s) involved in the selection (for imputation)
//                      [colX] for histogram, [colX, colY] for heatmap/scatterplot
// selectionSource    – the plot the selection was made on, or null
// highlightRevision  – counts every change to the highlight, so a plot can drop a row lookup that a newer
//                      highlight has overtaken

import { createContext, useContext, useState, useCallback } from "react";

export const SelectionContext = createContext(null);

export function SelectionProvider({ children }) {
    const [highlightedRowIds, setHighlightedRowIdsState] = useState(null);
    const [highlightedCols, setHighlightedColsState] = useState(null);
    const [selectionSource, setSelectionSourceState] = useState(null);
    const [highlightRevision, setHighlightRevision] = useState(0);

    /**
     * Set the cross-chart highlight.
     * @param {number[]} ids    – row IDs to highlight (pass null/[] to clear)
     * @param {string[]} cols   – columns involved (for preview / imputation)
     * @param {string|null} source – "histogram" | "heatmap" | "scatterplot" | null
     */
    const setHighlightedRowIds = useCallback((ids, cols, source = null) => {
        const hasIds = Boolean(ids && ids.length > 0);
        const hasCols = Boolean(cols && cols.length > 0);

        setHighlightedRowIdsState(hasIds ? ids : null);
        setHighlightedColsState(hasCols ? cols : null);
        setSelectionSourceState(source);
        setHighlightRevision(rev => rev + 1);
    }, []);

    const clearHighlight = useCallback(() => {
        setHighlightedRowIds(null, null);
    }, [setHighlightedRowIds]);

    return (
        <SelectionContext.Provider value={{
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
