import * as d3 from "d3";

export const ERROR_TYPES = {
  total: "Total Error %",
  missing: "Missing Values",
  mismatch: "Data Type Mismatch",
  anomaly: "Average Anomalies (Outliers)",
  incomplete: "Incomplete Data (< 3 points)",
  none: "None",
};

// The four quality dimensions the detectors actually produce. ERROR_TYPES also carries "total" and
// "none", which are display and sorting affordances rather than error types, so anything iterating
// real error types should use this instead of Object.keys(ERROR_TYPES).
// Matches DIMENSIONS in app/pgraph/metrics.py.
export const ERROR_DIMENSIONS = ["missing", "mismatch", "anomaly", "incomplete"];

// Drift from root is not an error type, so it sits outside the scale below and takes a colour none of the
// error types, the comparison roles or the improved/worsened steps use. See app/pgraph/distortion.py.
export const DRIFT_COLOR = "#0f766e";

export const errorColors = d3.scaleOrdinal()
  .domain(Object.keys(ERROR_TYPES))
  .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);
