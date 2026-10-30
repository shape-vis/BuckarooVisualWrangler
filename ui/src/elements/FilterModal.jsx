import React, { useState } from "react";

import "../styles/FilterModal.css";
import Modal from "./Modal.jsx";
import HistogramBarChart from "../visualizations/HistogramBarChart.jsx";
import { useSelection } from "../store/SelectionContext.jsx";

export default function FilterModal({ visible, attribute, onClose, onApply, errorColors }) {
  const { selection, highlightedRowIds } = useSelection();
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  if (!visible) return null;

  const selectedForAttribute = Boolean(
    selection?.viewType === "barchart"
    && selection?.cols?.length === 1
    && selection.cols[0] === attribute
    && selection?.data?.length > 0
  );
  const selectedRows = selectedForAttribute ? (highlightedRowIds?.length || 0) : 0;

  async function handleApply() {
    if (!selectedForAttribute) {
      setError("Select one or more bars before applying the filter.");
      return;
    }
    setApplying(true);
    setError("");
    try {
      await onApply(selection, selectedRows);
    } catch (applyError) {
      setError(applyError.message || "Could not apply this filter.");
    } finally {
      setApplying(false);
    }
  }

  return (
    <Modal visible={visible}>
      <div className="filter-modal-content" role="dialog" aria-modal="true" aria-label={`Filter rows by ${attribute}`}>
        <div className="filter-modal-header">
          <div>
            <span>Filter rows</span>
            <h2 title={attribute}>{attribute}</h2>
          </div>
          <button type="button" className="filter-modal-close" onClick={onClose} aria-label="Close filter">X</button>
        </div>

        <p className="filter-modal-instruction">Select a bar or drag across several bars. Only matching rows will remain in the plots.</p>

        <div className="filter-modal-chart">
          <svg viewBox="0 0 400 340" role="img" aria-label={`Value distribution for ${attribute}`}>
            <HistogramBarChart
              cellID="filterModalHistogram"
              pos={{ x: 50, y: 20 }}
              size={{ w: 300, h: 270 }}
              attrX={attribute}
              errorColors={errorColors}
            />
          </svg>
        </div>

        <div className={`filter-modal-selection ${selectedForAttribute ? "filter-modal-selection--ready" : ""}`} role="status">
          {selectedForAttribute
            ? `${selectedRows.toLocaleString()} matching row${selectedRows === 1 ? "" : "s"} selected`
            : "No values selected yet"}
        </div>
        {error && <div className="filter-modal-error" role="alert">{error}</div>}

        <div className="filter-modal-actions">
          <button type="button" className="filter-modal-cancel" onClick={onClose} disabled={applying}>Cancel</button>
          <button type="button" className="filter-modal-apply" onClick={handleApply} disabled={applying || !selectedForAttribute}>
            {applying ? "Applying..." : "Apply filter"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
