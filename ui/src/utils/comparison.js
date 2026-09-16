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
