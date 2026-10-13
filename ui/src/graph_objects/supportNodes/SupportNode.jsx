import {useState} from "react";
import {Handle, NodeResizer, Position} from "@xyflow/react";
import {usePgraph} from "../../store/PGraphContext.jsx";
import {anchorOf, getSupportType, recordSizeOf} from "./registry.js";
import {useSupportOpenContext} from "./supportOpen.js";
import {EDGE_GAP} from "./supportLayout.js";
import "../../styles/Nodes.css";

// Smaller than this and nothing a resizable kind draws still reads
const MIN_RESIZED = {width: 180, height: 120};

/**
 * The one React Flow node type behind every supporting sub-node. The frame - its name, the way to remove
 * it, the link to its host - is the same for all of them; what it draws inside is its kind's Body, handed
 * the host node so it can show anything about it. A kind that holds a plot also gets an Open in the header,
 * which takes it to the Plots view - see supportOpen.js.
 *
 * A side sub-node faces its host: one on the left links in on its right side, and the reverse. An edge
 * sub-node has no link to draw - React Flow cannot join a node to an edge - so it carries a short stub of
 * its own, pointing back across the gap at the edge's label.
 */
export function SupportNode({data, width, height}) {
    const {removeSupportNode, updateSupportNode, serverNodesById} = usePgraph();
    const {record} = data;
    const type = getSupportType(record.kind);
    const Body = type?.Body;
    /* React Flow hands over the width and height a resize in progress has reached; otherwise it is the size the
       record says. Once the drag ends the record keeps it, and the layout makes room for it.
       Until it has measured a node, React Flow hands over 0 for both, not undefined - and a node drawn 0 by 0
       is never measured, so it would stay hidden for good. Every redraw starts unmeasured (a wrangle redraws
       them all), so 0 has to fall back to the record's size like a missing value does. */
    const recorded = recordSizeOf(record);
    const size = {width: width || recorded.width, height: height || recorded.height};
    const resizable = type?.resizable?.(record) ?? false;
    const onEdge = anchorOf(record) === "edge";
    const host = serverNodesById[record.hostId];

    // Open, for a kind that holds a plot - async, since an error plot may first make its node the current one
    const openContext = useSupportOpenContext();
    const canOpen = Boolean(type?.open) && (type.canOpen?.({record, host}) ?? true);
    const [opening, setOpening] = useState(false);
    const open = async (event) => {
        event.stopPropagation();
        setOpening(true);
        try {
            await type.open(record, openContext);
        } finally {
            setOpening(false);
        }
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
                    onResizeEnd={(event, params) => updateSupportNode(record.id, {
                        size: {width: Math.round(params.width), height: Math.round(params.height)},
                    })}
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
                    {canOpen && (
                        <button
                            type="button"
                            className="support-node-open"
                            title={type.openTitle ?? "Open in the Plots view"}
                            onClick={open}
                            disabled={opening}
                        >
                            {opening ? "Opening…" : "Open ↗"}
                        </button>
                    )}
                    <button
                        type="button"
                        className="support-node-remove"
                        title="Remove this sub-node"
                        aria-label="Remove this sub-node"
                        onClick={(event) => { stop(event); removeSupportNode(record.id); }}
                    >×</button>
                </div>
                {Body && <Body record={record} host={host} />}
            </div>
        </div>
    );
}
