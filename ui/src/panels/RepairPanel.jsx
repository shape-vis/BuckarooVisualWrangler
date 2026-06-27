import { useContext, useState, useEffect, useCallback, useMemo } from "react";
import { SelectionContext } from "../store/SelectionContext.jsx";
import { executeWrangle, getPGraph, queryPreviewRowDiff } from "../utils/serverCalls.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useLoading } from "../store/LoadingContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import PreviewCard from "./PreviewCard.jsx";
import "../styles/RepairPanel.css";
import { errorColors as ERROR_COLORS } from "../store/errorColors.js";
import { usePgraph } from "../store/PGraphContext.jsx";
import { logInteractionEvent } from "../utils/interactionLogger.jsx";

function buildPreviewOptions(previews) {
  if (!previews) return [];

  const options = [{
    key: "delete",
    label: "Delete Rows",
    tableName: previews.preview_delete,
    repairType: "delete_rows",
    action: "delete",
    targetColumn: null,
    diffCols: previews.cols || [],
    animationType: "delete",
  }];

  if (previews.type === "histogram") {
    options.push({
      key: "impute",
      label: `Impute "${previews.cols[0]}"`,
      tableName: previews.preview_impute,
      repairType: `impute:${previews.cols[0]}`,
      action: "impute",
      targetColumn: previews.cols[0],
      diffCols: [previews.cols[0]],
      animationType: "impute",
    });
    return options;
  }

  options.push({
    key: "impute-x",
    label: `Impute "${previews.cols[0]}"`,
    tableName: previews.preview_impute_x,
    repairType: `impute:${previews.cols[0]}`,
    action: "impute",
    targetColumn: previews.cols[0],
    diffCols: [previews.cols[0]],
    animationType: "impute",
  });
  options.push({
    key: "impute-y",
    label: `Impute "${previews.cols[1]}"`,
    tableName: previews.preview_impute_y,
    repairType: `impute:${previews.cols[1]}`,
    action: "impute",
    targetColumn: previews.cols[1],
    diffCols: [previews.cols[1]],
    animationType: "impute",
  });

  return options;
}

function rowPhrase(count) {
  return `${count} selected ${count === 1 ? "row" : "rows"}`;
}

