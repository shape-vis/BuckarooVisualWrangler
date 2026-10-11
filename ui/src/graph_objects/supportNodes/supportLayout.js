/**
 * Where supporting sub-nodes sit. A kind anchors to one of two places (see registry.js):
 *
 *   side - beside its host, on its left or right only, because the space below a node belongs to the
 *          wrangles that branch from it - the side its branch leans to, unless its kind fixes one
 *   edge - beside the edge leading into its host: on the left of the edge when the host is a left child,
 *          on the right otherwise, so siblings' sub-nodes face away from each other rather than collide
 *
 * Sub-nodes are kept out of dagre. Dagre lays out the tree alone, but is told how much room they need - a
 * side sub-node widens its host (sideReserve), an edge one becomes the size of that edge's label
 * (edgeReserve) - so neighbours keep clear of them. They are then placed in that room as React Flow children
 * of their host, so their positions are relative to it and they move whenever it does.
 *
 * Each is drawn at its registry size, or the size the user resized it to - never a measured one, which is what
 * lets them be placed without measuring.
 */
import {isSupportId} from "../../utils/graphTopology.js";
import {anchorOf, getSupportType, recordSizeOf} from "./registry.js";

// From the host card to its sub-nodes, and between sub-nodes stacked on one side
const SIDE_GAP = 28;
const STACK_GAP = 8;

// From the right end of an edge's own label to a sub-node beside the edge - the stub that joins them
export const EDGE_GAP = 16;

/* About how wide and tall a card draws. Placement happens before React Flow has measured anything, so
   sub-nodes are set against this rather than the card's measured size - a card a little wider or narrower
   only changes the length of a link. */
const HOST_CARD = {width: 170, height: 80};

const sizeOf = recordSizeOf;
const onSide = (records) => records.filter((record) => anchorOf(record) === "side");
const onEdge = (records) => records.filter((record) => anchorOf(record) === "edge");

const stackHeight = (stack) => stack.reduce((sum, record) => sum + sizeOf(record).height, 0)
    + Math.max(0, stack.length - 1) * STACK_GAP;

// How far a side reaches out from the card: its widest sub-node and the gap, or nothing with none there
const sideWidth = (stack) => (stack.length ? Math.max(...stack.map((record) => sizeOf(record).width)) + SIDE_GAP : 0);

/* Which side of its host a side sub-node goes on. A kind may insist on one; otherwise ("auto") it follows its
   host's branch, as edge sub-nodes do - see branchSides - so a left child's sub-nodes face out to the left and
   a right child's to the right, rather than into the space between siblings. */
function sideOf(record, sides) {
    const fixed = getSupportType(record.kind)?.side;
    if (fixed === "left" || fixed === "right") return fixed;
    return sides.get(record.hostId) ?? "right";
}

// Each host's side sub-nodes, split by side
function bySide(records, sides) {
    const hosts = new Map();
    onSide(records).forEach((record) => {
        if (!hosts.has(record.hostId)) hosts.set(record.hostId, {left: [], right: []});
        hosts.get(record.hostId)[sideOf(record, sides)].push(record);
    });
    return hosts;
}

/**
 * The room each host needs beside it for its side sub-nodes, for dagre to reserve.
 *
 * @param sides - each host's branch side, from branchSides
 * @returns {Map<string, {left: number, right: number, height: number}>} by host id
 */
export function sideReserve(records, sides = new Map()) {
    const reserve = new Map();
    bySide(records, sides).forEach(({left, right}, hostId) => {
        reserve.set(hostId, {
            left: sideWidth(left),
            right: sideWidth(right),
            height: Math.max(stackHeight(left), stackHeight(right)),
        });
    });
    return reserve;
}

// The edge a host is drawn hanging from: the tree edge into it, from its parent or the run its parent is folded into
const incomingEdge = (drawnEdges, hostId) => drawnEdges.find((edge) => edge.target === hostId);

/**
 * Which way each host's branch leans, from where the tree put it: a host left of the node it hangs from is a
 * left child, and its sub-nodes - beside its edge, and beside it - go on the left. Anything else - a right
 * child, an only child straight below, the root - goes right. Needs a laid-out tree, so it is read from a
 * first layout pass.
 *
 * @returns {Map<string, "left" | "right">} by host id
 */
