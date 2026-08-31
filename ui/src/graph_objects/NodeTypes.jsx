import {useCallback, useState} from "react";
import "../styles/Nodes.css"
import { Handle, Position} from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {ERROR_TYPES, ERROR_DIMENSIONS} from "../store/errorColors.js";
import "../styles/Buttons.css"


/**
 * Names a node's role in the current comparison. Floats above the node so it cannot be confused with
 * the node's own label, and so it costs the node no height in the dagre layout.
 */
function ComparisonBadge( { role } ){
    if (!role) return null;

    return (
        <div className={`node-comparison-badge node-comparison-badge--${role}`}>
            {role === "current" ? "comparator" : "baseline"}
        </div>
    );
}

/**
 * The node's quality metrics, revealed by the magnifier.
 *
 * Floats below the node rather than growing it: dagre lays the graph out from fixed node sizes, so a
 * node that actually grew would overlap the rank beneath it. This hangs in the gap RANK_SEPARATION
 * already leaves there.
 */
function NodeMetricsExpansion( { metrics } ){
    if (!metrics) {
        return (
            <div className="node-metrics">
                <div className="node-metrics-empty">No metrics</div>
            </div>
        );
    }

    return (
        <div className="node-metrics">
            <div className="node-metrics-rows">
                {ERROR_DIMENSIONS.map((dimension) => (
                    <div key={dimension} className="node-metrics-row" title={ERROR_TYPES[dimension]}>
                        <span className="node-metrics-swatch" data-error-type={dimension} />
                        <span className="node-metrics-value">
                            {((metrics.totals?.[dimension] ?? 0) * 100).toFixed(2)}%
                        </span>
                    </div>
                ))}
            </div>
            <div className="node-metrics-footer">
                {metrics.row_count} rows · {metrics.column_count} cols
            </div>
        </div>
    );
}

/** The buttons every node carries, and the metrics the magnifier reveals. */
function NodeTools( { data } ){
    const { startBranchSelection } = usePgraph();
    const [expanded, setExpanded] = useState(false);

    const openQuality = useCallback(() => startBranchSelection(), [startBranchSelection]);

    return (
        <>
            <div className={"note-node-icon-container"}>
                <IconButton
                    className="node-sub-button-chart"
                    title="Measure quality along a branch"
                    onClick={openQuality}
                >
                    <img src="/images/icons/trend.svg" alt="" className="nodeButtonSvgIcon" />
                </IconButton>
                <IconButton
                    className="node-sub-button-inspect"
                    title={expanded ? "Hide this node's quality metrics" : "Show this node's quality metrics"}
                    onClick={() => setExpanded((open) => !open)}
                >
                    <img
                        src="/images/icons/inspect.svg"
                        alt=""
                        className={`nodeButtonSvgIcon ${expanded ? "nodeButtonSvgIcon--active" : ""}`}
                    />
                </IconButton>
            </div>

            {expanded && <NodeMetricsExpansion metrics={data.metrics} />}
        </>
    );
}

export function NoteNode( { data, isConnectable } ){

return (
    <>
        <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <NodeTools data={data} />
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}

export function RootNoteNode( { data, isConnectable } ){

return (
    <>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <NodeTools data={data} />
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}
