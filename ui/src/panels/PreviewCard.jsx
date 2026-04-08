// PreviewCard.jsx
// Renders a small histogram (1D), heatmap (2D), or scatterplot for a preview table.
// Fetches its own data from /api/plots/preview-histogram or /api/plots/preview-scatterplot.

import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { queryPreviewHistogram, queryPreviewScatterplot } from "../store/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../store/visCommon.jsx";
import "../styles/PreviewCard.css";

const PLOT_SIZE  = 150;   // px – inner chart area (square)
const LEFT_M     = 35;
const TOP_M      = 10;
const BOTTOM_M   = 40;
const RIGHT_M    = 10;
const SVG_W      = PLOT_SIZE + LEFT_M  + RIGHT_M;
const SVG_H      = PLOT_SIZE + TOP_M   + BOTTOM_M;

export default function PreviewCard({ label, tableName, cols, errorColors, chartType = "histogram", onExecuteWrangle }) {
  const svgRef      = useRef(null);
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  const colorScale = errorColors || (() => "steelblue");

  // ── fetch data ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!tableName || !cols || cols.length === 0) return;

    // Guard: histogram needs >= 1 col, heatmap/scatterplot need >= 2
    if ((chartType === "heatmap" || chartType === "scatterplot") && cols.length < 2) return;

    setLoading(true);
    setError(null);
    setData(null);

    if (chartType === "histogram") {
      queryPreviewHistogram({ type: "1d", tablename: tableName, column: cols[0], bins: 10 })
        .then(result => {
          if (result?.success) {
            setData(result.histogram);
          } else {
            setError(result?.error || "Failed to load preview");
          }
          setLoading(false);
        });
    } else if (chartType === "heatmap") {
      queryPreviewHistogram({ type: "2d", tablename: tableName, column_x: cols[0], column_y: cols[1], x_bins: 10, y_bins: 10 })
        .then(result => {
          if (result?.success) {
            setData(result.histogram);
          } else {
            setError(result?.error || "Failed to load preview");
          }
          setLoading(false);
        });
    } else if (chartType === "scatterplot") {
      queryPreviewScatterplot({ tablename: tableName, x_column: cols[0], y_column: cols[1], error_sample_count: 300, total_sample_count: 1000 })
        .then(result => {
          if (result?.success) {
            setData(result.scatterplot_data);
          } else {
            setError(result?.error || "Failed to load preview");
          }
          setLoading(false);
        });
    }
  }, [tableName, cols.join(","), chartType]);

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

// ── 1-D bar chart renderer ─────────────────────────────────────────────────
function draw1D(canvas, histogramData, colorScale) {
  const numHistDataX = histogramData.scaleX.numeric || [];
  const catHistDataX = histogramData.scaleX.categorical || [];

  const numDomainY = (numHistDataX.length === 0 || !numHistDataX[0])
    ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
  const catDomainY = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);

  const xScale = createHybridScales(
    PLOT_SIZE, numHistDataX, catHistDataX, numDomainY, catDomainY, "horizontal"
  );
  const yScale = d3.scaleLinear()
    .domain([0, d3.max(histogramData.histograms, d => d.count.items) || 1]).nice()
    .range([PLOT_SIZE, 0]);

  // Flatten stacked bars
  const myData = [];
  histogramData.histograms.forEach(d => {
    let items = d.count.items;
    Object.keys(d.count).filter(k => k !== "items").forEach(key => {
      myData.push({ bin: d.xBin, type: d.xType, value: d.count[key], name: key, top: items, bottom: items - d.count[key] });
      items -= d.count[key];
    });
    if (items > 0) {
      myData.push({ bin: d.xBin, type: d.xType, value: items, name: "none", top: items, bottom: 0 });
    }
  });

  canvas.append("g")
    .selectAll("rect")
    .data(myData)
    .join("rect")
    .attr("x", d => xScale.apply(d.type === "numeric" ? numHistDataX[d.bin]?.x0 : d.bin, d.type))
    .attr("y", d => yScale(d.top))
    .attr("height", d => Math.max(0, yScale(d.bottom) - yScale(d.top)))
    .attr("width", d => d.type === "numeric"
      ? xScale.numericalBandwidth(numHistDataX[d.bin]?.x0, numHistDataX[d.bin]?.x1)
      : xScale.categoricalBandwidth())
    .attr("fill", d => colorScale(d.name))
    .attr("stroke", "white")
    .attr("stroke-width", 1);

  canvas.append("g").call(d3.axisLeft(yScale).ticks(4)).style("font-size", "7px");
  if (xScale && typeof xScale.draw === "function") xScale.draw(canvas);
}

