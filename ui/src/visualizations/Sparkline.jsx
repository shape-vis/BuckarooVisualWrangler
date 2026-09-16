import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { createTooltip } from "../utils/visCommon.jsx";
import { formatDrift, formatDriftDelta } from "../utils/drift.js";
import "../styles/Sparkline.css";

/**
 * One quality dimension along the selected branch.
 *
 * Every node on the branch is plotted, whether or not the graph currently has it folded into a
 * collapsed node - collapsing is a way of looking at the tree and never changes what a step
 * contributed. Points belonging to a folded run are ringed, so it is clear which nodes the graph is
 * hiding while their values stay on the chart.
 *
 * Each step is its own line segment so it can carry its own color - green where the error rate fell,
 * red where it rose. A single path could not do that, which is why this is hand-drawn rather than
 * taken from a sparkline library.
 *
 * Drift from root is drawn with polarity "neutral": it has no better or worse direction - zero means
 * nothing was done, not that the data is good - so its steps are never green or red.
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

/* An error rate falling is an improvement and rising a regression, so its steps are green and red. A
   neutral series draws every step that moved in its own color, and only a flat step in grey. */
const stepColor = (delta, polarity, color) => (
  delta === 0 ? UNCHANGED : polarity === "neutral" ? color : delta < 0 ? IMPROVED : WORSENED
);

/* How a series' numbers read. Error rates are percentages whose steps are points; drift is a bare
   number, W1/IQR or TVD, whose steps are differences of two values both measured from root. */
const FORMATS = {
  rate: {
    value: (rate) => `${(rate * 100).toFixed(2)}%`,
    tick: (rate) => `${(rate * 100).toFixed(1)}%`,
    delta: (delta) => `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(2)} pts`,
  },
  drift: {
    value: formatDrift,
    tick: d3.format(".2~r"),
    delta: formatDriftDelta,
  },
};

// Axis labels have to fit in a few pixels, and a table name is mostly a prefix shared with every
// other node - the leading "n0a" is the part that identifies it
const shortNodeId = (nodeId) => String(nodeId ?? "").split("_")[0];

export default function Sparkline({
  values = [], deltas = [], nodeIds = [], color = "steelblue", collapsedNodeIds,
  polarity = "error", format = "rate",
}) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!svgRef.current || values.length === 0) return;

    const folded = collapsedNodeIds ?? new Set();
    const isFolded = (i) => folded.has(nodeIds[i]);
    const formats = FORMATS[format] ?? FORMATS.rate;

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
       gets one tick per node rather than the scale's own ticks. A flat branch is padded to a readable
       domain above, so its y ticks are reduced to the one real value rather than implying a spread
       that is not in the data. */
    canvas.append("g")
      .attr("class", "sparkline-axis")
      .call(
        d3.axisLeft(yScale)
          .ticks(flat ? 1 : 3)
          .tickValues(flat ? [values[0]] : null)
          .tickFormat(formats.tick)
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
      .attr("class", (i) => `bottom-axis-text${isFolded(i) ? " sparkline-tick--folded" : ""}`);

    canvas.selectAll("line.sparkline-step")
      .data(deltas.map((delta, i) => ({ delta, i })))
      .join("line")
      .attr("class", "sparkline-step")
      .attr("x1", (d) => pointX(d.i))
      .attr("y1", (d) => yScale(values[d.i]))
      .attr("x2", (d) => pointX(d.i + 1))
      .attr("y2", (d) => yScale(values[d.i + 1]))
      .attr("stroke", (d) => stepColor(d.delta, polarity, color))
      .attr("stroke-width", 2)
      .attr("stroke-linecap", "round");

    // A ring behind the dot marks a node the graph currently has folded into a collapsed node
    canvas.selectAll("circle.sparkline-folded-ring")
      .data(values.map((value, i) => ({ value, i })).filter((d) => isFolded(d.i)))
      .join("circle")
      .attr("class", "sparkline-folded-ring")
      .attr("cx", (d) => pointX(d.i))
      .attr("cy", (d) => yScale(d.value))
      .attr("r", 5.5);

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
          : formats.delta(delta);
      const foldedNote = isFolded(d.i) ? "<br/><em>hidden in a collapsed node</em>" : "";
      return `<strong>${node}</strong><br/>${formats.value(d.value)}<br/>${change}${foldedNote}`;
    });
  }, [values, deltas, nodeIds, color, collapsedNodeIds, polarity, format]);

  return (
    <svg
      ref={svgRef}
      className="sparkline"
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      style={{ width: "100%", height: "auto" }}
    />
  );
}
