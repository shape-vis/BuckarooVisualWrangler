import { Handle, Position } from "@xyflow/react";
import { useLLMOrchestrator } from "../store/LLMOrchestratorContext.jsx";
import PreviewCard from "../panels/PreviewCard.jsx";
import { errorColors } from "../store/errorColors.js";
import "../styles/Nodes.css";

export function ShadowNode({ id, data, isConnectable }) {
    const {
        acceptShadow, rejectShadow, requestPreview,
        status, lastError, activePreview, previewLoading,
    } = useLLMOrchestrator();
    const proposal = data.proposal || {};
    const isMaterializing = status === "materializing";
    const isManual = proposal.op === "manual-wrangle";
    const isPreviewing = activePreview?.shadowId === id;

    const stop = (e) => e.stopPropagation();

    return (
        <>
            <Handle type="target" position={Position.Top} isConnectable={isConnectable} />
            <div className="shadow-node" onClick={stop}>
                <div className="shadow-node-label">{data.label}</div>
                <div className="shadow-node-op">{proposal.op}</div>
                {proposal.rationale && (
                    <div className="shadow-node-rationale" title={proposal.rationale}>
                        {proposal.rationale}
                    </div>
                )}
                <div className="shadow-node-buttons">
                    {!isManual && (
                        <button
                            className="shadow-node-btn"
                            onClick={(e) => { stop(e); requestPreview(id); }}
                            disabled={isMaterializing || previewLoading}
                        >
                            {isPreviewing ? "Hide" : (previewLoading ? "…" : "Preview")}
                        </button>
                    )}
                    <button
                        className="shadow-node-btn shadow-node-btn--accept"
                        onClick={(e) => { stop(e); acceptShadow(id); }}
                        disabled={isMaterializing}
                    >
                        {isMaterializing ? "Working…" : "Accept"}
                    </button>
                    <button
                        className="shadow-node-btn"
                        onClick={(e) => { stop(e); rejectShadow(id); }}
                        disabled={isMaterializing}
                    >
                        Dismiss
                    </button>
                </div>
                {status === "error" && lastError && (
                    <div className="shadow-node-error" title={lastError}>{lastError}</div>
                )}
                {isPreviewing && activePreview && (
                    <div className="shadow-node-preview nodrag" onMouseDown={stop}>
                        <div className="shadow-node-preview-pair">
                            <PreviewCard
                                label={`${activePreview.column} · before`}
                                tableName={data.parentNodeId}
                                cols={[activePreview.column]}
                                errorColors={errorColors}
                                chartType="histogram"
                            />
                            <PreviewCard
                                label={`${activePreview.column} · after`}
                                tableName={activePreview.previewTable}
                                cols={[activePreview.column]}
                                errorColors={errorColors}
                                chartType="histogram"
                            />
                        </div>
                        <div className="shadow-node-deltas">
                            <div className="shadow-node-deltas-title">Error count change</div>
                            {activePreview.deltas.map((d) => {
                                const change = d.errors_after - d.errors_before;
                                const arrow = change < 0 ? "↓" : change > 0 ? "↑" : "·";
                                const cls = change < 0
                                    ? "shadow-node-delta--good"
                                    : change > 0 ? "shadow-node-delta--bad" : "";
                                return (
                                    <div key={d.column} className={`shadow-node-delta ${cls}`}>
                                        <span className="shadow-node-delta-col">{d.column}</span>
                                        <span className="shadow-node-delta-val">
                                            {arrow} {d.errors_before} → {d.errors_after}
                                            {d.pct_change != null && ` (${d.pct_change > 0 ? "+" : ""}${d.pct_change}%)`}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        </>
    );
}
