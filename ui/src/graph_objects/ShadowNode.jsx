import { Handle, Position } from "@xyflow/react";
import { useLLMOrchestrator } from "../store/LLMOrchestratorContext.jsx";
import "../styles/Nodes.css";

export function ShadowNode({ id, data, isConnectable }) {
    const { acceptShadow, rejectShadow, status, lastError } = useLLMOrchestrator();
    const proposal = data.proposal || {};
    const isMaterializing = status === "materializing";

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
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        </>
    );
}