function shortValue(value, maxLength = 44) {
  const text = value === null || value === undefined || value === "" ? "null" : String(value);
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function buildPreviewExplanation(activePreview, selectedCount, diffRows) {
  if (!activePreview) return "Select a preview to see what it will change.";

  if (activePreview.action === "delete") {
    return `This removes ${rowPhrase(selectedCount)}.`;
  }

  const changedRows = (diffRows || []).filter(row => row.status === "changed");
  if (changedRows.length === 1) {
    const row = changedRows[0];
    return `This changes ${activePreview.targetColumn} from ${shortValue(row.before)} to ${shortValue(row.after)}.`;
  }
  if (changedRows.length > 1) {
    return `This changes ${activePreview.targetColumn} for ${changedRows.length} selected rows.`;
  }

  return `This replaces missing/invalid values in ${activePreview.targetColumn}.`;
}

export default function RepairPanel() {
  const { tableName, setTableName } = useTableName();
  const { addLoader, removeLoader } = useLoading();
  const {
    highlightedRowIds,
    highlightedCols,
    selectionSource,
    clearHighlight,
  } = useContext(SelectionContext);
  const {
    busy,
    setBusy,
    requestPreviews,
    registerRepairHandler,
    repairPanelOpenTrigger,
    repairPanelCloseTrigger,
    closeRepairPanel,
    notifyRepairWrangleExecuted,
  } = useRepair();
  const { getLayoutedElements, setNodes, setEdges } = usePgraph();

  const [isOpen, setIsOpen] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [previews, setPreviews] = useState(null);
  const [previewsGenerated, setPreviewsGenerated] = useState(false);
  const [busyMessage, setBusyMessage] = useState("Generating previews...");
  const [selectedPreviewTable, setSelectedPreviewTable] = useState(null);
  const [diffState, setDiffState] = useState({
    loading: false,
    error: null,
    rows: [],
    truncated: false,
    totalRowCount: 0,
  });

  const hasSelection = highlightedRowIds && highlightedRowIds.length > 0;
  const selectedColumns = useMemo(() => highlightedCols || [], [highlightedCols]);
  const sourceLabel = selectionSource || (selectedColumns.length > 1 ? "2D plot" : "histogram");
  const chartType = previews?.type || (
    selectedColumns.length <= 1
      ? "histogram"
      : selectionSource === "scatterplot"
        ? "scatterplot"
        : "heatmap"
  );
  const previewOptions = useMemo(() => buildPreviewOptions(previews), [previews]);
  const activePreview = useMemo(() => {
    return previewOptions.find(option => option.tableName === selectedPreviewTable)
      || previewOptions[0]
      || null;
  }, [previewOptions, selectedPreviewTable]);
  const selectedRowsKey = useMemo(() => (highlightedRowIds || []).map(String).join(","), [highlightedRowIds]);
  const activeDiffColsKey = activePreview?.diffCols?.join("|") || "";
  const previewExplanation = useMemo(() => (
    buildPreviewExplanation(activePreview, highlightedRowIds?.length || 0, diffState.rows)
  ), [activePreview, highlightedRowIds, diffState.rows]);

  const closeWorkspace = useCallback(() => {
    setIsOpen(false);
    closeRepairPanel();
  }, [closeRepairPanel]);

  const handleRepairSelection = useCallback(async () => {
    setIsOpen(true);
    setPreviewError(null);
    setPreviews(null);
    setSelectedPreviewTable(null);
    setDiffState({
      loading: false,
      error: null,
      rows: [],
      truncated: false,
      totalRowCount: 0,
    });
    setPreviewsGenerated(false);
    setBusyMessage("Generating previews...");
    logInteractionEvent("repair_previews_requested", {
      table: tableName,
      source: selectionSource,
      cols: selectedColumns,
      rowIds: highlightedRowIds || [],
      rowCount: highlightedRowIds?.length || 0,
    });

    const response = await requestPreviews();
    if (!response) {
      logInteractionEvent("repair_previews_skipped", {
        reason: "no_active_selection",
        table: tableName,
      });
      return;
    }

    const { result, cols, selectionSource: previewSource } = response;

    if (!result?.success) {
      setPreviewError(result?.error || "Preview generation failed.");
      logInteractionEvent("repair_previews_failed", {
        table: tableName,
        source: previewSource,
        cols,
        error: result?.error || "Preview generation failed.",
      });
      return;
    }

    setPreviewsGenerated(true);
    logInteractionEvent("repair_previews_generated", {
      table: tableName,
      source: previewSource,
      cols,
      dims: result.dims,
      previewTables: {
        delete: result.preview_delete,
        impute: result.preview_impute,
        imputeX: result.preview_impute_x,
        imputeY: result.preview_impute_y,
      },
    });

    if (result.dims === 1) {
      setPreviews({
        type: "histogram",
        preview_delete: result.preview_delete,
        preview_impute: result.preview_impute,
        cols,
      });
    } else {
      setPreviews({
        type: previewSource || "heatmap",
        preview_delete: result.preview_delete,
        preview_impute_x: result.preview_impute_x,
        preview_impute_y: result.preview_impute_y,
        cols,
      });
    }
  }, [requestPreviews, tableName, selectionSource, selectedColumns, highlightedRowIds]);

  useEffect(() => {
    registerRepairHandler(handleRepairSelection);
    return () => registerRepairHandler(null);
  }, [registerRepairHandler, handleRepairSelection]);

  useEffect(() => {
    if (repairPanelOpenTrigger > 0) setIsOpen(true);
  }, [repairPanelOpenTrigger]);

  useEffect(() => {
    if (repairPanelCloseTrigger > 0) setIsOpen(false);
  }, [repairPanelCloseTrigger]);

  useEffect(() => {
    if (!previewOptions.length) {
      setSelectedPreviewTable(null);
      return;
    }

    if (!selectedPreviewTable || !previewOptions.some(option => option.tableName === selectedPreviewTable)) {
      setSelectedPreviewTable(previewOptions[0].tableName);
    }
  }, [previewOptions, selectedPreviewTable]);

  useEffect(() => {
    let isActive = true;

    if (!activePreview || !tableName || !selectedRowsKey || !activePreview.diffCols?.length) {
      setDiffState({
        loading: false,
        error: null,
        rows: [],
        truncated: false,
        totalRowCount: 0,
      });
      return () => {
        isActive = false;
      };
    }

    setDiffState({
      loading: true,
      error: null,
      rows: [],
      truncated: false,
      totalRowCount: highlightedRowIds?.length || 0,
    });

    queryPreviewRowDiff({
      source_table: tableName,
      preview_table: activePreview.tableName,
      row_ids: highlightedRowIds || [],
      cols: activePreview.diffCols,
    }).then(result => {
      if (!isActive) return;
      if (result?.success) {
        setDiffState({
          loading: false,
          error: null,
          rows: result.rows || [],
          truncated: Boolean(result.truncated),
          totalRowCount: result.totalRowCount || 0,
        });
      } else {
        setDiffState({
          loading: false,
          error: result?.error || "Could not load before/after values.",
          rows: [],
          truncated: false,
          totalRowCount: 0,
        });
      }
    }).catch(error => {
      if (!isActive) return;
      setDiffState({
        loading: false,
        error: error?.message || "Could not load before/after values.",
        rows: [],
        truncated: false,
        totalRowCount: 0,
      });
    });

    return () => {
      isActive = false;
    };
  }, [
    activePreview?.tableName,
    activeDiffColsKey,
    tableName,
    selectedRowsKey,
    highlightedRowIds,
  ]);

  async function handleExecuteWrangle(previewTableName, repairType) {
    setBusy(true);
    addLoader();
    setPreviewError(null);
    setBusyMessage("Executing wrangle...");
    logInteractionEvent("wrangle_execute_requested", {
      table: tableName,
      previewTable: previewTableName,
      repairType,
      cols: selectedColumns,
      rowIds: highlightedRowIds || [],
      rowCount: highlightedRowIds?.length || 0,
    });

    try {
      const result = await executeWrangle(previewTableName);

      if (result?.success) {
        logInteractionEvent("wrangle_execute_succeeded", {
          table: tableName,
          previewTable: previewTableName,
          repairType,
          nextTable: result.table,
        });
        const pGraphResult = await getPGraph();
        if (pGraphResult?.nodes && pGraphResult?.edges) {
          const layoutNodesEdges = getLayoutedElements(pGraphResult.nodes, pGraphResult.edges);
          setNodes(layoutNodesEdges.nodes);
          setEdges(layoutNodesEdges.edges);
        }
        if (result.table) {
          setTableName(result.table);
        }
        setPreviews(null);
        clearHighlight();
        closeWorkspace();
        notifyRepairWrangleExecuted?.();
      } else {
        setPreviewError(result?.error || "Execute wrangle failed.");
        logInteractionEvent("wrangle_execute_failed", {
          table: tableName,
          previewTable: previewTableName,
          repairType,
          error: result?.error || "Execute wrangle failed.",
        });
      }
    } catch (error) {
      setPreviewError(error?.message || "Execute wrangle failed.");
      logInteractionEvent("wrangle_execute_failed", {
        table: tableName,
        previewTable: previewTableName,
        repairType,
        error: error?.message || "Execute wrangle failed.",
      });
    } finally {
      setBusy(false);
      removeLoader();
    }
  }

  function renderPreviewCards() {
    if (!previews) {
      return (
        <div className="repair-empty-preview">
          {busy ? "Building repair previews..." : "No repair previews yet."}
        </div>
      );
    }

    return (
      <>
        {previewOptions.map(option => (
          <PreviewCard
            key={option.key}
            label={option.label}
            tableName={option.tableName}
            sourceTableName={tableName}
            cols={previews.cols}
            errorColors={ERROR_COLORS}
            chartType={previews.type}
            selectedRowIds={highlightedRowIds}
            animationType={option.animationType}
            isSelected={activePreview?.tableName === option.tableName}
            onSelect={() => setSelectedPreviewTable(option.tableName)}
            onExecuteWrangle={() => handleExecuteWrangle(option.tableName, option.repairType)}
          />
        ))}
      </>
    );
  }

  function renderPreviewDetails() {
    if (!previews) return null;

    return (
      <div className="repair-preview-details">
        <div className="repair-preview-details-title">Selected Preview</div>
        <div className="repair-preview-name">
          {activePreview?.label || "No preview selected"}
        </div>
        <p className="repair-preview-explanation">
          {diffState.loading ? "Checking selected row changes..." : previewExplanation}
        </p>

        <div className="repair-diff-title">Before / After Values</div>
        {diffState.loading && (
          <div className="repair-diff-empty">Loading value changes...</div>
        )}
        {!diffState.loading && diffState.error && (
          <div className="repair-diff-error">{diffState.error}</div>
        )}
        {!diffState.loading && !diffState.error && diffState.rows.length === 0 && (
          <div className="repair-diff-empty">No row-level values to compare.</div>
        )}
        {!diffState.loading && !diffState.error && diffState.rows.length > 0 && (
          <>
            <div className="repair-diff-table-wrap">
              <table className="repair-diff-table">
                <thead>
                  <tr>
                    <th>Row ID</th>
                    <th>Column</th>
                    <th>Before</th>
                    <th>After</th>
                  </tr>
                </thead>
                <tbody>
                  {diffState.rows.map((row, index) => (
                    <tr
                      key={`${row.rowId}-${row.column}-${index}`}
                      className={`repair-diff-row repair-diff-row--${row.status}`}
                    >
                      <td>{row.rowId}</td>
                      <td title={row.column}>{shortValue(row.column, 28)}</td>
                      <td title={row.before}>{shortValue(row.before)}</td>
                      <td title={row.after}>{shortValue(row.after)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {diffState.truncated && (
              <div className="repair-diff-note">
                Showing the first 100 of {diffState.totalRowCount} selected rows.
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  if (!isOpen) return null;

  return (
    <div className="repair-workspace-backdrop" role="presentation">
      <section
        className="repair-workspace"
        data-tutorial-target="repair-workspace"
        role="dialog"
        aria-modal="true"
        aria-labelledby="repair-workspace-title"
      >
        <header className="repair-workspace-header">
          <div>
            <h2 id="repair-workspace-title">Repair Workspace</h2>
            <div className="repair-workspace-subtitle">
              {hasSelection
                ? `${highlightedRowIds.length} row(s) selected`
                : "No active selection"}
            </div>
          </div>
          <button
            type="button"
            className="repair-workspace-close"
            onClick={closeWorkspace}
            aria-label="Close repair workspace"
          >
            x
          </button>
        </header>

        {(busy || previewsGenerated || previewError) && (
          <div className="repair-workspace-feedback">
            {busy && (
              <div className="repair-feedback-centered">
                {busyMessage}
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
          </div>
        )}

        <div className="repair-workspace-grid">
          <aside className="repair-workspace-column repair-workspace-summary">
            <div className="repair-workspace-section-title">Selection Summary</div>
            <dl className="repair-summary-list">
              <div>
                <dt>Rows</dt>
                <dd>{hasSelection ? highlightedRowIds.length : 0}</dd>
              </div>
              <div>
                <dt>Columns</dt>
                <dd>{selectedColumns.length > 0 ? selectedColumns.join(", ") : "None"}</dd>
              </div>
              <div>
                <dt>Source</dt>
                <dd>{sourceLabel}</dd>
              </div>
              <div>
                <dt>Current table</dt>
                <dd>{tableName || "None"}</dd>
              </div>
            </dl>
            <div className="repair-row-list-title">Selected Row IDs</div>
            <div className="repair-row-list">
              {hasSelection
                ? highlightedRowIds.slice(0, 60).join(", ")
                : "Select a point, bin, or bar before opening repair."}
              {hasSelection && highlightedRowIds.length > 60
                ? `, +${highlightedRowIds.length - 60} more`
                : ""}
            </div>
            {renderPreviewDetails()}
          </aside>

          <main className="repair-workspace-column repair-workspace-before">
            <div className="repair-workspace-section-title">Before Repair</div>
            {hasSelection && tableName && selectedColumns.length > 0 ? (
              <PreviewCard
                label="Current Data"
                tableName={tableName}
                cols={selectedColumns}
                errorColors={ERROR_COLORS}
                chartType={chartType}
                selectedRowIds={highlightedRowIds}
              />
            ) : (
              <div className="repair-empty-preview">No selected data to preview.</div>
            )}
          </main>

          <aside className="repair-workspace-column repair-workspace-previews">
            <div className="repair-workspace-section-title">Repair Previews</div>
            <div className="repair-preview-list">
              {renderPreviewCards()}
            </div>
          </aside>
        </div>
      </section>
    </div>
  );
}
