// drift.js
// Shared by every view that shows drift from root: how its numbers read, and the null test's flags.
// Drift is a cost, not an error - see app/pgraph/distortion.py - so nothing here colors it good or bad.

import { useEffect, useState } from "react";
import { getDriftNull } from "./serverCalls.jsx";

export const NULL_FLAG_TITLE =
    "Drift larger than 95% of random row deletions of the same size — not explainable by chance.";

/** A drift value as it reads everywhere: three places, or a dash where there is none. */
export const formatDrift = (value) => (value == null ? "—" : value.toFixed(3));

/** A change in drift between two nodes, both measured from root. */
export const formatDriftDelta = (delta) =>
    `${delta > 0 ? "+" : delta < 0 ? "−" : "±"}${Math.abs(delta).toFixed(3)}`;

/**
 * The null test for every column of one node, as {column: result}.
 *
 * Only asked for when the node lost rows: the test models rows leaving at random, so it cannot apply
 * anywhere else. The server caches it, but it is still the one slow part of drift, so it is fetched on
 * demand rather than carried in the graph. A reply for a node the view has since moved off is dropped.
 */
export function useDriftNull(nodeId, rowsRemoved) {
    const [result, setResult] = useState({ node: null, columns: {} });

    useEffect(() => {
        if (!nodeId || !rowsRemoved) return;

        const controller = new AbortController();
        getDriftNull(nodeId, [], controller.signal)
            .then((response) => {
                if (response?.success) setResult({ node: nodeId, columns: response.columns });
            })
            .catch((error) => {
                if (error.name !== "AbortError") console.error("[getDriftNull]", error.message);
            });
        return () => controller.abort();
    }, [nodeId, rowsRemoved]);

    return result.node === nodeId ? result.columns : {};
}
