import { useContext } from "react";
import { SelectionContext } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import { useCandidates } from "../store/CandidatesContext.jsx";
import PreviewCard from "./PreviewCard.jsx";
import "../styles/RepairPanel.css";
import { errorColors as ERROR_COLORS } from "../store/errorColors.js";
import { usePgraph } from "../store/PGraphContext.jsx";
import { nodeName } from "../utils/comparison.js";
import { CANDIDATE_SOURCES } from "../utils/candidates.js";

/**
 * The line saying what is selected: how many rows, out of how many when the table's size is known, and in
 * which columns.
 */
function selectionStatus(rowIds, cols, totalRows) {
  if (!rowIds || rowIds.length === 0) {
    return "No selection — click a point, bin, or bar in the plots.";
  }

  const selectedText = rowIds.length.toLocaleString();

  let ofTotal = "";
  if (totalRows != null) {
    ofTotal = ` of ${totalRows.toLocaleString()}`;
  }

  let colsText = "";
  if (cols?.length) {
    colsText = ` · cols: ${cols.join(", ")}`;
  }

  const statusText = `${selectedText}${ofTotal} row(s) selected${colsText}`;
  return statusText;
}

function candidateLabel(node) {
  const candidate = node.data.candidate ?? {};
  const sourceTag = CANDIDATE_SOURCES[candidate.source]?.tag ?? "Candidate";
  const candidateName = candidate.label ?? "";
  return `${sourceTag} · ${nodeName(node.id)} · ${candidateName}`;
}

/**
 * Every candidate staged on the graph - repairs of a selection and the AI's suggestions alike - as preview
 * charts, grouped by the node each hangs off. The same candidates are drawn in the graph, where they can also be
 * navigated to, compared and given supporting sub-nodes; accepting or declining one here or there is the same.
 */
export default function RepairPanel() {
  const { tableName } = useTableName();
  const { highlightedRowIds, highlightedCols } = useContext(SelectionContext);
  const { busy, repairError, repairLocked } = useRepair();
  const { candidates, acceptCandidate, declineCandidate, declineAll, busy: deciding, busyId } = useCandidates();
  const { serverNodesById } = usePgraph();
  // The current table's size, from the metrics its graph node already carries
  const totalRows = serverNodesById?.[tableName]?.data?.metrics?.row_count;

  // Candidates by the node they hang off, in the order they were staged
  const groups = new Map();
  candidates.forEach((node) => {
    const parent = node.data?.parent;
    if (!groups.has(parent)) groups.set(parent, []);
    groups.get(parent).push(node);
  });

  // The dock owns the panel chrome - tab strip, collapsing and resizing - so this renders bare content
  return (
      <div id="toolbox">
        <div className="repair-panel-title">
          Data Repair Panel
        </div>

        {/* ── Selection status ─────────────────────────────────────────── */}
        <div className="repair-selection-status">
          {selectionStatus(highlightedRowIds, highlightedCols, totalRows)}
        </div>

        {/* Nothing is repaired from a candidate until it is accepted */}
        {repairLocked && (
          <div className="repair-locked">
            {nodeName(tableName)} is a candidate. Accept it before repairing from it.
          </div>
        )}

        {/* ── Feedback ─────────────────────────────────────────────────── */}
        {busy && (
          <div className="repair-feedback-centered">
            Generating previews…
            <div className="repair-loading-bar-track">
              <div className="repair-loading-bar-fill" />
            </div>
          </div>
        )}
        {repairError && (
          <div className="repair-error">
            Error: {repairError}
          </div>
        )}

        {/* ── Candidates, by the node they hang off ─────────────────────── */}
        <div id="preview-area" className="toolbox-preview-area">
          {candidates.length === 0 && !busy && (
            <div className="repair-feedback-centered">No candidates staged. Select rows and press Repair.</div>
          )}
          {[...groups].map(([parent, nodes]) => (
            <div key={parent} className="repair-candidate-group">
              <div className="repair-candidate-group-head">
                <span>From {nodeName(parent)}</span>
                <button
                  type="button"
                  className="repair-candidate-btn"
                  onClick={() => declineAll(parent)}
                  disabled={deciding}
                  title={`Decline every candidate under ${nodeName(parent)}`}
                >
                  Decline all
                </button>
              </div>
              {nodes.map((node) => {
                const candidate = node.data.candidate ?? {};
                return (
                  <div key={node.id} className="repair-candidate">
                    <PreviewCard
                      label={candidateLabel(node)}
                      tableName={node.id}
                      cols={candidate.cols ?? []}
                      errorColors={ERROR_COLORS}
                      chartType={candidate.chart_type}
                    />
                    <div className="repair-candidate-actions">
                      <button
                        type="button"
                        className="repair-candidate-btn repair-candidate-btn--accept"
                        onClick={() => acceptCandidate(node.id)}
                        disabled={deciding}
                        title="Accept this wrangle and cement it into the graph"
                      >
                        {busyId === node.id ? "Working…" : "Accept"}
                      </button>
                      <button
                        type="button"
                        className="repair-candidate-btn"
                        onClick={() => declineCandidate(node.id)}
                        disabled={deciding}
                        title="Decline this candidate"
                      >
                        Decline
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
  );
}
