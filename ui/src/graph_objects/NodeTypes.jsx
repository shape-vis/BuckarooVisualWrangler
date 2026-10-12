import {useCallback, useState} from "react";
import "../styles/Nodes.css"
import { Handle, Position} from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useAISuggestions} from "../store/AISuggestionsContext.jsx";
import {CANDIDATE_LOCKED} from "../store/RepairContext.jsx";
import {NodeMetrics} from "./NodeMetrics.jsx";
import {showTooltip, moveTooltip, hideTooltip} from "../utils/visCommon.jsx";
import "../styles/Buttons.css"


/**
 * Names a node's role in the current comparison. Floats above the node so it cannot be confused with
 * the node's own label, and so it costs the node no height in the dagre layout.
 */
export function ComparisonBadge( { role } ){
    if (!role) return null;

    return (
        <div className={`node-comparison-badge node-comparison-badge--${role}`}>
            {role === "current" ? "selection B" : "selection A"}
        </div>
    );
}

/**
 * A folded run's quality metrics, revealed by its magnifier. A real node shows its own as a supporting
 * sub-node instead - see supportNodes/QualityMetricsSupport.jsx.
 *
 * Floats below the node rather than growing it: dagre lays the graph out from fixed node sizes, so a
 * node that actually grew would overlap the rank beneath it. This hangs in the gap RANK_SEPARATION
 * already leaves there.
 */
function NodeMetricsExpansion( { metrics } ){
    return (
        <div className="node-metrics">
            <NodeMetrics metrics={metrics} />
        </div>
    );
}

/**
 * One of a node's icon buttons, named in the shared tooltip on hover: what it is, then what it does now -
 * or, while it is disabled, why.
 *
 * The tooltip hangs off a wrapper rather than the button, because a disabled button fires no mouse events,
 * and the AI button spends most of its life disabled with a reason worth reading. Pressing hides the tooltip,
 * since the button may open something over it or change what it would say.
 */
function NodeButton( { label, detail, children, ...button } ){
    return (
        <span
            className="node-button-tip"
            onMouseEnter={(event) => showTooltip(`<strong>${label}</strong><br/>${detail}`, event)}
            onMouseMove={moveTooltip}
            onMouseLeave={hideTooltip}
            onMouseDown={hideTooltip}
        >
            <IconButton {...button} ariaLabel={label}>{children}</IconButton>
        </span>
    );
}

/**
 * The buttons every node carries. Its quality metrics are a supporting sub-node now, added from the
 * support button, rather than a readout of their own.
 *
 * Takes the node's id rather than reading data.label, because the layout truncates a long label
 * down to the three-character node id - so the label is not a table name you can send anywhere.
 */
export function NodeTools( { nodeId } ){
    const { startBranchSelection, isCandidate, graphMode, openSupportModal,
            supportCountByHost, hiddenSupportHosts, toggleSupportHidden, hideAllNodeSupports,
            hideAllEdgeSupports } = usePgraph();
    const ai = useAISuggestions();

    const openQuality = useCallback(() => startBranchSelection(), [startBranchSelection]);

    const askAI = useCallback(() => ai?.requestSuggestions(nodeId), [ai, nodeId]);

    /* Suggestions are staged as candidates under this node, alongside any already there. Nothing can be
       wrangled from a candidate until it is accepted, so a candidate's own AI button is off; and in analysis
       mode the new candidates would land somewhere the tree is not drawn. */
    const analysing = graphMode === "analysis";
    const locked = isCandidate(nodeId);
    const aiBlocked = !ai?.configured || ai?.busy || analysing || locked;
    const aiTitle = !ai?.configured
        ? "AI suggestions are not configured - add GEMINI_API_KEY to .env"
        : locked
            ? `${CANDIDATE_LOCKED}.`
            : analysing
                ? "Switch to wrangling mode for suggestions"
                : ai?.busy ? "Working…" : "Suggest repairs for this node";

    // Off in analysis mode: sub-nodes are hidden on the plot, so adding one there would show nothing
    const openSupport = useCallback(() => openSupportModal(nodeId), [openSupportModal, nodeId]);

    /* Hiding and showing this node's sub-nodes - beside it and beside its incoming edge - offered once it has
       some. What the graph's own toggles already hide is not this button's to show, so it counts only the rest,
       and goes inert when there is none. */
    const counts = supportCountByHost.get(nodeId) ?? {side: 0, edge: 0};
    const hasSupport = counts.side + counts.edge > 0;
    const supportCount = (hideAllNodeSupports ? 0 : counts.side) + (hideAllEdgeSupports ? 0 : counts.edge);
    const supportHidden = hiddenSupportHosts.has(nodeId);
    const toggleSupport = useCallback(() => toggleSupportHidden(nodeId), [toggleSupportHidden, nodeId]);
    const supportNoun = supportCount === 1 ? "supporting node" : `${supportCount} supporting nodes`;

    // The row shows on hover, but stays up while one of its buttons is switched on, so that is never hidden
    const pinned = ai?.pendingNode === nodeId;

    return (
        <>
            {/* stopPropagation on click does not stop dblclick, and React Flow navigates the app
                on a node double-click - so a quick double-tap on any of these would move the
                current table out from under the user */}
            <div
                className={`note-node-icon-container ${pinned ? "note-node-icon-container--pinned" : ""}`}
                onDoubleClick={(e) => e.stopPropagation()}
            >
                <NodeButton
                    className="node-sub-button-chart"
                    label="Branch quality"
                    detail="Measure quality along a branch"
                    onClick={openQuality}
                >
                    <img src="/images/icons/trend.svg" alt="" className="nodeButtonSvgIcon" />
                </NodeButton>
                <NodeButton
                    className="node-sub-button-ai"
                    label="AI repairs"
                    detail={aiTitle}
                    onClick={askAI}
                    disabled={aiBlocked}
                >
                    <img
                        src="/images/icons/sparkle.svg"
                        alt=""
                        className={`nodeButtonSvgIcon ${ai?.pendingNode === nodeId ? "nodeButtonSvgIcon--active" : ""}`}
                    />
                </NodeButton>
                <NodeButton
                    className="node-sub-button-support"
                    label="Supporting nodes"
                    detail={analysing ? "Switch to wrangling mode to add supporting nodes" : "Add supporting nodes beside this node"}
                    onClick={openSupport}
                    disabled={analysing}
                >
                    <img src="/images/icons/support.svg" alt="" className="nodeButtonSvgIcon" />
                </NodeButton>
                {hasSupport && (
                    <NodeButton
                        className="node-sub-button-support-visibility"
                        label={supportHidden ? "Show supporting nodes" : "Hide supporting nodes"}
                        detail={analysing
                            ? "Supporting nodes are hidden on the plot - switch to wrangling mode"
                            : supportCount === 0
                                ? "This node's supporting nodes are hidden graph-wide - turn them back on at the graph's top left"
                                : `${supportHidden ? "Show" : "Hide"} this node's ${supportNoun}`}
                        onClick={toggleSupport}
                        disabled={analysing || supportCount === 0}
                    >
                        <img
                            src={supportHidden ? "/images/icons/eye-off.svg" : "/images/icons/eye.svg"}
                            alt=""
                            className="nodeButtonSvgIcon"
                        />
                    </NodeButton>
                )}
            </div>

            {/* While they are hidden, a pill on the card's corner keeps them from being forgotten. It floats,
                like the comparison badge, so it costs the layout nothing; clicking it shows them again. */}
            {supportHidden && supportCount > 0 && !analysing && (
                <button
                    type="button"
                    className="node-support-hidden-pill"
                    onClick={(event) => { event.stopPropagation(); toggleSupport(); }}
                    onDoubleClick={(event) => event.stopPropagation()}
                    onMouseEnter={(event) => showTooltip(`<strong>${supportCount} hidden</strong><br/>Click to show this node's ${supportNoun}`, event)}
                    onMouseMove={moveTooltip}
                    onMouseLeave={hideTooltip}
                    aria-label={`Show this node's ${supportNoun}`}
                >
                    +{supportCount}
                </button>
            )}
        </>
    );
}

