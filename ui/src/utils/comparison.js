// comparison.js
// Shared by the compare panel and the plot it draws.

import { ERROR_DIMENSIONS, ERROR_TYPE_DETAILS } from "../store/errorColors.js";
import { truncateText } from "./textUtils.js";

/* What each node is called, by its table - "n2b" - as the graph's payload labels it. A node's table name is
   its identity and never changes; its label is assigned when it joins the graph for good, and a staged
   candidate shows its own "c7" until then. PGraphContext refills this whenever the graph loads. */
let nodeLabels = new Map();

export function setNodeLabels(labels) {
    nodeLabels = labels;
}

/* The prefix a node table's name starts with: n0a…n9z for a node of the graph, c7 for a staged candidate */
const TABLE_PREFIX = String.raw`n\d[a-z]|c\d+`;
const PREFIX_OF_TABLE = new RegExp(`^(${TABLE_PREFIX})_`);
const BASE_OF_TABLE = new RegExp(`^(?:${TABLE_PREFIX})_(.+)$`);

/* A node's short name: its label, or for a table the graph has not labelled, the prefix its name starts with
   - n0a, c7. The full table name stays available in a title attribute. */
export function nodeName(id) {
    if (nodeLabels.has(id)) return nodeLabels.get(id);
    const match = id?.match(PREFIX_OF_TABLE);
    return match ? match[1] : truncateText(id, 16);
}

/* The base a node table's name carries after its prefix - the uploaded file's cleaned name */
export function baseName(id) {
    const match = id?.match(BASE_OF_TABLE);
    return match ? match[1] : null;
}

/* A sentence for the wrangle that produced a node: "Imputed age", "Deleted rows selected on age ×
   income". The server writes it, from the operation's own description (app/server_utils/wrangle_ops.py); a wrangle
   without one still reads, as the op and its columns. */
export function describeWrangle(wrangle) {
    if (!wrangle) return null;
    if (wrangle.op === "root") return "Original upload";
    if (wrangle.description) return wrangle.description;

    const columns = wrangle.columns?.join(" × ");
    return columns ? `${wrangle.op} · ${columns}` : wrangle.op;
}

/* The nearest node both tables descend from - the point their branches part. A node counts as its own
   ancestor, so a pair where one descends from the other meets at the upper one. Walked on each node's parent,
   which runs up to the "root" sentinel above the root node.
   :param nodesByTable: the server's nodes keyed by table, as PGraphContext's serverNodesById holds them
   :return: the table, or null when the two share none */
export function commonAncestor(nodesByTable, a, b) {
    // Everything a descends from, a included
    const lineage = new Set();
    let table = a;
    while (nodesByTable?.[table]) {
        lineage.add(table);
        table = parentTableOf(nodesByTable, table);
    }

    // The first of b's ancestors, b included, that a shares
    table = b;
    while (nodesByTable?.[table]) {
        if (lineage.has(table)) return table;
        table = parentTableOf(nodesByTable, table);
    }
    return null;
}

/* The table a node was made from - "root" for the root node itself */
function parentTableOf(nodesByTable, table) {
    return nodesByTable[table].data?.parent;
}

// The pair's colors, matching the graph's comparison rings (Nodes.css) in both its modes
export const ROLE_COLORS = { a: "#1877F2", b: "#701c1c" };
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

/* Each side's data: that node's breakdown against root. A single-node result carries its node as both sides,
   and has only the one side to draw. */
export function flowSides(data) {
    return { a: data?.single ? undefined : data?.a, b: data?.b };
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

/* What a difference plot, or a heatmap tile, measures: rows, or error flags of some kind - all of them, or one error
   type, named as shared/error_types.json names it. The label names the option; the noun is how the plot talks about
   it on an axis or in a tooltip. */
export const MEASURES = {
    items: { label: "Rows", noun: "rows" },
    errors: { label: "All errors", noun: "error flags" },
};
for (const type of ERROR_DIMENSIONS) {
    const details = ERROR_TYPE_DETAILS[type];
    MEASURES[type] = { label: details.short_label, noun: details.noun };
}

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

/* Each plot kind offers the views that make sense for it: a heatmap overlay would be two grids painted
   over one another. Drift draws each node against root rather than against the other, and its views
   depend on the column instead - see DRIFT_VIEWS. A single node has no other to overlay or subtract, so it
   only ever draws side by side - one panel. */
export const PLOT_KINDS = [
    { id: "histogram", label: "Histogram", axes: 1, views: ["side", "overlay", "difference"] },
    { id: "heatmap", label: "Heatmap", axes: 2, views: ["side", "difference"] },
    { id: "drift", label: "Drift", axes: 1, views: null },
];

/* Drift's views: the shape a numeric column now has, and where a categorical one's rows went */
export const DRIFT_VIEWS = { numeric: ["ridgeline"], categorical: ["flows"] };

export const VIEW_LABELS = {
    side: "Side by side", overlay: "Overlay", difference: "Difference",
    ridgeline: "Ridgeline", flows: "Flows",
};

/**
 * The views a kind offers, and the one actually drawn for a chosen view: a view this kind does not offer
 * falls back to its first, so the choice is kept for when it applies again.
 * @param columnKind drift's column kind, "numeric" or "categorical", as root decided it
 */
export function viewsFor({ kind, view, columnKind, single }) {
    const views = viewsOfKind(kind, columnKind, single);
    const activeView = views.includes(view) ? view : views[0];
    return { views, activeView };
}

function viewsOfKind(kind, columnKind, single) {
    if (kind === "drift") return DRIFT_VIEWS[columnKind] ?? DRIFT_VIEWS.numeric;
    if (single) return ["side"];
    const plotKind = PLOT_KINDS.find((one) => one.id === kind);
    return plotKind.views;
}

/**
 * What drift is measured from: the two nodes' common ancestor when asked for and it is not root, else root
 * (null). Root is the node whose parent is the "root" sentinel.
 */
export function referenceBase({ kind, reference, a, b }, nodesByTable) {
    if (kind !== "drift" || reference !== "ancestor" || a === b) return null;
    const ancestor = commonAncestor(nodesByTable, a, b);
    if (!ancestor) return null;

    const ancestorIsRoot = nodesByTable?.[ancestor]?.data?.parent === "root";
    if (ancestorIsRoot) return null;
    return ancestor;
}
