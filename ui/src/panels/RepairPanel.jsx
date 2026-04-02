import { useContext, useState } from "react";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";
import { SelectionContext } from "../utils/SelectionContext.jsx";
import { createPreviews, executeWrangle } from "../utils/serverCalls.jsx";
import PreviewCard from "./PreviewCard.jsx";
import "../styles/RepairPanel.css";
import { errorColors as ERROR_COLORS } from "../utils/errorColors.js";

export default function RepairPanel({ table_name, onWrangleExecuted }) {
  const { highlightedRowIds, highlightedCols, selectionSource, clearHighlight } = useContext(SelectionContext);

  const [busy, setBusy] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [previews, setPreviews] = useState(null);
  const [previewsGenerated, setPreviewsGenerated] = useState(false);
  // previews shape:
  //   1D: { type: "histogram", preview_delete, preview_impute, cols }
  //   2D: { type: "heatmap"|"scatterplot", preview_delete, preview_impute_x, preview_impute_y, cols }

  const hasSelection = highlightedRowIds && highlightedRowIds.length > 0;

  async function handleRepairSelection() {
    if (!hasSelection) return;

    setBusy(true);
    setPreviewError(null);
    setPreviews(null);
    setPreviewsGenerated(false);

    const cols = highlightedCols || [];
    const result = await createPreviews(table_name, highlightedRowIds, cols);

    setBusy(false);

    if (!result?.success) {
      setPreviewError(result?.error || "Preview generation failed.");
      return;
    }

    setPreviewsGenerated(true);

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
    setPreviewsGenerated(false);
  }

  return (
    <CollapsiblePanel direction="right" collapsed={"Data Repair Panel"} defaultOpen={false} className="panel--repair">
      <div id="toolbox">
        <div className="repair-panel-title">
          Data Repair Panel
        </div>

        {/* ── Action buttons ───────────────────────────────────────────── */}
        <div className="repair-tools">
          <div
            id="repairButton"
            className={`regButton ${hasSelection ? "regButton--repair" : "regButton--repair-disabled"}`}
            onClick={handleRepairSelection}
          >
            Repair Selection
          </div>

          <div
            id="zoomButton"
            className="regButton regButton--zoom"
          >
            Zoom Selection
          </div>

          <div
            id="undoButton"
            className="regButton regButton--small"
            onClick={handleClearSelection}
          >
            Undo
          </div>

          <div id="redoButton" className="regButton regButton--small">
            Redo
          </div>
        </div>

        {/* ── Selection status ─────────────────────────────────────────── */}
        <div className="repair-selection-status">
          {hasSelection
            ? `${highlightedRowIds.length} row(s) selected${highlightedCols?.length ? ` · cols: ${highlightedCols.join(", ")}` : ""}`
            : "No selection — click a point, bin, or bar in the plots."}
        </div>

        {/* ── Feedback ─────────────────────────────────────────────────── */}
        {busy && (
          <div className="repair-feedback-centered">
            Generating previews…
            <div className="repair-loading-bar-track">
              <div className="repair-loading-bar-fill" />
            </div>
          </div>
        )}
        {!busy && previewsGenerated && !previewError && (
          <div className="repair-feedback-centered repair-success">
            Previews generated
          </div>
        )}
        {previewError && (
          <div className="repair-error">
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
