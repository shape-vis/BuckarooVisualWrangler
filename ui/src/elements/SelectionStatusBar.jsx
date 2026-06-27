import { useEffect } from "react";
import { useSelection } from "../store/SelectionContext.jsx";
import "../styles/SelectionStatusBar.css";

export default function SelectionStatusBar() {
  const {
    highlightedRowIds,
    highlightedCols,
    selectionSource,
    selectionNotice,
    clearHighlight,
    clearSelectionNotice,
  } = useSelection();

  const selectedCount = highlightedRowIds?.length || 0;
  const hasSelection = selectedCount > 0;

  useEffect(() => {
    if (!selectionNotice) return undefined;
    const timer = window.setTimeout(() => {
      clearSelectionNotice();
    }, 2200);
    return () => window.clearTimeout(timer);
  }, [selectionNotice, clearSelectionNotice]);

  if (!hasSelection && !selectionNotice) return null;

  return (
    <div className="selection-status-overlay" aria-live="polite">
      {hasSelection && (
        <div className="selection-status-bar">
          <strong>
            {selectedCount} row{selectedCount === 1 ? "" : "s"} selected
          </strong>
          {highlightedCols?.length > 0 && (
            <span className="selection-status-detail">
              {highlightedCols.join(", ")}
            </span>
          )}
          {selectionSource && (
            <span className="selection-status-source">{selectionSource}</span>
          )}
          <button
            type="button"
            className="selection-status-clear"
            onClick={() => clearHighlight("selection_status_clear")}
          >
            Clear
          </button>
        </div>
      )}
      {selectionNotice && (
        <div className="selection-status-toast" key={selectionNotice.id}>
          {selectionNotice.message}
        </div>
      )}
    </div>
  );
}
