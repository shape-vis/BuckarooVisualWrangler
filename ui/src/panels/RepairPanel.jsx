import { useContext, useState } from "react";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { SelectionContext } from "../utils/SelectionContext.jsx";
import { createPreviews, executeWrangle } from "../utils/serverCalls.jsx";
import PreviewCard from "./PreviewCard.jsx";
import "./RepairPanel.css";
import * as d3 from "d3";

const ERROR_COLORS = d3.scaleOrdinal()
  .domain(["total", "missing", "mismatch", "anomaly", "incomplete", "none"])
  .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);

export default function RepairPanel({ table_name, onWrangleExecuted }) {
  const { highlightedRowIds, highlightedCols, selectionSource, clearHighlight } = useContext(SelectionContext);

  const [busy, setBusy] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [previews, setPreviews] = useState(null);
  // previews shape:
  //   1D: { type: "histogram", preview_delete, preview_impute, cols }
  //   2D: { type: "heatmap"|"scatterplot", preview_delete, preview_impute_x, preview_impute_y, cols }

  const hasSelection = highlightedRowIds && highlightedRowIds.length > 0;

  async function handleRepairSelection() {
    if (!hasSelection) return;

    setBusy(true);
    setPreviewError(null);
    setPreviews(null);

    const cols = highlightedCols || [];
    const result = await createPreviews(table_name, highlightedRowIds, cols);

    setBusy(false);

    if (!result?.success) {
      setPreviewError(result?.error || "Preview generation failed.");
      return;
    }

    if (result.dims === 1) {
      setPreviews({
        type: "histogram",
        preview_delete: result.preview_delete,
        preview_impute: result.preview_impute,
        cols,
      });
    } else {
      setPreviews({
        type: selectionSource || "heatmap",
        preview_delete: result.preview_delete,
        preview_impute_x: result.preview_impute_x,
        preview_impute_y: result.preview_impute_y,
        cols,
      });
    }
  }

  async function handleExecuteWrangle(previewTableName) {
    setBusy(true);
    setPreviewError(null);
    const result = await executeWrangle(table_name, previewTableName);
    setBusy(false);
    if (result?.success) {
      setPreviews(null);
      clearHighlight();
      onWrangleExecuted?.();
    } else {
      setPreviewError(result?.error || "Execute wrangle failed.");
    }
  }

  function handleClearSelection() {
    clearHighlight();
    setPreviews(null);
    setPreviewError(null);
  }

  return (
    <CollapsiblePanel direction="right" collapsed={"Data Repair Panel"} defaultOpen={false} style={{ height: "100%", margin: "0px 0" }}>
      <div id="toolbox">
        <div style={{ fontWeight: "bold", marginLeft: "auto", marginRight: "auto", marginTop: "10px", marginBottom: "10px" }}>
          Data Repair Panel
        </div>

        {/* ── Action buttons ───────────────────────────────────────────── */}
        <div className="repair-tools">
          <div
            id="repairButton"
            className="regButton"
            style={{
              width: "130px",
              opacity: hasSelection ? 1 : 0.4,
              cursor: hasSelection ? "pointer" : "not-allowed",
            }}
            onClick={handleRepairSelection}
          >
            ⚒️ Repair Selection
          </div>

          <div
            id="zoomButton"
            className="regButton"
            style={{ width: "130px", marginLeft: "25px", marginRight: "25px" }}
          >
            🔍 Zoom Selection
          </div>

          <div
            id="undoButton"
            className="regButton"
            style={{ width: "65px" }}
            onClick={handleClearSelection}
          >
            ↩️ Undo
          </div>

          <div id="redoButton" className="regButton" style={{ width: "65px" }}>
            🔄 Redo
          </div>
        </div>

        {/* ── Selection status ─────────────────────────────────────────── */}
        <div style={{ fontSize: 11, color: "#555", margin: "6px 12px", minHeight: 16 }}>
          {hasSelection
            ? `${highlightedRowIds.length} row(s) selected${highlightedCols?.length ? ` · cols: ${highlightedCols.join(", ")}` : ""}`
            : "No selection — click a point, bin, or bar in the plots."}
        </div>

        {/* ── Feedback ─────────────────────────────────────────────────── */}
        {busy && (
          <div style={{ fontSize: 12, color: "#555", margin: "8px 12px" }}>
            Generating previews…
          </div>
        )}
        {previewError && (
          <div style={{ fontSize: 12, color: "red", margin: "8px 12px" }}>
            Error: {previewError}
          </div>
        )}

        {/* ── Preview area ──────────────────────────────────────────────── */}
        <div id="preview-area" className="toolbox-preview-area">
          {previews && previews.type === "histogram" && (
            <>
              <PreviewCard
                label="Delete Preview"
                tableName={previews.preview_delete}
                cols={previews.cols}
                errorColors={ERROR_COLORS}
                chartType="histogram"
                onExecuteWrangle={() => handleExecuteWrangle(previews.preview_delete)}
              />
              <PreviewCard
                label="Impute Preview"
                tableName={previews.preview_impute}
                cols={previews.cols}
                errorColors={ERROR_COLORS}
                chartType="histogram"
                onExecuteWrangle={() => handleExecuteWrangle(previews.preview_impute)}
              />
            </>
          )}
          {previews && (previews.type === "heatmap" || previews.type === "scatterplot") && (
            <>
              <PreviewCard
                label="Delete Preview"
                tableName={previews.preview_delete}
                cols={previews.cols}
                errorColors={ERROR_COLORS}
                chartType={previews.type}
                onExecuteWrangle={() => handleExecuteWrangle(previews.preview_delete)}
              />
              <PreviewCard
                label={`Impute "${previews.cols[0]}" Preview`}
                tableName={previews.preview_impute_x}
                cols={previews.cols}
                errorColors={ERROR_COLORS}
                chartType={previews.type}
                onExecuteWrangle={() => handleExecuteWrangle(previews.preview_impute_x)}
              />
              <PreviewCard
                label={`Impute "${previews.cols[1]}" Preview`}
                tableName={previews.preview_impute_y}
                cols={previews.cols}
                errorColors={ERROR_COLORS}
                chartType={previews.type}
                onExecuteWrangle={() => handleExecuteWrangle(previews.preview_impute_y)}
              />
            </>
          )}
        </div>
      </div>
    </CollapsiblePanel>
  );
}
