import { BaseEdge, getStraightPath, useInternalNode } from "@xyflow/react";

/* Where a line from a node's centre toward a point leaves the node's box */
function borderPoint(node, toward) {
    const { x, y } = node.internals.positionAbsolute;
    const halfWidth = node.measured.width / 2;
    const halfHeight = node.measured.height / 2;
    const centre = { x: x + halfWidth, y: y + halfHeight };
    const dx = toward.x - centre.x;
    const dy = toward.y - centre.y;
    if (!dx && !dy) return centre;
    const scale = 1 / Math.max(Math.abs(dx) / halfWidth, Math.abs(dy) / halfHeight);
    return { x: centre.x + dx * scale, y: centre.y + dy * scale };
}

const centreOf = (node) => ({
    x: node.internals.positionAbsolute.x + node.measured.width / 2,
    y: node.internals.positionAbsolute.y + node.measured.height / 2,
});

/**
 * An edge in the graph's analysis mode: a straight line from a parent to its child, centre to centre and cut
 * off where it meets each node's box. In analysis mode a child can sit in any direction from its parent, so
 * the handles a tree layout draws from - out of the bottom, into the top - would send the line the wrong way.
 * This is React Flow's floating-edge pattern, and it works the same for the dots and for the full cards.
 */
export default function AnalysisEdge({ id, source, target, markerEnd, style, interactionWidth }) {
    const from = useInternalNode(source);
    const to = useInternalNode(target);
    // Until both ends are measured there is no box to cut the line at
    if (!from?.measured?.width || !to?.measured?.width) return null;

    const start = borderPoint(from, centreOf(to));
    const end = borderPoint(to, centreOf(from));
    const [path] = getStraightPath({ sourceX: start.x, sourceY: start.y, targetX: end.x, targetY: end.y });
    return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={interactionWidth}/>;
}
