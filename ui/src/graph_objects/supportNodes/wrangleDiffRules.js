// Kept apart from WrangleDiffSupport.jsx, which exports only components so fast refresh can reload it.

/* Why a wrangle diff cannot be added to this host, or null. Root has no incoming wrangle, an edge carries one
   diff, and a wrangle that recorded no columns has nothing to plot. */
export function wrangleDiffUnavailable({host, records}) {
    if (!host || host.data?.parent === "root") return "The root has no incoming wrangle to show.";
    if (records.some((record) => record.kind === "wrangleDiff")) return "The edge into this node already has one.";
    if (!host.data?.wrangle?.columns?.length) return "This wrangle recorded no columns to compare.";
    return null;
}
