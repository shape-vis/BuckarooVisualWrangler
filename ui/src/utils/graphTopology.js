/**
 * Walking the provenance graph on the client, over the nodes/edges arrays the UI already holds.
 *
 * These exist for interface affordances - showing which nodes a branch may end on - and are not the
 * authority on anything. The server validates a branch selection independently before computing it.
 */

/** Node ids directly below `nodeId`. */
export function childrenOf(edges, nodeId) {
    return edges.filter((edge) => edge.source === nodeId).map((edge) => edge.target);
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
