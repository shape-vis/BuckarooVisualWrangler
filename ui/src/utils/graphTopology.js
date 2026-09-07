/**
 * Walking and folding the provenance graph on the client, over the nodes/edges arrays the UI holds.
 *
 * The branch helpers here exist for interface affordances - showing which nodes a branch may end on -
 * and are not the authority on anything: the server validates a branch selection before computing it.
 * The collapse helpers, by contrast, are the whole feature: collapsing is a view operation and never
 * reaches the server.
 */

/** Node ids directly below `nodeId`. */
export function childrenOf(edges, nodeId) {
    return edges.filter((edge) => edge.source === nodeId).map((edge) => edge.target);
}

/** The node id directly above `nodeId`, or undefined at the root. */
export function parentOf(edges, nodeId) {
    return edges.find((edge) => edge.target === nodeId)?.source;
}

/**
 * `nodeId` and everything reachable below it.
 *
 * Inclusive because a branch is allowed to stop at the edge's target - the shortest branch is the
 * single edge itself.
 *
 * @returns {Set<string>} node ids
 */
export function descendantsOf(edges, nodeId) {
    const found = new Set();
    if (!nodeId) return found;

    const pending = [nodeId];
    while (pending.length > 0) {
        const current = pending.pop();
        if (found.has(current)) continue;   // a malformed cycle would otherwise spin forever
        found.add(current);
        pending.push(...childrenOf(edges, current));
    }

    return found;
}

/**
 * Put a set of selected nodes in top-to-bottom order, if they form one unbroken run.
 *
 * A run is collapsible only when it is a straight piece of one branch (thesis §8(b)(iv)). Two things
 * would break that, and both are rejected here:
 *   - more than one node has no selected parent, so the selection is not a single chain
 *   - a node in the middle of the run has more than one child, so collapsing it would swallow the
 *     fork and orphan the sibling subtree in the layout
 * The last node may fork freely: its children reattach to the collapsed node.
 *
 * @returns {{nodes: string[]} | {error: string}}
 */
export function orderCollapsibleRun(edges, selectedIds) {
    const selected = new Set(selectedIds);
    if (selected.size < 2) return {error: "Select at least two nodes to collapse."};

    const heads = [...selected].filter((id) => !selected.has(parentOf(edges, id)));
    if (heads.length !== 1) {
        return {error: "Those nodes are not one unbroken run on a single branch."};
    }

    const ordered = [];
    let current = heads[0];

    while (current !== undefined) {
        ordered.push(current);

        const children = childrenOf(edges, current);
        const next = children.find((child) => selected.has(child));

        // Everything except the tail has to be a straight link, or the collapse hides a fork
        if (next !== undefined && children.length > 1) {
            return {error: `${current} branches - a run cannot be collapsed through a fork.`};
        }
        current = next;
    }

    if (ordered.length !== selected.size) {
        return {error: "Those nodes are not one unbroken run on a single branch."};
    }

    return {nodes: ordered};
}

/** A stable id for the placeholder node standing in for a collapsed run. */
export const collapsedRunId = (run) => `collapsed:${run[0]}:${run[run.length - 1]}`;

/**
 * Fold each collapsed run into a single placeholder node, rewiring the edges around it.
 *
 * The run's own nodes and internal edges drop out of the view. Whatever pointed at the run's head now
 * points at the placeholder, and whatever hung off its tail now hangs off the placeholder, so the
 * tree stays connected and dagre can lay it out unchanged.
 */
export function applyCollapse(nodes, edges, collapsedRuns) {
    if (!collapsedRuns || collapsedRuns.length === 0) return {nodes, edges};

    // Which run, if any, has swallowed a given node
    const runOf = new Map();
    collapsedRuns.forEach((run) => run.nodes.forEach((id) => runOf.set(id, run)));

    const nodesById = new Map(nodes.map((node) => [node.id, node]));

    /* Copied, not passed through by reference. Laying the folded graph out writes node.type and
       node.data.label onto whatever it is handed, and these objects mirror what the server sent - a
       view transform must not be able to scribble on them. */
    const remainingNodes = nodes
        .filter((node) => !runOf.has(node.id))
        .map((node) => ({...node, data: {...node.data}}));

    const placeholders = collapsedRuns.map((run) => {
        const head = run.nodes[0];
        const tail = run.nodes[run.nodes.length - 1];

        return {
            id: run.id,
            type: "collapsedNode",
            position: nodesById.get(head)?.position ?? {x: 0, y: 0},
            data: {
                label: `${run.nodes.length} steps`,
                // The state you actually arrive at is the tail's, so that is what the node reports
                metrics: nodesById.get(tail)?.data?.metrics,
                parent: nodesById.get(head)?.data?.parent,
                run: run.nodes,
                head,
                tail,
            },
        };
    });

    const rewired = [];
    edges.forEach((edge) => {
        const sourceRun = runOf.get(edge.source);
        const targetRun = runOf.get(edge.target);

        // Wholly inside a run: it is one of the steps being folded away
        if (sourceRun && targetRun && sourceRun === targetRun) return;

        rewired.push({
            ...edge,
            source: sourceRun ? sourceRun.id : edge.source,
            target: targetRun ? targetRun.id : edge.target,
        });
    });

    return {nodes: [...remainingNodes, ...placeholders], edges: rewired};
}

/**
 * Every node the graph currently has folded away.
 *
 * The sparkline marks these so it is clear which of its points the graph is hiding - it still plots
 * all of them, because collapsing changes the view and never what a step contributed.
 *
 * @returns {Set<string>} node ids
 */
export function collapsedNodeIds(collapsedRuns) {
    const ids = new Set();
    (collapsedRuns ?? []).forEach((run) => run.nodes.forEach((id) => ids.add(id)));
    return ids;
}
