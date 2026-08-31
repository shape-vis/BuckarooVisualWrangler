import { useContext, useState, useEffect, useCallback } from "react";
import { SelectionContext } from "../store/SelectionContext.jsx";
import {executeWrangle} from "../utils/serverCalls.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import PreviewCard from "./PreviewCard.jsx";
import "../styles/RepairPanel.css";
import { errorColors as ERROR_COLORS } from "../store/errorColors.js";
import {usePgraph} from "../store/PGraphContext.jsx";

export default function RepairPanel() {
  // global contexts for this component
  const { setTableName } = useTableName();
  const { addLoader, removeLoader } = useLoading();
  const { highlightedRowIds, highlightedCols, clearHighlight } = useContext(SelectionContext);
  const { busy, setBusy, requestPreviews, registerRepairHandler, closeRepairPanel, onWrangleExecuted } = useRepair();
  const {refreshGraph} = usePgraph();
  //local component state
  const [previewError, setPreviewError] = useState(null);
  const [previews, setPreviews] = useState(null);
  const [previewsGenerated, setPreviewsGenerated] = useState(false);


  const hasSelection = highlightedRowIds && highlightedRowIds.length > 0;

  const handleRepairSelection = useCallback(async () => {
    setPreviewError(null);
    setPreviews(null);
    setPreviewsGenerated(false);

    const response = await requestPreviews();
    if (!response) return;

    const { result, cols, selectionSource } = response;

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
  }, [requestPreviews]);

  useEffect(() => {
    registerRepairHandler(handleRepairSelection);
    return () => registerRepairHandler(null);
  }, [registerRepairHandler, handleRepairSelection]);

  async function handleExecuteWrangle(previewTableName) {
    setBusy(true);
    addLoader();
    setPreviewError(null);

    //execute the wrangle
    // The columns the selection was made on, so the new node's edge can name them
    const result = await executeWrangle(previewTableName, previews?.cols ?? []);

    //the wrangle added a node, so pull the graph back down and re-layout it
    await refreshGraph();

    setBusy(false);
    removeLoader();
    if (result?.success) {
      if (result.table) {
        setTableName(result.table);
      }
      setPreviews(null);
      clearHighlight();
      closeRepairPanel();
      onWrangleExecuted?.();
    } else {
      setPreviewError(result?.error || "Execute wrangle failed.");
    }
  }

  // The dock owns the panel chrome - tab strip, collapsing and resizing - so this renders bare content
  return (
      <div id="toolbox">
        <div className="repair-panel-title">
          Data Repair Panel
        </div>

        {/* ── Action buttons ─────────────────────────────────────────────
        <div className="repair-tools">
          <div
            id="zoomButton"
            className="regButton regButton--zoom"
          >
            Zoom Selection
          </div>
        </div> */}

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
  );
}
