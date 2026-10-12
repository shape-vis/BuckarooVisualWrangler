// PreviewCard.jsx
// Renders a small histogram (1D), heatmap (2D), or scatterplot for a preview table.
// The fetching and drawing are shared with the error-plot sub-node - see visualizations/previewPlots.js.

import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import {
  LEFT_M, SVG_H, SVG_W, TOP_M, draw1D, draw2D, drawScatter, usePreviewPlotData,
} from "../visualizations/previewPlots.js";
import "../styles/PreviewCard.css";

export default function PreviewCard({ label, tableName, cols, errorColors, chartType = "histogram", onExecuteWrangle }) {
  const svgRef = useRef(null);
  const { data, loading, error } = usePreviewPlotData({ table: tableName, kind: chartType, columns: cols });

  const colorScale = errorColors || (() => "steelblue");

  // ── draw chart ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!data || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const canvas = svg.append("g")
      .attr("transform", `translate(${LEFT_M}, ${TOP_M})`);

    if (chartType === "histogram") {
      draw1D(canvas, data, colorScale);
    } else if (chartType === "heatmap") {
      draw2D(canvas, data, colorScale);
    } else if (chartType === "scatterplot") {
      drawScatter(canvas, data, colorScale);
    }
  }, [data, chartType]);

  return (
    <div className="repair-method preview-card">
      <div className="preview-card-chart">
        <div className="preview-card-label">{label}</div>
        {loading && <div className="preview-card-loading">Loading…</div>}
        {error   && <div className="preview-card-error">{error}</div>}
        {!loading && !error && (
          <svg ref={svgRef} viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ width: "100%", height: "auto" }} />
        )}
      </div>
      {onExecuteWrangle && (
        <button
          onClick={onExecuteWrangle}
          className="regButton preview-card-execute"
        >
          Execute Wrangle
        </button>
      )}
    </div>
  );
}