// ── 2-D heatmap renderer ───────────────────────────────────────────────────
function draw2D(canvas, histogramData, colorScale) {
  const numHistDataX = histogramData.scaleX.numeric || [];
  const catHistDataX = histogramData.scaleX.categorical || [];
  const numHistDataY = histogramData.scaleY.numeric || [];
  const catHistDataY = histogramData.scaleY.categorical || [];

  const numDomainX = (numHistDataX.length === 0 || !numHistDataX[0])
    ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
  const catDomainX = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);
  const numDomainY = (numHistDataY.length === 0 || !numHistDataY[0])
    ? null : [d3.min(numHistDataY, d => d.x0), d3.max(numHistDataY, d => d.x1)];
  const catDomainY = catHistDataY.length === 0 ? null : catHistDataY.map(d => d);

  const xScale = createHybridScales(PLOT_SIZE, numHistDataX, catHistDataX, numDomainX, catDomainX, "horizontal");
  const yScale = createHybridScales(PLOT_SIZE, numHistDataY, catHistDataY, numDomainY, catDomainY, "vertical");

  xScale.draw(canvas);
  yScale.draw(canvas);

  const tileFill = (d) => {
    const keys = Object.keys(d.count).filter(k => k !== "items");
    if (keys.length === 0) return colorScale("none");
    return colorScale(keys[0]);
  };

  const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);

  const tiles = canvas.append("g")
    .selectAll("rect")
    .data(binsToRender)
    .join("rect")
    .attr("x", d => xScale.apply(d.xType === "numeric" ? xScale.numHistData[d.xBin]?.x0 : d.xBin, d.xType))
    .attr("y", d => yScale.apply(d.yType === "numeric" ? yScale.numHistData[d.yBin]?.x1 : d.yBin, d.yType))
    .attr("height", d => d.yType === "numeric"
      ? yScale.numericalBandwidth(yScale.numHistData[d.yBin]?.x1, yScale.numHistData[d.yBin]?.x0)
      : yScale.categoricalBandwidth())
    .attr("width", d => d.xType === "numeric"
      ? xScale.numericalBandwidth(xScale.numHistData[d.xBin]?.x0, xScale.numHistData[d.xBin]?.x1)
      : xScale.categoricalBandwidth())
    .attr("fill", tileFill)
    .attr("stroke", "white")
    .attr("stroke-width", 1);

  createTooltip(tiles,
    d => `<strong>Items:</strong> ${d.count.items}`,
    () => {}, () => {}, () => {}
  );
}

// ── Scatterplot renderer ───────────────────────────────────────────────────
function drawScatter(canvas, scatterData, colorScale) {
  const numHistDataX = scatterData.scaleX.numeric || [];
  const catHistDataX = scatterData.scaleX.categorical || [];
  const numHistDataY = scatterData.scaleY.numeric || [];
  const catHistDataY = scatterData.scaleY.categorical || [];

  const xScale = createHybridScales(
    PLOT_SIZE, numHistDataX, catHistDataX,
    numHistDataX.length === 0 ? null : numHistDataX,
    catHistDataX.length === 0 ? null : catHistDataX,
    "horizontal"
  );
  const yScale = createHybridScales(
    PLOT_SIZE, numHistDataY, catHistDataY,
    numHistDataY.length === 0 ? null : numHistDataY,
    catHistDataY.length === 0 ? null : catHistDataY,
    "vertical"
  );

  xScale.draw(canvas);
  yScale.draw(canvas);

  const circleFill = (d) => {
    if (!d.errors || d.errors.length === 0) return colorScale("none");
    return colorScale(d.errors[0]);
  };

  canvas.selectAll("circle")
    .data(scatterData.data || [])
    .join("circle")
    .attr("cx", d => xScale ? xScale.apply(d.x, d.xType, true) : 0)
    .attr("cy", d => yScale ? yScale.apply(d.y, d.yType, true) : 0)
    .attr("r", 3)
    .attr("fill", circleFill)
    .attr("opacity", 0.7);
}
