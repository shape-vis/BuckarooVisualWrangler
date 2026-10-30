import * as d3 from "d3";
import errorTypesFile from "../../../shared/error_types.json";

/* The error types, from shared/error_types.json - the one list the backend reads too (app/error_types.py), so a new
   detector's type, label and colour are written down once. Every list, scale and swatch below is built from it. */
const ERROR_TYPE_ENTRIES = errorTypesFile.error_types;

// "total" and "none" are display and sorting affordances of the attribute list, not error types: the first sorts by
// every error at once, the second marks a column nothing flags
const TOTAL_LABEL = "Total Error %";
const NONE_LABEL = "None";
const TOTAL_COLOR = "#00000000";
const NONE_COLOR = "steelblue";

/* Every entry the attribute list offers, by key: total, each error type, then none - each with its label */
export const ERROR_TYPES = { total: TOTAL_LABEL };
for (const entry of ERROR_TYPE_ENTRIES) {
  ERROR_TYPES[entry.key] = entry.label;
}
ERROR_TYPES.none = NONE_LABEL;

// The quality dimensions the detectors actually produce, in their order. ERROR_TYPES also carries "total" and "none",
// so anything iterating real error types should use this instead of Object.keys(ERROR_TYPES). The same list as
// ERROR_TYPES in app/db_utils/detector_sql.py.
export const ERROR_DIMENSIONS = ERROR_TYPE_ENTRIES.map((entry) => entry.key);

// Each error type as the file describes it, by key: label, short_label, noun, color, text_color, table_priority
export const ERROR_TYPE_DETAILS = {};
for (const entry of ERROR_TYPE_ENTRIES) {
  ERROR_TYPE_DETAILS[entry.key] = entry;
}

// The error types in the order a table cell flagged several ways picks its colour by, the first found winning
export const ERROR_TABLE_PRIORITY = [...ERROR_DIMENSIONS].sort(
  (a, b) => ERROR_TYPE_DETAILS[a].table_priority - ERROR_TYPE_DETAILS[b].table_priority,
);

// Drift from root is not an error type, so it sits outside the scale below and takes a colour none of the
// error types, the comparison roles or the improved/worsened steps use. See app/pgraph/distortion.py.
export const DRIFT_COLOR = "#0f766e";

// The colour of each entry of ERROR_TYPES, by its key
const ERROR_TYPE_COLORS = { total: TOTAL_COLOR, none: NONE_COLOR };
for (const entry of ERROR_TYPE_ENTRIES) {
  ERROR_TYPE_COLORS[entry.key] = entry.color;
}

const errorTypeKeys = Object.keys(ERROR_TYPES);
const colorsInKeyOrder = errorTypeKeys.map((type) => ERROR_TYPE_COLORS[type]);

export const errorColors = d3.scaleOrdinal()
  .domain(errorTypeKeys)
  .range(colorsInKeyOrder);

/* The inline style a swatch, badge or table cell takes its colours from: the stylesheets draw every error type with
   one rule reading --swatch-color, and --swatch-text for text on it. Inline rather than on the page's root, so a
   panel popped out into a window of its own keeps its colours. */
export function errorSwatchStyle(type) {
  const style = { "--swatch-color": ERROR_TYPE_COLORS[type] ?? "transparent" };
  const details = ERROR_TYPE_DETAILS[type];
  if (details) style["--swatch-text"] = details.text_color;
  return style;
}
