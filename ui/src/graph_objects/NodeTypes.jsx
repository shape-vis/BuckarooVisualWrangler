import {useCallback, useState} from "react";
import "../styles/Nodes.css"
import { Handle, Position} from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useAISuggestions} from "../store/AISuggestionsContext.jsx";
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

/**
 * The buttons every node carries, and the metrics the magnifier reveals.
 *
 * Takes the node's id rather than reading data.label, because the layout truncates a long label
 * down to the three-character node id - so the label is not a table name you can send anywhere.
 */
function NodeTools( { nodeId, data } ){
    const { startBranchSelection, hasProspectiveNodes } = usePgraph();
    const ai = useAISuggestions();
    const [expanded, setExpanded] = useState(false);

    const openQuality = useCallback(() => startBranchSelection(), [startBranchSelection]);

    const askAI = useCallback(() => ai?.requestSuggestions(nodeId), [ai, nodeId]);

    /* One set of suggestions at a time. Rather than silently replacing the last node's, every AI
       button goes inert until the outstanding ones have been accepted or declined - so there is
       never a second dashed forest, and never a question of which is stale. */
    const aiBlocked = !ai?.configured || ai?.busy || hasProspectiveNodes;
    const aiTitle = !ai?.configured
        ? "AI suggestions are not configured - add GEMINI_API_KEY to .env"
        : hasProspectiveNodes
            ? "Accept or decline the current suggestions first"
            : ai?.busy ? "Working…" : "Suggest repairs for this node";

    return (
        <>
            {/* stopPropagation on click does not stop dblclick, and React Flow navigates the app
                on a node double-click - so a quick double-tap on any of these would move the
                current table out from under the user */}
            <div className={"note-node-icon-container"} onDoubleClick={(e) => e.stopPropagation()}>
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
                <IconButton
                    className="node-sub-button-ai"
                    title={aiTitle}
                    onClick={askAI}
                    disabled={aiBlocked}
                >
                    <img
                        src="/images/icons/sparkle.svg"
                        alt=""
                        className={`nodeButtonSvgIcon ${ai?.pendingNode === nodeId ? "nodeButtonSvgIcon--active" : ""}`}
                    />
                </IconButton>
            </div>

            {expanded && <NodeMetricsExpansion metrics={data.metrics} />}
        </>
    );
}

/**
 * Stands in for a run of nodes folded out of the view.
 *
 * Nothing is destroyed to make this: it carries the ids of the real nodes it hides, and reports the
 * metrics of the run's last node, since that is the state the run actually arrives at. Expanding
 * simply drops the run, and the real nodes are drawn again from data that never changed.
 */
export function CollapsedNode( { id, data, isConnectable } ){

const { expandRun, selectRunBranch } = usePgraph();
const [expanded, setExpanded] = useState(false);

// A folded run is a sequence, so its trajectory is the branch running through it, head to tail
const openQuality = useCallback(() => selectRunBranch(data.run), [selectRunBranch, data.run]);

return (
    <>
        <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
        <div>
            <div className={"node-node-label"}>
                <h3 title={data.run?.join(" → ")}>{data.label}</h3>
                <div className={"collapsed-node-range"}>
                    {String(data.head).split("_")[0]} … {String(data.tail).split("_")[0]}
                </div>
                <div className={"note-node-icon-container"}>
                    <IconButton
                        className="node-sub-button-chart"
                        title={`Plot quality across these ${data.run?.length} nodes`}
                        onClick={openQuality}
                    >
                        <img src="/images/icons/trend.svg" alt="" className="nodeButtonSvgIcon" />
                    </IconButton>
                    <IconButton
                        className="node-sub-button-inspect"
                        title={expanded ? "Hide quality metrics" : "Show the run's resulting quality metrics"}
                        onClick={() => setExpanded((open) => !open)}
                    >
                        <img
                            src="/images/icons/inspect.svg"
                            alt=""
                            className={`nodeButtonSvgIcon ${expanded ? "nodeButtonSvgIcon--active" : ""}`}
                        />
                    </IconButton>
                    <IconButton
                        className="node-sub-button-expand"
                        title={`Expand these ${data.run?.length} nodes`}
                        onClick={() => expandRun(id)}
                    >+</IconButton>
                </div>
            </div>
        </div>
        {expanded && <NodeMetricsExpansion metrics={data.metrics} />}
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}

export function NoteNode( { id, data, isConnectable } ){

return (
    <>
        <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <NodeTools nodeId={id} data={data} />
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}

export function RootNoteNode( { id, data, isConnectable } ){

return (
    <>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <NodeTools nodeId={id} data={data} />
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
    </>
)
}
