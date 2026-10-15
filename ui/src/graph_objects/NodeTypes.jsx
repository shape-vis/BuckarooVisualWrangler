import {useCallback, useState} from "react";
import "../styles/Nodes.css";
import "../styles/AnalysisDot.css";
import { Handle, Position} from "@xyflow/react";
import {IconButton} from "../elements/Buttons.jsx";
import {usePgraph} from "../store/PGraphContext.jsx";
import {useAISuggestions} from "../store/AISuggestionsContext.jsx";
import {aiAvailability} from "../store/aiAvailability.js";
import {NodeMetrics} from "./NodeMetrics.jsx";
import {SupportBadges} from "./supportNodes/SupportBadges.jsx";
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

// "supporting node", or "3 supporting nodes"
function supportNoun(count) {
    if (count === 1) return "supporting node";
    return `${count} supporting nodes`;
}

/**
 * The buttons every node carries, always showing: the AI's repairs, the support-nodes window, and - once the node
 * has supporting sub-nodes - the eye that hides them all, each leaving its badge on the node, and shows them
 * again. Quality metrics are not among them: they are added as a supporting sub-node from the support button.
 *
 * Takes the node's id rather than reading data.label, because the label is only what the card displays -
 * the id is the table name the server knows the node by.
 */
export function NodeTools( { nodeId } ){
    const { isCandidate, graphMode, openSupportWindow, supportNodes, isSupportShown,
            toggleSupportHidden } = usePgraph();
    const ai = useAISuggestions();

    const askAI = useCallback(() => ai?.requestSuggestions(nodeId), [ai, nodeId]);

    /* Suggestions are staged as candidates under this node, alongside any already there. Nothing can be
       wrangled from a candidate until it is accepted, so a candidate's own AI button is off; and in analysis
       mode the new candidates would land somewhere the tree is not drawn. */
    const analysing = graphMode === "analysis";
    const aiState = aiAvailability({
        configured: ai?.configured,
        locked: isCandidate(nodeId),
        analysing,
        busy: ai?.busy,
    });

    // Off in analysis mode: sub-nodes are hidden on the plot, so adding one there would show nothing
    const openSupport = useCallback(() => openSupportWindow(nodeId), [openSupportWindow, nodeId]);

    /* The eye: while any of this node's sub-nodes shows, it hides them all, each leaving its badge; once none
       does, it shows them all again. Offered once the node has some. */
    const ofNode = supportNodes.filter((record) => record.hostId === nodeId);
    const hasSupport = ofNode.length > 0;
    const shownCount = ofNode.filter((record) => isSupportShown(record)).length;
    const anyShown = shownCount > 0;
    const toggleSupport = useCallback(() => toggleSupportHidden(nodeId), [toggleSupportHidden, nodeId]);

    let visibilityDetail;
    if (analysing) {
        visibilityDetail = "Supporting nodes are hidden on the plot - switch to wrangling mode";
    } else if (anyShown) {
        visibilityDetail = `Hide this node's ${supportNoun(shownCount)} - each leaves a badge on the node`;
    } else {
        visibilityDetail = `Show this node's ${supportNoun(ofNode.length)} again`;
    }

    const asking = ai?.pendingNode === nodeId;

    return (
        // stopPropagation on click does not stop dblclick, and React Flow navigates the app on a node
        // double-click - so a quick double-tap on any of these would move the current table out from under the user
        <div className="note-node-icon-container" onDoubleClick={(e) => e.stopPropagation()}>
            <NodeButton
                className="node-sub-button-ai"
                label="AI repairs"
                detail={aiState.detail}
                onClick={askAI}
                disabled={aiState.blocked}
            >
                <img
                    src="/images/icons/sparkle.svg"
                    alt=""
                    className={`nodeButtonSvgIcon ${asking ? "nodeButtonSvgIcon--active" : ""}`}
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
                    label={anyShown ? "Hide supporting nodes" : "Show supporting nodes"}
                    detail={visibilityDetail}
                    onClick={toggleSupport}
                    disabled={analysing}
                >
                    <img
                        src={anyShown ? "/images/icons/eye.svg" : "/images/icons/eye-off.svg"}
                        alt=""
                        className="nodeButtonSvgIcon"
                    />
                </NodeButton>
            )}
        </div>
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
    const { expandRun } = usePgraph();
    const [expanded, setExpanded] = useState(false);

    const headId = String(data.head).split("_")[0];
    const tailId = String(data.tail).split("_")[0];

    return (
        <>
            <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>
            <div>
                <div className="node-tools">
                    <h3 title={data.run?.join(" → ")}>{data.label}</h3>
                    <div className={"collapsed-node-range"}>
                        {headId} … {tailId}
                    </div>
                    <div className="note-node-icon-container">
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
    );
}

/**
 * The card for a table in the wrangling tree. The root has no parent, so it is drawn without the
 * handle an incoming edge would attach to; otherwise every card is the same.
 */
function NoteCard( { id, data, isConnectable, hasParent } ){
    return (
        <>
            {hasParent && <Handle type="target" position={Position.Top} isConnectable={isConnectable}/>}
            <ComparisonBadge role={data.comparisonRole} />
            <div>
                <div className="node-tools">
                    <SupportBadges hostId={id} />
                    <h3>{data.label}</h3>
                    <NodeTools nodeId={id} />
                </div>
            </div>
            <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} />
            <SupportHandles />
        </>
    );
}

export function NoteNode( { id, data, isConnectable } ){
    return <NoteCard id={id} data={data} isConnectable={isConnectable} hasParent={true} />;
}

export function RootNoteNode( { id, data, isConnectable } ){
    return <NoteCard id={id} data={data} isConnectable={isConnectable} hasParent={false} />;
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
