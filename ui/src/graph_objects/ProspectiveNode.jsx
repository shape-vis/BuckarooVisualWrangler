import { Handle, Position } from "@xyflow/react";
import { useAISuggestions } from "../store/AISuggestionsContext.jsx";
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

/**
 * A wrangle the AI is proposing: drawn where the resulting node would go, but dashed, and gone
 * again the moment it is accepted or declined.
 *
 * Carries a source handle deliberately: nothing branches off a suggestion, because until it is
 * accepted there is no table for anything to branch from.
 *
 * The row count is not the model's claim - the server resolved it from the flagged rows the
 * wrangle will actually touch - so it is worth showing plainly.
 */
export function ProspectiveNode({ id, data, isConnectable }) {
    const { acceptSuggestion, declineSuggestion, busySuggestionId, busy } = useAISuggestions();

    const isBusy = busySuggestionId === id;
    const rows = data.rowCount === 1 ? "1 flagged row" : `${data.rowCount} flagged rows`;
    const errorLabel = ERROR_TYPES[data.errorType] ?? data.errorType;

    const tooltip = (event) => showTooltip(
        `<strong>${escapeHtml(data.label)}</strong><br/>`
        + `${escapeHtml(rows)} · ${escapeHtml(errorLabel)}<br/>`
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
                    <span
                        className="prospective-node-swatch"
                        style={{ backgroundColor: errorColors(data.errorType) }}
                    />
                    <span className="prospective-node-label">{data.label}</span>
                </div>

                <div className="prospective-node-rows">{rows}</div>

                <div className="prospective-node-reason">
                    {truncateText(data.reason, 90)}
                </div>

                <div className="prospective-node-buttons">
                    <button
                        className="prospective-node-btn prospective-node-btn--accept"
                        onClick={(e) => { stop(e); acceptSuggestion(id); }}
                        disabled={busy}
                        title="Run this wrangle and cement it into the graph"
                    >
                        {isBusy ? "Working…" : "Accept"}
                    </button>
                    <button
                        className="prospective-node-btn"
                        onClick={(e) => { stop(e); declineSuggestion(id); }}
                        disabled={busy}
                        title="Dismiss this suggestion"
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