/**
 * Where the links out to a node's supporting sub-nodes leave it: its left and right sides, since below it
 * is where its wrangles branch. Hidden; the link itself is the mark.
 *
 * Rendered after the node's bottom handle. An edge that names no handle - every edge of the tree - leaves
 * from a node's first source handle, so these must never come first.
 */
export function SupportHandles(){
    return (
        <>
            <Handle type="source" id="support-left" position={Position.Left}
                    isConnectable={false} className="support-handle" />
            <Handle type="source" id="support-right" position={Position.Right}
                    isConnectable={false} className="support-handle" />
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
                <div className={`note-node-icon-container ${expanded ? "note-node-icon-container--pinned" : ""}`}>
                    <NodeButton
                        className="node-sub-button-chart"
                        label="Run quality"
                        detail={`Plot quality across these ${data.run?.length} nodes`}
                        onClick={openQuality}
                    >
                        <img src="/images/icons/trend.svg" alt="" className="nodeButtonSvgIcon" />
                    </NodeButton>
                    <NodeButton
                        className="node-sub-button-inspect"
                        label="Quality metrics"
                        detail={expanded ? "Hide quality metrics" : "Show the run's resulting quality metrics"}
                        onClick={() => setExpanded((open) => !open)}
                    >
                        <img
                            src="/images/icons/inspect.svg"
                            alt=""
                            className={`nodeButtonSvgIcon ${expanded ? "nodeButtonSvgIcon--active" : ""}`}
                        />
                    </NodeButton>
                    <NodeButton
                        className="node-sub-button-expand"
                        label="Expand run"
                        detail={`Expand these ${data.run?.length} nodes`}
                        onClick={() => expandRun(id)}
                    >+</NodeButton>
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
                <NodeTools nodeId={id} />
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        <SupportHandles />
    </>
)
}

/**
 * A node in the graph's analysis mode, plotted as a dot at its drift and error. Its colour is its branch's,
 * a ring marks the current node and selection A, and its id is shown for root and the pair and on hover for
 * the rest. The label hangs outside the dot, so React Flow measures - and centres - the dot alone.
 *
 * The role comes in data rather than as the node's class: those classes style a card, and would paint a
 * box around the dot. The handles are invisible; analysis edges run centre to centre and do not use them.
 */
export function AnalysisDotNode( { data } ){
    const { color, role, label, showLabel, provisional } = data.analysis;
    return (
        <div
            className={[
                "analysis-dot",
                role ? `analysis-dot--${role}` : "",
                showLabel ? "analysis-dot--labelled" : "",
                // A staged candidate is hollow: it is on the plot, but not yet part of the graph
                provisional ? "analysis-dot--provisional" : "",
            ].filter(Boolean).join(" ")}
            style={{"--analysis-dot-color": color}}
        >
            <Handle type="target" position={Position.Top} className="analysis-handle" isConnectable={false}/>
            <span className="analysis-dot-label">{label}</span>
            <Handle type="source" position={Position.Bottom} className="analysis-handle" isConnectable={false}/>
        </div>
    );
}

export function RootNoteNode( { id, data, isConnectable } ){

return (
    <>
        <ComparisonBadge role={data.comparisonRole} />
        <div>
            <div className={"node-node-label"}>
                <h3>{data.label}</h3>
                <NodeTools nodeId={id} />
            </div>
        </div>
        <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
        <SupportHandles />
    </>
)
}
