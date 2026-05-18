import { Handle, Position } from "@xyflow/react";
import { useLLMOrchestrator } from "../store/LLMOrchestratorContext.jsx";
import "../styles/Nodes.css";

export function PlanShadowNode({ id, data, isConnectable }) {
    const {
        acceptShadow, rejectShadow, requestPreview,
        status, lastError, activePreview, previewLoading,
    } = useLLMOrchestrator();
    const plan = data.proposal || {};
    const steps = plan.steps || [];
    const isMaterializing = status === "materializing";
    const isPreviewing = activePreview?.shadowId === id && activePreview?.kind === "plan";

    const stop = (e) => e.stopPropagation();

    return (
        <>
            <Handle type="target" position={Position.Top} isConnectable={isConnectable} />
            <div className="shadow-node plan-shadow-node" onClick={stop}>
                <div className="shadow-node-label">{data.label}</div>
                <div className="shadow-node-op">{steps.length}-step plan</div>
                {plan.rationale && (
                    <div className="shadow-node-rationale" title={plan.rationale}>
                        {plan.rationale}
                    </div>
                )}
                <ol className="plan-shadow-steps">
                    {steps.map((s, i) => (
                        <li key={i}>
                            <span className="plan-step-op">{s.op}</span>{" "}
                            <span className="plan-step-col">{s.params?.column}</span>
                            {s.name && <div className="plan-step-name">{s.name}</div>}
                        </li>
                    ))}
                </ol>
                <div className="shadow-node-buttons">
                    <button
                        className="shadow-node-btn"
                        onClick={(e) => { stop(e); requestPreview(id); }}
                        disabled={isMaterializing || previewLoading}
                    >
                        {isPreviewing ? "Hide" : (previewLoading ? "…" : "Preview")}
                    </button>
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
                {isPreviewing && (
                    <div className="plan-preview-hint">Step previews shown below</div>
                )}
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        </>
    );
}
