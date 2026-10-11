import { useContext } from "react";
import { SelectionContext } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import PreviewCard from "./PreviewCard.jsx";
import "../styles/RepairPanel.css";
import { errorColors as ERROR_COLORS } from "../store/errorColors.js";
import {usePgraph} from "../store/PGraphContext.jsx";

/* A candidate's card title: a lone impute is just "Impute", while a two-column selection's imputes name
   the column each fills */
function cardLabel(entry) {
  if (entry.op === "delete") return "Delete Preview";
  return entry.cols?.length > 1 ? `Impute "${entry.column}" Preview` : "Impute Preview";
}

/**
 * The repair candidates for the current selection, as preview charts. The same candidates hang off the
 * current node in the graph - see RepairContext - so executing one here, or accepting or declining one there,
 * is reflected in both. Asking for repairs no longer opens this panel; it is here for a closer look.
 */
export default function RepairPanel() {
  // global contexts for this component
  const { tableName } = useTableName();
  const { highlightedRowIds, highlightedCols } = useContext(SelectionContext);
  const { busy, repairEntries, acceptRepair, repairError } = useRepair();
  const {serverNodesById} = usePgraph();
  // The current table's size, from the metrics its graph node already carries
  const totalRows = serverNodesById?.[tableName]?.data?.metrics?.row_count;

  const hasSelection = highlightedRowIds && highlightedRowIds.length > 0;

  // The dock owns the panel chrome - tab strip, collapsing and resizing - so this renders bare content
  return (
      <div id="toolbox">
        <div className="repair-panel-title">
          Data Repair Panel
        </div>

        {/* ── Selection status ─────────────────────────────────────────── */}
        <div className="repair-selection-status">
          {hasSelection
            ? `${highlightedRowIds.length.toLocaleString()}${totalRows != null ? ` of ${totalRows.toLocaleString()}` : ""} row(s) selected${highlightedCols?.length ? ` · cols: ${highlightedCols.join(", ")}` : ""}`
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
        {!busy && repairEntries.length > 0 && !repairError && (
          <div className="repair-feedback-centered repair-success">
            Previews generated - also shown as candidate nodes in the graph
          </div>
        )}
        {repairError && (
          <div className="repair-error">
            Error: {repairError}
          </div>
        )}

        {/* ── Preview area ──────────────────────────────────────────────── */}
        <div id="preview-area" className="toolbox-preview-area">
          {repairEntries.map((entry) => (
            <PreviewCard
              key={entry.id}
              label={cardLabel(entry)}
              tableName={entry.previewTable}
              cols={entry.cols}
              errorColors={ERROR_COLORS}
              chartType={entry.chartType}
              onExecuteWrangle={() => acceptRepair(entry.id)}
            />
          ))}
        </div>
      </div>
  );
}
