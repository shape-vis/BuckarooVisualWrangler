import { Handle, Position } from "@xyflow/react";
import { useAISuggestions } from "../store/AISuggestionsContext.jsx";
import { useRepair } from "../store/RepairContext.jsx";
import PreviewCard from "../panels/PreviewCard.jsx";
import { ERROR_TYPES, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import { showTooltip, moveTooltip, hideTooltip } from "../utils/visCommon.jsx";
import "../styles/Nodes.css";

/* The reason comes from a language model, and showTooltip writes it as html. */
function escapeHtml(text) {
    return String(text ?? "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* What each source calls its candidates, and how the node hands accept and decline back to it. An AI
   suggestion counts the flagged rows its wrangle will touch; a repair, the rows the user selected. */
const SOURCES = {
    ai: { tag: "AI", rowNoun: "flagged" },
    repair: { tag: "Repair", rowNoun: "selected" },
};

function useSourceActions(source) {
    const ai = useAISuggestions();
    const repair = useRepair();
    if (source === "repair") {
        return { accept: repair.acceptRepair, decline: repair.declineRepair, busyId: repair.busyRepairId, busy: repair.busy };
    }
    return { accept: ai.acceptSuggestion, decline: ai.declineSuggestion, busyId: ai.busySuggestionId, busy: ai.busy };
}

/**
 * A wrangle that has not happened yet - an AI suggestion, or a way of repairing the rows selected in
 * the plots: drawn where the resulting node would go, but dashed, and gone again the moment it is
 * accepted or declined. Accepting runs it through the source it came from.
 *
 * Carries a source handle deliberately: nothing branches off a suggestion, because until it is
 * accepted there is no table for anything to branch from.
 *
 * The row count is not the model's claim - the server resolved it from the flagged rows the
 * wrangle will actually touch - so it is worth showing plainly.
 */
export function ProspectiveNode({ id, data, isConnectable }) {
    const source = SOURCES[data.source] ?? SOURCES.ai;
    const { accept, decline, busyId, busy } = useSourceActions(data.source);

    const isBusy = busyId === id;
    const rows = data.rowCount === 1 ? `1 ${source.rowNoun} row` : `${data.rowCount} ${source.rowNoun} rows`;
    // A repair is of whatever the user selected, so it names no error type
    const errorLabel = data.errorType ? (ERROR_TYPES[data.errorType] ?? data.errorType) : null;

    const tooltip = (event) => showTooltip(
        `<strong>${escapeHtml(data.label)}</strong><br/>`
        + `${escapeHtml(rows)}${errorLabel ? ` · ${escapeHtml(errorLabel)}` : ""}<br/>`
        + `${escapeHtml(data.reason)}`,
        event,
    );

    // Keep clicks and drags inside the node from reaching the pane behind it
    const stop = (event) => event.stopPropagation();

    return (
        <>
            <Handle type="target" position={Position.Top} isConnectable={isConnectable} />
            <div
                className="prospective-node nodrag"
                onMouseEnter={tooltip}
                onMouseMove={moveTooltip}
                onMouseLeave={hideTooltip}
                onClick={stop}
                onDoubleClick={stop}
            >
                <div className="prospective-node-title">
                    <span className={`prospective-node-source prospective-node-source--${data.source ?? "ai"}`}>
                        {source.tag}
                    </span>
                    {data.errorType && (
                        <span
                            className="prospective-node-swatch"
                            style={{ backgroundColor: errorColors(data.errorType) }}
                        />
                    )}
                    <span className="prospective-node-label">{data.label}</span>
                </div>

                <div className="prospective-node-rows">{rows}</div>

                <div className="prospective-node-reason">
                    {truncateText(data.reason, 90)}
                </div>

                {/* A repair has a real preview table behind it, so it shows the chart the Repair panel shows
                    for it - running it is still Accept below, not a button of the chart's own */}
                {data.previewTable && (
                    <div className="prospective-node-chart">
                        <PreviewCard
                            tableName={data.previewTable}
                            cols={data.cols ?? []}
                            errorColors={errorColors}
                            chartType={data.chartType}
                        />
                    </div>
                )}

                <div className="prospective-node-buttons">
                    <button
                        className="prospective-node-btn prospective-node-btn--accept"
                        onClick={(e) => { stop(e); accept(id); }}
                        disabled={busy}
                        title="Run this wrangle and cement it into the graph"
                    >
                        {isBusy ? "Working…" : "Accept"}
                    </button>
                    <button
                        className="prospective-node-btn"
                        onClick={(e) => { stop(e); decline(id); }}
                        disabled={busy}
                        title="Dismiss this candidate"
                    >
                        Decline
                    </button>
                </div>
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable}
                    style={{ visibility: "hidden" }} />
        </>
    );
}
