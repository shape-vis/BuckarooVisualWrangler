import {useState} from "react";
import {Handle, NodeResizer, Position} from "@xyflow/react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {anchorOf, getSupportType, recordSizeOf} from "./registry.js";
import {useSupportActionContext} from "./supportActions.js";
import {EDGE_GAP} from "./supportLayout.js";
import {fitsFullPlot} from "./compareView.js";
import "../../styles/SupportNode.css";

// Smaller than this and nothing a resizable kind draws still reads
const MIN_RESIZED = {width: 180, height: 120};

/**
 * The one React Flow node type behind every supporting sub-node. The frame - its name, the ways to minimise and
 * remove it, the link to its host - is the same for all of them; what it draws inside is its kind's Body, handed
 * the host node so it can show anything about it, and the size it is drawn at. A kind with an action gets its
 * button in the header: Repair on an error plot, Open on a plot the compare window can show - see
 * supportActions.js.
 *
 * Minimising hides it and leaves its badge on the host (SupportBadges), which brings it back. A kind that shows its
 * plot in miniature until it has room (the registry's zoom) gets a button beside it that expands it to the detailed
 * plot and back.
 *
 * A side sub-node faces its host: one on the left links in on its right side, and the reverse. An edge
 * sub-node has no link to draw - React Flow cannot join a node to an edge - so it carries a short stub of
 * its own, pointing back across the gap at the edge's label.
 */
export function SupportNode({data, width, height}) {
    const {removeSupportNode, updateSupportNode, minimizeSupportNode, serverNodesById, wranglingSupportId} = usePgraph();
    const {record} = data;
    const type = getSupportType(record.kind);
    const Body = type?.Body;
    /* Drawn at the size the record says. While the user drags its corner, React Flow hands over the width and
       height the drag has reached, and it follows them; once the drag ends the record keeps that size, and the
       layout makes room for it.
       Only during a drag: otherwise React Flow hands over the size it last measured - 0 before it has measured at
       all - and drawing at that would pin the node to it, so a size the record is given in code (an error plot
       growing to be wrangled on) would never show. */
    const [resizing, setResizing] = useState(false);
    let size = recordSizeOf(record);
    if (resizing && width && height) {
        size = {width, height};
    }
    const resizable = type?.resizable?.(record) ?? false;
    const onEdge = anchorOf(record) === "edge";
    const host = serverNodesById[record.hostId];

    /* The kind's action - async, since a repair may first make its node the current one. An error plot being
       wrangled on has its own Done instead. */
    const actionContext = useSupportActionContext();
    const action = type?.action;
    const wrangling = wranglingSupportId === record.id;
    const showAction = Boolean(action) && !wrangling;
    let blocked = null;
    if (showAction) {
        blocked = action.blockedReason?.(record, actionContext) ?? null;
    }
    const [running, setRunning] = useState(false);
    const runAction = async (event) => {
        event.stopPropagation();
        setRunning(true);
        try {
            await action.run(record, actionContext);
        } finally {
            setRunning(false);
        }
    };

    // Expanding to the detailed plot and back: between the kind's two sizes, by which the sub-node is drawn at now
    const zoom = type?.zoom;
    const expanded = fitsFullPlot(size);
    const toggleZoom = (event) => {
        event.stopPropagation();
        let next = zoom.detail;
        if (expanded) {
            next = zoom.miniature;
        }
        updateSupportNode(record.id, {size: next});
    };

    // Clicks inside a sub-node are its own; they must not select, navigate or end a branch behind it
    const stop = (event) => event.stopPropagation();

    // The edge stub reaches out of whichever side faces the edge
    let stubStyle = {width: EDGE_GAP, left: -EDGE_GAP};
    if (data.edgeSide === "left") {
        stubStyle = {width: EDGE_GAP, right: -EDGE_GAP};
    }

    return (
        <div className="support-node-shell" style={{width: size.width, height: size.height}}>
            {resizable && (
                <NodeResizer
                    minWidth={MIN_RESIZED.width}
                    minHeight={MIN_RESIZED.height}
                    lineClassName="support-resize-line"
                    handleClassName="support-resize-handle"
                    onResizeStart={() => setResizing(true)}
                    onResizeEnd={(event, params) => {
                        setResizing(false);
                        updateSupportNode(record.id, {
                            size: {width: Math.round(params.width), height: Math.round(params.height)},
                        });
                    }}
                />
            )}
            {/* Points back across the gap at the edge: from the left side of a sub-node right of its edge, and
                from the right side of one on the left */}
            {onEdge && (
                <span className="support-node-stub" style={stubStyle} />
            )}
            <div
                className={`support-node nodrag ${onEdge ? "support-node--edge" : ""}`}
                onClick={stop}
                onDoubleClick={stop}
            >
                {!onEdge && (
                    <Handle
                        type="target"
                        position={record.side === "left" ? Position.Right : Position.Left}
                        isConnectable={false}
                        className="support-handle"
                    />
                )}
                <div className="support-node-header">
                    <span className="support-node-title">{type?.label ?? record.kind}</span>
                    {showAction && (
                        <button
                            type="button"
                            className="support-node-open"
                            title={blocked ?? action.title}
                            onClick={runAction}
                            disabled={running || Boolean(blocked)}
                        >
                            {running ? action.busyLabel : action.label}
                        </button>
                    )}
                    {zoom && (
                        <button
                            type="button"
                            className={`support-node-zoom ${showAction ? "" : "support-node-zoom--first"}`}
                            title={expanded ? "Shrink to the miniature" : "Expand to the detailed plot"}
                            aria-label={expanded ? "Shrink to the miniature" : "Expand to the detailed plot"}
                            onClick={toggleZoom}
                        >
                            {expanded ? "⤡" : "⤢"}
                        </button>
                    )}
                    <button
                        type="button"
                        className={`support-node-minimize ${showAction || zoom ? "" : "support-node-minimize--first"}`}
                        title="Minimise to a badge on its node"
                        aria-label="Minimise this sub-node"
                        onClick={(event) => { stop(event); minimizeSupportNode(record.id); }}
                    >–</button>
                    <button
                        type="button"
                        className="support-node-remove"
                        title="Remove this sub-node"
                        aria-label="Remove this sub-node"
                        onClick={(event) => { stop(event); removeSupportNode(record.id); }}
                    >×</button>
                </div>
                {Body && <Body record={record} host={host} size={size} />}
            </div>
        </div>
    );
}
