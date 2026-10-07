// comparison.js
// Shared by the compare modal and the plot it draws.

import { ERROR_DIMENSIONS } from "../store/errorColors.js";
import { truncateText } from "./textUtils.js";

/* Node tables are named "<node id>_<base name>", so the id - n0a, n2b - names a node compactly. The
   full table name stays available in a title attribute. */
export function nodeName(id) {
    const match = id?.match(/^(n\d[a-z])_/);
    return match ? match[1] : truncateText(id, 16);
}

/* A sentence for the wrangle that produced a node: "Imputed age", "Deleted rows selected on age ×
   income". An op this does not know still reads, as the op and its columns. */
export function describeWrangle(wrangle) {
    if (!wrangle) return null;
    if (wrangle.op === "root") return "Original upload";

    const columns = wrangle.columns?.join(" × ");
    if (wrangle.op === "impute") return columns ? `Imputed ${columns}` : "Imputed values";
    if (wrangle.op === "delete") return columns ? `Deleted rows selected on ${columns}` : "Deleted rows";
    return columns ? `${wrangle.op} · ${columns}` : wrangle.op;
}

/* The nearest node both tables descend from - the point their branches part. A node counts as its own
   ancestor, so a pair where one descends from the other meets at the upper one. Walked on each node's parent,
   which runs up to the "root" sentinel above the root node.
   :param nodesByTable: the server's nodes keyed by table, as PGraphContext's serverNodesById holds them
   :return: the table, or null when the two share none */
export function commonAncestor(nodesByTable, a, b) {
    const lineage = new Set();
    for (let table = a; nodesByTable?.[table]; table = nodesByTable[table].data?.parent) lineage.add(table);
    for (let table = b; nodesByTable?.[table]; table = nodesByTable[table].data?.parent) {
        if (lineage.has(table)) return table;
    }
    return null;
}

// The pair's colors, matching the graph's comparison rings (Nodes.css) in both its modes
export const ROLE_COLORS = { a: "#1877F2", b: "#1a7f37" };
export const ROLE_NAMES = { a: "Selection A", b: "Selection B" };

// The server's name for the deleted rows' sink, and for the catch-all the long tail folds into
export const REMOVED_LABEL = "(removed)";
export const OTHER_LABEL = "(other)";

/* The two sides of the Flows view's Sankey, left to right: root sits in the middle, with its rows' flows into
   selection A drawn out to the left and into selection B out to the right. */
export const FLOW_SIDES = [
    { id: "a", color: ROLE_COLORS.a },
    { id: "b", color: ROLE_COLORS.b },
];

/* Each side's data: that node's breakdown against root */
export function flowSides(data) {
    return { a: data?.a, b: data?.b };
}

/* The categories the Sankey lays out, in the server's order - the most common first. Both sides share one
   list, so one window and one choice of categories covers them both. The removed sink is not among them: it
   is pinned under whatever the plot shows. */
export function flowCategories(data) {
    const sides = flowSides(data);
    const labels = FLOW_SIDES
        .map((side) => sides[side.id]?.flows)
        .filter(Boolean)
        .flatMap((flows) => [...flows.sources, ...flows.targets]);
    return [...new Set(labels)].filter((label) => label !== REMOVED_LABEL);
}

/* What the catch-all holds, gathered across both sides: each category the server folded, with the most rows
   either of them folded for it. Biggest first, as the server sends them.
   :return: {categories: [{category, rows}], more} - more counts the ones past the server's list */
export function otherCategories(data) {
    const sides = flowSides(data);
    const rows = new Map();
    let more = 0;
    FLOW_SIDES.forEach((side) => {
        const other = sides[side.id]?.flows?.other;
        if (!other) return;
        more = Math.max(more, other.more);
        other.categories.forEach(({ category, rows: count }) => {
            rows.set(category, Math.max(rows.get(category) ?? 0, count));
        });
    });
    return {
        categories: [...rows].map(([category, count]) => ({ category, rows: count }))
            .sort((a, b) => b.rows - a.rows),
        more,
    };
}

/* What a difference plot, or a heatmap tile, measures: rows, or error flags of some kind. The label
   names the option; the noun is how the plot talks about it on an axis or in a tooltip. */
export const MEASURES = {
    items: { label: "Rows", noun: "rows" },
    errors: { label: "All errors", noun: "error flags" },
    missing: { label: "Missing", noun: "missing values" },
    mismatch: { label: "Type mismatch", noun: "type mismatches" },
    anomaly: { label: "Anomalies", noun: "anomalies" },
    incomplete: { label: "Incomplete", noun: "incomplete values" },
};

/**
 * One side's value for a measure, read from a bin's counts ({items, missing, anomaly, ...}). An
 * error type the bin never recorded is zero.
 */
export function measureOf(count, measure) {
    if (!count) return 0;
    if (measure === "items") return count.items ?? 0;
    if (measure === "errors") return ERROR_DIMENSIONS.reduce((sum, type) => sum + (count[type] ?? 0), 0);
    return count[measure] ?? 0;
}
