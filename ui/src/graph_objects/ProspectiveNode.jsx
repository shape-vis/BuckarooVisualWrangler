import { Handle, NodeResizer, Position } from "@xyflow/react";
import { useCandidates } from "../store/CandidatesContext.jsx";
import { usePgraph } from "../store/PGraphContext.jsx";
import PreviewCard from "../panels/PreviewCard.jsx";
import { ERROR_TYPES, errorColors } from "../store/errorColors.js";
import { truncateText } from "../utils/textUtils.js";
import { showTooltip, moveTooltip, hideTooltip } from "../utils/visCommon.jsx";
import { escapeHtml } from "../utils/html.js";
import { CANDIDATE_SOURCES } from "../utils/candidates.js";
import { ComparisonBadge, NodeTools, SupportHandles } from "./NodeTypes.jsx";
import { SupportBadges } from "./supportNodes/SupportBadges.jsx";
import "../styles/ProspectiveNode.css";

// Smaller than this and its preview chart no longer reads; it starts larger
const MIN_SIZE = { width: 170, height: 300 };

/**
 * A candidate: a wrangle staged as a provisional node of the graph - a way of repairing the user's selection,
 * or a repair the AI suggested. Both look the same, show the same preview chart of their own table, and are
 * accepted and declined the same way; only the source tag and the reason differ.
 *
 * It is a node like any other - it carries the tools every node does, so it can be given supporting
 * sub-nodes, measured along a branch, navigated to and compared - except that nothing can be wrangled from it
 * until it is accepted. Dashed and violet, so it cannot be mistaken for a node that has joined the graph.
 *
 * The row count is not the model's claim - the server resolved it from the rows the wrangle touches - so it
 * is worth showing plainly.
 *
 * Its corners can be dragged to make it larger, and its preview chart with it - the graph makes room for the new
 * size (PGraphContext's candidateSizes).
 */
export function ProspectiveNode({ id, data, isConnectable }) {
    const candidate = data.candidate ?? {};
    const source = CANDIDATE_SOURCES[candidate.source] ?? CANDIDATE_SOURCES.repair;
    const { acceptCandidate, declineCandidate, busy, busyId } = useCandidates();
    const { setCandidateSize } = usePgraph();

    const isBusy = busyId === id;
    const rowCount = candidate.row_count ?? 0;
    const rows = rowCount === 1 ? `1 ${source.rowNoun} row` : `${rowCount.toLocaleString()} ${source.rowNoun} rows`;

    // A repair is of whatever the user selected, so it names no error type
    let errorLabel = null;
    if (candidate.error_type) {
        errorLabel = ERROR_TYPES[candidate.error_type] ?? candidate.error_type;
    }

    let rowsLine = escapeHtml(rows);
    if (errorLabel) {
        rowsLine += ` · ${escapeHtml(errorLabel)}`;
    }

    /* The reason can come from a language model, and showTooltip writes it as html, so all of it is escaped.
       A missing label or reason shows as nothing rather than as "undefined". */
    const labelText = escapeHtml(candidate.label ?? "");
    const nodeText = escapeHtml(data.label ?? "");
    const reasonText = escapeHtml(candidate.reason ?? "");
    const tooltip = (event) => showTooltip(
        `<strong>${labelText}</strong> · ${nodeText}<br/>`
        + `${rowsLine}<br/>`
        + `${reasonText}`,
        event,
    );

    /* Its buttons keep their clicks to themselves, so pressing one is never also a click on the node. The card
       itself lets clicks through to React Flow like any node's: that is how a branch is ended on it, and how a
       shift-click makes it selection A. A double-click navigates to it. */
    const stop = (event) => event.stopPropagation();

    return (
        <>
            <NodeResizer
                minWidth={MIN_SIZE.width}
                minHeight={MIN_SIZE.height}
                lineClassName="prospective-resize-line"
                handleClassName="prospective-resize-handle"
                onResizeEnd={(event, params) => setCandidateSize(id, {
                    width: Math.round(params.width),
                    height: Math.round(params.height),
                })}
            />
            <Handle type="target" position={Position.Top} isConnectable={isConnectable} />
            <ComparisonBadge role={data.comparisonRole} />
            <div className="prospective-node nodrag">
                <SupportBadges hostId={id} />
                {/* The full label and reason, on hovering the text they are cut short in - not the chart or buttons */}
                <div
                    className="prospective-node-text"
                    onMouseEnter={tooltip}
                    onMouseMove={moveTooltip}
                    onMouseLeave={hideTooltip}
                >
                    <div className="prospective-node-title">
                        <span className={`prospective-node-source prospective-node-source--${candidate.source ?? "repair"}`}>
                            {source.tag}
                        </span>
                        {candidate.error_type && (
                            <span
                                className="prospective-node-swatch"
                                style={{ backgroundColor: errorColors(candidate.error_type) }}
                            />
                        )}
                        <span className="prospective-node-label">{candidate.label}</span>
                        <span className="prospective-node-id">{data.label}</span>
                    </div>

                    <div className="prospective-node-rows">{rows}</div>

                    <div className="prospective-node-reason">
                        {truncateText(candidate.reason, 90)}
                    </div>
                </div>

                {/* Its own table's preview chart - for either source, since both are staged */}
                <div className="prospective-node-chart">
                    <PreviewCard
                        tableName={id}
                        cols={candidate.cols ?? []}
                        errorColors={errorColors}
                        chartType={candidate.chart_type}
                        fill
                    />
                </div>

                <div className="prospective-node-buttons">
                    <button
                        className="prospective-node-btn prospective-node-btn--accept"
                        onClick={(e) => { stop(e); acceptCandidate(id); }}
                        onDoubleClick={stop}
                        disabled={busy}
                        title="Accept this wrangle and cement it into the graph"
                    >
                        {isBusy ? "Working…" : "Accept"}
                    </button>
                    <button
                        className="prospective-node-btn"
                        onClick={(e) => { stop(e); declineCandidate(id); }}
                        onDoubleClick={stop}
                        disabled={busy}
                        title="Decline this candidate"
                    >
                        Decline
                    </button>
                </div>

                {/* The tools every node carries: branch quality, supporting nodes - its AI button stays off */}
                <div className="node-tools prospective-node-tools">
                    <NodeTools nodeId={id} />
                </div>
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
            <SupportHandles />
        </>
    );
}
