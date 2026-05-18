import { Handle, Position } from "@xyflow/react";
import PreviewCard from "../panels/PreviewCard.jsx";
import { errorColors } from "../store/errorColors.js";
import "../styles/Nodes.css";

export function PlanStepShadow({ data, isConnectable }) {
    const step = data.step || {};
    const skipped = step.skipped || !step.preview_table;
    const stop = (e) => e.stopPropagation();

    return (
        <>
            <Handle type="target" position={Position.Top} isConnectable={isConnectable} />
            <div className="shadow-node plan-step-shadow" onClick={stop}>
                <div className="shadow-node-label">{data.label}</div>
                <div className="shadow-node-op">{step.op}{step.column ? ` · ${step.column}` : ""}</div>
                {skipped ? (
                    <div className="plan-step-skipped">{step.note || "no-op at this step"}</div>
                ) : (
                    <>
                        <div className="shadow-node-preview-pair">
                            <PreviewCard
                                label="before"
                                tableName={step.source_table}
                                cols={[step.column]}
                                errorColors={errorColors}
                                chartType="histogram"
                            />
                            <PreviewCard
                                label="after"
                                tableName={step.preview_table}
                                cols={[step.column]}
                                errorColors={errorColors}
                                chartType="histogram"
                            />
                        </div>
                        <div className="shadow-node-deltas">
                            {(step.deltas || []).map((d) => {
                                const change = d.errors_after - d.errors_before;
                                const cls = change < 0 ? "shadow-node-delta--good"
                                    : change > 0 ? "shadow-node-delta--bad" : "";
                                const arrow = change < 0 ? "↓" : change > 0 ? "↑" : "·";
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
                    </>
                )}
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        </>
    );
}