export function branchSides(records, layoutNodes, drawnEdges) {
    const positions = new Map(layoutNodes.map((node) => [node.id, node.position]));
    const sides = new Map();
    records.forEach((record) => {
        const edge = incomingEdge(drawnEdges, record.hostId);
        const from = edge && positions.get(edge.source);
        const to = positions.get(record.hostId);
        // Cards are one width, so comparing their left edges compares their middles
        sides.set(record.hostId, from && to && to.x < from.x - 1 ? "left" : "right");
    });
    return sides;
}

/**
 * The room each edge needs beside it, keyed by the edge's target - the host, and the side it goes on. Dagre is
 * given this as the edge's label, on that side, which also opens the gap between the two ranks to its height.
 *
 * @returns {Map<string, {width: number, height: number, side: "left" | "right"}>} by host id
 */
export function edgeReserve(records, sides = new Map()) {
    const reserve = new Map();
    onEdge(records).forEach((record) => reserve.set(record.hostId, {
        ...sizeOf(record),
        side: sides.get(record.hostId) ?? "right",
    }));
    return reserve;
}

const linkTo = (record, source, sourceHandle) => ({
    id: `support-edge:${record.id}`,
    source,
    sourceHandle,
    target: record.id,
    type: "straight",
    style: {stroke: "var(--support-accent)", strokeDasharray: "4 3"},
});

/**
 * The React Flow nodes and edges for every side sub-node whose host is drawn.
 *
 * Each side's sub-nodes stack top to bottom in the order they were added, centred on the host card's
 * middle, and sit against the card - a narrower one on the left is pushed right to meet it.
 */
function placeSideNodes(records, branch) {
    const nodes = [];
    const edges = [];

    bySide(records, branch).forEach((sides, hostId) => {
        ["left", "right"].forEach((side) => {
            const stack = sides[side];
            let y = HOST_CARD.height / 2 - stackHeight(stack) / 2;

            stack.forEach((record) => {
                const size = sizeOf(record);
                nodes.push({
                    id: record.id,
                    type: "supportNode",
                    parentId: hostId,
                    position: {x: side === "left" ? -SIDE_GAP - size.width : HOST_CARD.width + SIDE_GAP, y},
                    // A sub-node goes where its host does; dragging it alone would only detach it visually
                    draggable: false,
                    selectable: false,
                    data: {record},
                });
                edges.push(linkTo(record, hostId, `support-${side}`));
                y += size.height + STACK_GAP;
            });
        });
    });

    return {nodes, edges};
}

/**
 * The React Flow nodes for every edge sub-node whose edge is drawn.
 *
 * React Flow draws an edge from the middle of its source card's bottom to the middle of its target's top, and
 * puts the edge's label at the halfway point - so that is where the sub-node is set beside, just past the
 * label's end on its side. The source is whatever the edge is drawn from: a parent folded into a run is the run.
 * There is no link; a short stub on the sub-node itself points back at the label.
 */
// Where an edge sub-node goes, in the graph's own coordinates, or null when its edge is not drawn
function edgeBox(record, positions, drawnEdges, labelWidthOf, sides) {
    const edge = incomingEdge(drawnEdges, record.hostId);
    const from = edge && positions.get(edge.source);
    const to = positions.get(record.hostId);
    if (!from || !to) return null;

    const size = sizeOf(record);
    const side = sides.get(record.hostId) ?? "right";
    const middle = {
        x: (from.x + to.x) / 2 + HOST_CARD.width / 2,
        y: (from.y + HOST_CARD.height + to.y) / 2,
    };
    const clear = labelWidthOf(edge) / 2 + EDGE_GAP;
    return {
        record, side, to,
        x: side === "left" ? middle.x - clear - size.width : middle.x + clear,
        y: middle.y - size.height / 2,
        width: size.width,
        height: size.height,
    };
}

