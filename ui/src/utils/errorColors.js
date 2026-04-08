import * as d3 from "d3";

export const ERROR_TYPES = {
  total: "Total Error %",
  missing: "Missing Values",
  mismatch: "Data Type Mismatch",
  anomaly: "Anomalies",
  incomplete: "Rare Values",
  none: "None",
};

export const errorColors = d3.scaleOrdinal()
  .domain(Object.keys(ERROR_TYPES))
  .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);
