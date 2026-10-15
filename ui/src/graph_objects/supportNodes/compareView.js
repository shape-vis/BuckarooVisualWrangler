/**
 * The compare kind of supporting sub-node: a comparison of two nodes kept beside each of them. It is not
 * offered in the support-nodes window; Save in the compare window makes one on each of the two nodes it
 * compares, grouped so they change together. It shows the comparison - as a picture until it is resized large
 * enough for the whole plot - and opens it in the compare window.
 *
 *   other - the other node of the two, a table name
 *   spec  - the comparison object it shows (utils/comparisonSpec.js), kept up to date while it is open in
 *           the compare window
 *   group - shared by the sub-nodes one Save added
 *
 * Plain JSON throughout, since records are saved as they are.
 */
import { PLOT_KINDS, nodeName } from "../../utils/comparison.js";
import { normalizeSpec } from "../../utils/comparisonSpec.js";

export const COMPARE_DEFAULTS = { other: null, spec: null, group: null };

// The size a compare sub-node starts at: room for its comparison in miniature, which it shows until it is larger
export const COMPARE_SIZE = { width: 260, height: 206 };

/* The two sizes a sub-node drawing the compare window's plot switches between with its expand button: its plot in
   miniature, and in detail - room for the whole plot, FULL_PLOT_SIZE or more */
export const MINIATURE_SIZE = { width: 240, height: 190 };
export const DETAIL_SIZE = { width: 440, height: 500 };

/* The smallest a sub-node drawing the compare window's plot - a compare or a drift-plot sub-node - shows the whole
   plot at: room for it with its zoom strip, hover note and legend, without squeezing it. Smaller, it shows its
   badge's picture of the plot instead. */
export const FULL_PLOT_SIZE = { width: 440, height: 480 };

/** Whether a sub-node drawn this size has room for the compare window's whole plot. */
export function fitsFullPlot(size) {
    if (!size) return false;
    return size.width >= FULL_PLOT_SIZE.width && size.height >= FULL_PLOT_SIZE.height;
}

/**
 * The comparison the sub-node shows: what it last showed, or - for a record without one - this node against
 * the other on the first plot kind, starting on the host's first column.
 */
export function specOfCompare(record, hostColumns) {
    const config = { ...COMPARE_DEFAULTS, ...record.config };
    if (config.spec) return normalizeSpec(config.spec);
    return normalizeSpec({
        a: config.other ?? record.hostId,
        b: record.hostId,
        anchor: record.hostId,
        kind: PLOT_KINDS[0].id,
        x: hostColumns[0] || "",
        y: hostColumns[1] || hostColumns[0] || null,
    });
}

/** One line naming what a comparison shows: its two nodes, its plot kind and its column. */
export function compareSummary(spec) {
    const plotKind = PLOT_KINDS.find((option) => option.id === spec.kind);
    const kindLabel = plotKind?.label ?? spec.kind;

    let summary = `${nodeName(spec.a)} → ${nodeName(spec.b)} · ${kindLabel}`;
    if (spec.x) {
        summary += ` · ${spec.x}`;
    }
    return summary;
}

/** The settings Save in the compare window keeps a comparison with, on one of its two nodes. */
export function savedCompareConfig(spec, hostId, group) {
    const other = hostId === spec.a ? spec.b : spec.a;
    return { ...COMPARE_DEFAULTS, other, spec, group };
}

/* The helpers below are shared by the compare window and the sub-nodes that draw its plots, so the two
   always read a comparison the same way. */

/**
 * Whether a drift column is numeric or categorical, as root decided it: read from the first of the given
 * nodes' distortions that knows the column, so callers list them in the order they trust them.
 */
export function columnKindOf(column, distortions) {
    for (const distortion of distortions) {
        const entry = distortion?.columns?.[column];
        if (entry != null) return entry.kind;
    }
    return undefined;
}

/** The hidden-categories list with one more category in it - the same list when it is already there. */
export function withCategoryHidden(hidden, category) {
    if (hidden.includes(category)) return hidden;
    return [...hidden, category];
}