function placeEdgeNodes(records, positions, drawnEdges, labelWidthOf, sides) {
    return onEdge(records)
        .map((record) => edgeBox(record, positions, drawnEdges, labelWidthOf, sides))
        .filter(Boolean)
        .map(({record, side, to, x, y}) => ({
            id: record.id,
            type: "supportNode",
            parentId: record.hostId,
            position: {x: x - to.x, y: y - to.y},
            draggable: false,
            selectable: false,
            // Which side of the edge it is on, so its stub points back the right way
            data: {record, edgeSide: side},
        }));
}

// Clear space kept between two group boundaries once they have been pulled apart
const GROUP_GAP = 48;
// Shifting settles in a few passes; this only stops a pathological graph from looping
const MAX_SPREAD_PASSES = 40;

const overlaps = (a, b) => a.x0 < b.x1 + GROUP_GAP && b.x0 < a.x1 + GROUP_GAP && a.y0 < b.y1 && b.y0 < a.y1;

/* Each host's group as the graph would draw it from these positions: the box its boundary encloses, in the
   graph's own coordinates, and whether the box's left edge is its edge sub-node - which moves only half as far
   as its host does, since it sits halfway along the edge. */
function groupBoxes(records, positions, drawnEdges, labelWidthOf, sides) {
    const placed = [...placeSideNodes(records, sides).nodes,
        ...placeEdgeNodes(records, positions, drawnEdges, labelWidthOf, sides)];
    const boxes = new Map();
    groupBoundaries(placed, positions).forEach((group) => {
        const {hostId, width, height} = group.data;
        const edgeNode = placed.find((node) => node.parentId === hostId && anchorOf(node.data.record) === "edge");
        boxes.set(hostId, {
            hostId,
            host: positions.get(hostId),
            x0: group.position.x,
            y0: group.position.y,
            x1: group.position.x + width,
            y1: group.position.y + height,
            leftIsEdgeNode: Boolean(edgeNode) && edgeNode.position.x - GROUP_PADDING <= group.data.offset.x + 0.5,
        });
    });
    return [...boxes.values()];
}

/**
 * Pulls apart nodes whose group boundaries would overlap or crowd each other - a node with its sub-nodes,
 * beside it and beside its edge. Dagre reserves room for the sub-nodes, but edge sub-nodes follow the edge React
 * Flow draws - a curve whose middle is halfway between the two cards - rather than the one dagre routed, so
 * groups can still collide: a middle child's, with its edge sub-node out to the right, runs into its right-hand
 * sibling's.
 *
 * Wherever two groups come within GROUP_GAP of each other, the branch on the right moves over: its host, the
 * host's subtree, and everything right of the host at its depth or below, so nothing it passes is left behind on
 * top of it. When the moving group's left edge is its edge sub-node, which moves half as far as its host, the
 * host moves twice the shortfall. Repeats until every group has its gap.
 *
 * @returns the laid-out tree's nodes, moved where needed (new objects for the moved ones)
 */
export function spreadSupportGroups(records, layoutNodes, drawnEdges, labelWidthOf, sides) {
    let nodes = layoutNodes;
    if (new Set(records.map((record) => record.hostId)).size < 2) return nodes;

    const childrenOf = new Map();
    drawnEdges.forEach((edge) => {
        if (!childrenOf.has(edge.source)) childrenOf.set(edge.source, []);
        childrenOf.get(edge.source).push(edge.target);
    });
    const subtreeOf = (id) => {
        const found = new Set([id]);
        const queue = [id];
        while (queue.length) (childrenOf.get(queue.shift()) ?? []).forEach((child) => {
            if (!found.has(child)) { found.add(child); queue.push(child); }
        });
        return found;
    };

    for (let pass = 0; pass < MAX_SPREAD_PASSES; pass += 1) {
        const positions = new Map(nodes.map((node) => [node.id, node.position]));
        const boxes = groupBoxes(records, positions, drawnEdges, labelWidthOf, sides).sort((a, b) => a.x0 - b.x0);

        // The first crowded pair whose right-hand group hangs from the right-hand host, which is the one that can
        // move right without dragging the other along
        let pair = null;
        for (let i = 0; i < boxes.length && !pair; i += 1) {
            for (let j = i + 1; j < boxes.length && !pair; j += 1) {
                if (overlaps(boxes[i], boxes[j]) && boxes[j].host.x > boxes[i].host.x) pair = [boxes[i], boxes[j]];
            }
        }
        if (!pair) break;

        const [left, right] = pair;
        const shortfall = left.x1 + GROUP_GAP - right.x0;
        const shift = right.leftIsEdgeNode ? 2 * shortfall : shortfall;
        const pivot = right.host;
        const moving = subtreeOf(right.hostId);
        nodes = nodes.map((node) => (moving.has(node.id) || (node.position.y >= pivot.y - 1 && node.position.x >= pivot.x - 1)
            ? {...node, position: {x: node.position.x + shift, y: node.position.y}}
            : node));
    }
    return nodes;
}

