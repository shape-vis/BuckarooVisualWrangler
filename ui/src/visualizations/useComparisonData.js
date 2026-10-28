// useComparisonData.js
// Fetches what a comparison plots, for the compare panel and the compare sub-node alike, so the two draw
// the same data the same way.

import { useEffect, useState } from "react";
import { getDriftDetail, getNodeComparison } from "../utils/serverCalls.jsx";
import { useHostWindow } from "../store/HostWindowContext.jsx";

// Options can be changed in quick succession, so a request waits for them to settle
const FETCH_DELAY_MS = 150;

/* The Drift kind's data: each node's breakdown against root, or against base - their common ancestor - when
   one is given. Both are measured from the same state, so a categorical column's two Sankeys share its
   categories - the Flows view draws them as one, that state in the middle. A single node is asked for once. */
async function getDriftComparison({ a, b, x, keep, base }, signal) {
    const [detailA, detailB] = a === b
        ? await getDriftDetail({ node: b, column: x, keep, base }, signal).then((detail) => [detail, detail])
        : await Promise.all([
            getDriftDetail({ node: a, column: x, keep, base }, signal),
            getDriftDetail({ node: b, column: x, keep, base }, signal),
        ]);
    const failed = [detailA, detailB].find((response) => !response?.success);
    if (failed) return { success: false, error: failed?.error };
    // base travels with the result, so a result still up while the next loads is labelled by its own
    return { success: true, kind: "drift", x, base: base ?? null, a: detailA, b: detailB };
}

/**
 * The plot data for one set of options, refetched as they change.
 *
 * A result is only current when it carries the key of the options that asked for it, which is how loading
 * is known without any state of its own. While the next result loads, the last one of the same kind stays
 * up. Comparing a node with itself is a single-node comparison: the result says so with single, and
 * ComparisonPlot draws the one side.
 *
 * @param options {a, b, kind, x, y, keep, base} - node tables, plot kind, columns (y for a heatmap only),
 *        the categories kept out of a Sankey's catch-all, and the ancestor drift is measured from
 * @returns {loading, current, plotData} - current is the result for these options, error and all, or null
 */
export function useComparisonData({ a, b, kind, x, y, keep, base }) {
    // The timer is the host window's: a popped-out panel stays in view while this page may be minimised,
    // and a hidden page's own timers are throttled to a crawl
    const hostWindow = useHostWindow();
    const [result, setResult] = useState({ key: null, data: null, error: null });

    const requestKey = [a, b, kind, x, y ?? "", keep?.join(",") ?? "", base ?? ""].join("|");
    const loading = Boolean(x) && result.key !== requestKey;
    const current = result.key === requestKey ? result : null;
    const plotData = result.data?.kind === kind ? result.data : null;

    useEffect(() => {
        if (!x || !loading) return undefined;

        const controller = new AbortController();
        const timer = hostWindow.setTimeout(async () => {
            try {
                const response = kind === "drift"
                    ? await getDriftComparison({ a, b, x, keep, base }, controller.signal)
                    : await getNodeComparison({ a, b, kind, x, y }, controller.signal);
                setResult(response?.success
                    ? { key: requestKey, data: { ...response, single: a === b }, error: null }
                    : { key: requestKey, data: null, error: response?.error || "The comparison failed" });
            } catch (error) {
                // A request superseded by newer options is aborted on purpose, and is not a failure
                if (error.name !== "AbortError") {
                    setResult({ key: requestKey, data: null, error: error.message });
                }
            }
        }, FETCH_DELAY_MS);

        return () => {
            hostWindow.clearTimeout(timer);
            controller.abort();
        };
    }, [requestKey, loading, a, b, kind, x, y, keep, base, hostWindow]);

    return { loading, current, plotData };
}
