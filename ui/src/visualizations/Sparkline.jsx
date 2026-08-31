import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { createTooltip } from "../utils/visCommon.jsx";
import "../styles/Sparkline.css";

/**
 * One quality dimension along the selected branch.
 *
 * Each step is its own line segment so it can carry its own color - green where the error rate fell,
 * red where it rose. A single path could not do that, which is why this is hand-drawn rather than
 * taken from a sparkline library. The points are colored by dimension to tie the chart to its title.
 */

const PLOT_W = 176;
const PLOT_H = 52;
const LEFT_M = 30;   // room for the y axis' percentage labels
const RIGHT_M = 10;  // so the last point and its label are not clipped
const TOP_M = 8;
const BOTTOM_M = 20; // room for the x axis' node labels
const SVG_W = PLOT_W + LEFT_M + RIGHT_M;
const SVG_H = PLOT_H + TOP_M + BOTTOM_M;

const IMPROVED = "#1a7f37";
const WORSENED = "#d1242f";
const UNCHANGED = "#8c939d";

const stepColor = (delta) => (delta === 0 ? UNCHANGED : delta < 0 ? IMPROVED : WORSENED);
const asPercent = (rate) => `${(rate * 100).toFixed(2)}%`;

// Axis labels have to fit in a few pixels, and a table name is mostly a prefix shared with every
// other node - the leading "n0a" is the part that identifies it
const shortNodeId = (nodeId) => String(nodeId ?? "").split("_")[0];

export default function Sparkline({ values = [], deltas = [], nodeIds = [], color = "steelblue" }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!svgRef.current || values.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const canvas = svg.append("g").attr("transform", `translate(${LEFT_M}, ${TOP_M})`);

    /* A branch of one node has no line to draw, so its single point sits mid-width rather than hard
       left. Folding that into the scale keeps the axis ticks on the dots in both cases. */
    const xScale = values.length === 1
      ? d3.scaleLinear().domain([0, 1]).range([PLOT_W / 2, PLOT_W / 2])
      : d3.scaleLinear().domain([0, values.length - 1]).range([0, PLOT_W]);

    const maxValue = d3.max(values);
    const minValue = d3.min(values);
    // A flat branch would collapse to a zero-height domain, so pad it into a mid-height baseline
    const flat = maxValue === minValue;

    const yScale = d3.scaleLinear()
      .domain(flat ? [minValue - 1, maxValue + 1] : [minValue, maxValue])
      .range([PLOT_H, 0]);

    const pointX = (i) => xScale(i);

    /* Axes. The y axis is the quality metric; the x axis is the branch's nodes in path order, so it
       gets one tick per node rather than dagre's continuous scale ticks. A flat branch is padded to
       a readable domain above, so its ticks are suppressed to avoid implying a spread that is not
       in the data. */
    canvas.append("g")
      .attr("class", "sparkline-axis")
      .call(
        d3.axisLeft(yScale)
          .ticks(flat ? 1 : 3)
          .tickValues(flat ? [values[0]] : null)
          .tickFormat((rate) => `${(rate * 100).toFixed(1)}%`)
          .tickSize(3)
      )
      .selectAll("text")
      .attr("class", "left-axis-text");

    canvas.append("g")
      .attr("class", "sparkline-axis")
      .attr("transform", `translate(0, ${PLOT_H})`)
      .call(
        d3.axisBottom(xScale)
          .tickValues(d3.range(values.length))
          .tickFormat((i) => shortNodeId(nodeIds[i]))
          .tickSize(3)
      )
      .selectAll("text")
      .attr("class", "bottom-axis-text");

    canvas.selectAll("line.sparkline-step")
      .data(deltas.map((delta, i) => ({ delta, i })))
      .join("line")
      .attr("class", "sparkline-step")
      .attr("x1", (d) => pointX(d.i))
      .attr("y1", (d) => yScale(values[d.i]))
      .attr("x2", (d) => pointX(d.i + 1))
      .attr("y2", (d) => yScale(values[d.i + 1]))
      .attr("stroke", (d) => stepColor(d.delta))
      .attr("stroke-width", 2)
      .attr("stroke-linecap", "round");

    // Bound as objects, not raw numbers: createTooltip passes only the datum, and a repeated value
    // would otherwise be ambiguous about which step it came from
    const dots = canvas.selectAll("circle.sparkline-point")
      .data(values.map((value, i) => ({ value, i })))
      .join("circle")
      .attr("class", "sparkline-point")
      .attr("cx", (d) => pointX(d.i))
      .attr("cy", (d) => yScale(d.value))
      .attr("r", 3)
      .attr("fill", color)
      .attr("stroke", "#ffffff")
      .attr("stroke-width", 1);

    // Reuses the global #tooltip div mounted in Buckaroo.jsx
    createTooltip(dots, (d) => {
      const node = nodeIds[d.i] ?? `step ${d.i}`;
      const delta = d.i > 0 ? deltas[d.i - 1] : null;
      const change = delta === null
        ? "start of branch"
        : delta === 0
          ? "no change"
          : `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(2)} pts`;
      return `<strong>${node}</strong><br/>${asPercent(d.value)}<br/>${change}`;
    });
  }, [values, deltas, nodeIds, color]);

  return (
    <svg
      ref={svgRef}
      className="sparkline"
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      style={{ width: "100%", height: "auto" }}
    />
  );
}