/**
 * Every sub-node React Flow should draw, with the links to the side ones. Hosts must already be in React
 * Flow's node list ahead of these, since a child has to follow its parent.
 *
 * @param records      - the sub-nodes to draw: hosts drawn, none hidden
 * @param layoutNodes  - the laid-out tree
 * @param layoutEdges  - its edges, as drawn
 * @param labelWidthOf - (edge) => how wide that edge's own label is
 * @param sides        - which way each host's branch leans, by host id, as branchSides found and dagre
 *                       reserved them: where its edge and "auto" side sub-nodes go
 */
export function placeSupportNodes(records, layoutNodes, layoutEdges, labelWidthOf, sides = new Map()) {
    const positions = new Map(layoutNodes.map((node) => [node.id, node.position]));
    const side = placeSideNodes(records, sides);
    const nodes = [...side.nodes, ...placeEdgeNodes(records, positions, layoutEdges, labelWidthOf, sides)];
    return {
        // Each host's boundary first, so it is drawn beneath what it encloses
        nodes: [...groupBoundaries(nodes, positions), ...nodes],
        edges: side.edges,
    };
}

// How far a boundary stands off what it encloses
const GROUP_PADDING = 12;

/**
 * A boundary around each host and the sub-nodes that are drawn for it - beside it and beside its edge - so the
 * group reads as one thing. Worked out in the host's own coordinates: the card at the origin, each sub-node
 * where it was placed. Purely a mark: it takes no clicks and is not part of the tree.
 *
 * It is shaded, so it must sit beneath its host's card rather than tint it - and React Flow always stacks a
 * child above its parent. So unlike the sub-nodes it is not the host's child: it is placed in the graph's own
 * coordinates, beneath every node and edge, and carries its offset from the host so the graph view can keep it
 * on the host when the host is dragged (see PGraph's styledNodes).
 */
function groupBoundaries(subNodes, positions) {
    const boxes = new Map();
    subNodes.forEach((node) => {
        const size = sizeOf(node.data.record);
        const hostId = node.parentId;
        if (!boxes.has(hostId)) boxes.set(hostId, {x0: 0, y0: 0, x1: HOST_CARD.width, y1: HOST_CARD.height});
        const box = boxes.get(hostId);
        box.x0 = Math.min(box.x0, node.position.x);
        box.y0 = Math.min(box.y0, node.position.y);
        box.x1 = Math.max(box.x1, node.position.x + size.width);
        box.y1 = Math.max(box.y1, node.position.y + size.height);
    });

    return [...boxes].filter(([hostId]) => positions.has(hostId)).map(([hostId, box]) => {
        const width = box.x1 - box.x0 + 2 * GROUP_PADDING;
        const height = box.y1 - box.y0 + 2 * GROUP_PADDING;
        const offset = {x: box.x0 - GROUP_PADDING, y: box.y0 - GROUP_PADDING};
        const host = positions.get(hostId);
        return {
            id: `${SUPPORT_GROUP_PREFIX}${hostId}`,
            type: "supportGroup",
            position: {x: host.x + offset.x, y: host.y + offset.y},
            // Beneath the cards and the edges, which sit at 0
            zIndex: -1,
            draggable: false,
            selectable: false,
            focusable: false,
            data: {width, height, hostId, offset},
        };
    });
}

// A boundary's id. Under the sub-node prefix, so every check that keeps sub-nodes out of the tree keeps it out too
const SUPPORT_GROUP_PREFIX = "support:group:";

// The edges the tree is made of: everything but the links out to sub-nodes
export const treeEdgesOf = (edges) => edges.filter((edge) => !isSupportId(edge.target));
