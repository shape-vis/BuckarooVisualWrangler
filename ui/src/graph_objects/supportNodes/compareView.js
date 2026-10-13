/**
 * The compare kind of supporting sub-node: a comparison of two nodes kept beside each of them. It is not
 * offered in the add-sub-node modal; Save in the compare window makes one on each of the two nodes it
 * compares, grouped so they change together. It previews the comparison and opens it in the compare window.
 *
 *   other - the other node of the two, a table name
 *   spec  - the comparison object it shows (utils/comparisonSpec.js), kept up to date while it is open in
 *           the compare window
 *   group - shared by the sub-nodes one Save added
 *
 * Plain JSON throughout, since records are saved as they are.
 */
import { PLOT_KINDS } from "../../utils/comparison.js";
import { normalizeSpec } from "../../utils/comparisonSpec.js";

export const COMPARE_DEFAULTS = { other: null, spec: null, group: null };

// The size a compare sub-node starts at: room for its preview
export const COMPARE_SIZE = { width: 260, height: 206 };

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
