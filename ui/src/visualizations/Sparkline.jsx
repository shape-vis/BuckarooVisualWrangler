import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { createTooltip } from "../utils/visCommon.jsx";
import "../styles/Sparkline.css";

/**
 * One quality dimension plotted across every downstream branch at once, so branches can be compared
 * rather than flipped between.
 *
 * Two things are encoded at the same time, which is why this is hand-drawn rather than taken from a
 * sparkline library:
 *   - hue says which branch a line is, matching that branch's edges in the provenance graph
 *   - each step is drawn solid when the error rate fell and dashed when it rose
 * Branches share index 0 (the selected node) and fan out from there.
 */

const PLOT_W = 196;
const PLOT_H = 34;
const LEFT_M = 6;
const RIGHT_M = 6;
const TOP_M = 8;
const BOTTOM_M = 8;
const SVG_W = PLOT_W + LEFT_M + RIGHT_M;
const SVG_H = PLOT_H + TOP_M + BOTTOM_M;

const asPercent = (rate) => `${(rate * 100).toFixed(2)}%`;

export default function Sparkline({ series = [] }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!svgRef.current || series.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const canvas = svg.append("g").attr("transform", `translate(${LEFT_M}, ${TOP_M})`);

    const allValues = series.flatMap((s) => s.values);
    const longest = Math.max(...series.map((s) => s.values.length));

    const xScale = d3.scaleLinear()
      .domain([0, Math.max(longest - 1, 1)])
      .range([0, PLOT_W]);

    const maxValue = d3.max(allValues);
    const minValue = d3.min(allValues);
    // A flat series would collapse to a zero-height domain, so pad it into a mid-height baseline
    const flat = maxValue === minValue;

    const yScale = d3.scaleLinear()
      .domain(flat ? [minValue - 1, maxValue + 1] : [minValue, maxValue])
      .range([PLOT_H, 0]);

    // A branch of one node has no line, so its single point sits mid-width rather than at the left
    const pointX = (i) => (longest === 1 ? PLOT_W / 2 : xScale(i));

    series.forEach((branch) => {
      const steps = branch.deltas.map((delta, i) => ({ delta, i }));

      canvas.selectAll(null)
        .data(steps)
        .join("line")
        .attr("class", "sparkline-step")
        .attr("x1", (d) => pointX(d.i))
        .attr("y1", (d) => yScale(branch.values[d.i]))
        .attr("x2", (d) => pointX(d.i + 1))
        .attr("y2", (d) => yScale(branch.values[d.i + 1]))
        .attr("stroke", branch.color)
        .attr("stroke-width", 2)
        .attr("stroke-linecap", "round")
        // Dashed where the error rate rose, so direction survives the hue being spent on branch identity
        .attr("stroke-dasharray", (d) => (d.delta > 0 ? "3 2" : null));

      // Bound as objects, not raw numbers: createTooltip passes only the datum, and a repeated value
      // would otherwise be ambiguous about which step it came from
      const points = branch.values.map((value, i) => ({ value, i, branch }));

      const dots = canvas.selectAll(null)
        .data(points)
        .join("circle")
        .attr("class", "sparkline-point")
        .attr("cx", (d) => pointX(d.i))
        .attr("cy", (d) => yScale(d.value))
        .attr("r", 3)
        .attr("fill", branch.color)
        .attr("stroke", "#ffffff")
        .attr("stroke-width", 1);

      // Reuses the global #tooltip div mounted in Buckaroo.jsx
      createTooltip(dots, (d) => {
        const node = d.branch.nodeIds[d.i] ?? `step ${d.i}`;
        const delta = d.i > 0 ? d.branch.deltas[d.i - 1] : null;
        const change = delta === null
          ? "start of branch"
          : delta === 0
            ? "no change"
            : `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(2)} pts`;
        return `<strong>${node}</strong><br/>${d.branch.label}<br/>${asPercent(d.value)}<br/>${change}`;
      });
    });
  }, [series]);

  return (
    <svg
      ref={svgRef}
      className="sparkline"
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      style={{ width: "100%", height: "auto" }}
    />
  );
}
