// comparison.js
// Shared by the compare modal and the plot it draws.

import { ERROR_DIMENSIONS } from "../store/errorColors.js";

// The pair's colors, matching the graph's comparison rings (Nodes.css) and the attribute summary strip
export const ROLE_COLORS = { base: "#1877F2", other: "#1a7f37" };
export const ROLE_NAMES = { base: "Baseline", other: "Comparator" };

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
