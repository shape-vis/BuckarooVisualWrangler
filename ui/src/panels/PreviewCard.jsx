// PreviewCard.jsx
// Renders a small histogram (1D), heatmap (2D), or scatterplot for a preview table.
// Fetches its own data from /api/plots/preview-histogram or /api/plots/preview-scatterplot.

import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { queryBinsForRows, queryPreviewHistogram, queryPreviewScatterplot } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import "../styles/PreviewCard.css";

const PLOT_SIZE  = 150;   // px – inner chart area (square)
const LEFT_M     = 35;
const TOP_M      = 10;
const BOTTOM_M   = 40;
const RIGHT_M    = 10;
const SVG_W      = PLOT_SIZE + LEFT_M  + RIGHT_M;
const SVG_H      = PLOT_SIZE + TOP_M   + BOTTOM_M;
const HIGHLIGHT_COLOR = "#facc15";
const HIGHLIGHT_STROKE = "#1f2937";
const DEFAULT_COLOR_SCALE = () => "steelblue";
const PREVIEW_AXIS_OPTIONS = {
  detailMode: "compact",
  collapseCategoricalThreshold: 4,
  maxCategoricalTicks: 4,
  numericTicks: 3,
};

export default function PreviewCard({
  label,
  tableName,
  sourceTableName = null,
  cols,
  errorColors,
  chartType = "histogram",
  onExecuteWrangle,
  selectedRowIds = [],
  animationType = null,
  sharedCountDomainMax = null,
  impact = null,
  isDestructive = false,
  isSelected = false,
  onSelect = null,
}) {
  const svgRef      = useRef(null);
  const [data, setData]       = useState(null);
  const [comparisonData, setComparisonData] = useState(null);
  const [sourceScatterData, setSourceScatterData] = useState(null);
  const [highlightBins, setHighlightBins] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  const colorScale = errorColors || DEFAULT_COLOR_SCALE;
  const colsKey = (cols || []).join(",");
  const selectedRowsKey = (selectedRowIds || []).map(String).join(",");

  // ── fetch data ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!tableName || !cols || cols.length === 0) return;

    // Guard: histogram needs >= 1 col, heatmap/scatterplot need >= 2
    if ((chartType === "heatmap" || chartType === "scatterplot") && cols.length < 2) return;

    let isActive = true;
    queueMicrotask(() => {
      if (!isActive) return;
      setLoading(true);
      setError(null);
      setData(null);
      setComparisonData(null);
      setHighlightBins(null);
    });

    if (chartType === "histogram") {
      const params = { type: "1d", tablename: tableName, column: cols[0], bins: 10 };
      if (sourceTableName) params.reference_table = sourceTableName;
      const comparisonParams = sourceTableName
        ? { type: "1d", tablename: sourceTableName, column: cols[0], bins: 10, reference_table: sourceTableName }
        : null;

      Promise.all([
        queryPreviewHistogram(params),
        comparisonParams && sourceTableName !== tableName
          ? queryPreviewHistogram(comparisonParams)
          : Promise.resolve(null),
      ]).then(([result, comparisonResult]) => {
        if (!isActive) return;
        if (result?.success) {
          setData(result.histogram);
          setComparisonData(
            comparisonResult?.success ? comparisonResult.histogram : result.histogram
          );
        } else {
          setError(result?.error || "Failed to load preview");
        }
        setLoading(false);
      });
    } else if (chartType === "heatmap") {
      const params = { type: "2d", tablename: tableName, column_x: cols[0], column_y: cols[1], x_bins: 10, y_bins: 10 };
      if (sourceTableName) params.reference_table = sourceTableName;
      const comparisonParams = sourceTableName
        ? { type: "2d", tablename: sourceTableName, column_x: cols[0], column_y: cols[1], x_bins: 10, y_bins: 10, reference_table: sourceTableName }
        : null;

      Promise.all([
        queryPreviewHistogram(params),
        comparisonParams && sourceTableName !== tableName
          ? queryPreviewHistogram(comparisonParams)
          : Promise.resolve(null),
      ]).then(([result, comparisonResult]) => {
        if (!isActive) return;
        if (result?.success) {
          setData(result.histogram);
          setComparisonData(
            comparisonResult?.success ? comparisonResult.histogram : result.histogram
          );
        } else {
          setError(result?.error || "Failed to load preview");
        }
        setLoading(false);
      });
    } else if (chartType === "scatterplot") {
      const scatterParams = {
        tablename: tableName,
        x_column: cols[0],
        y_column: cols[1],
        error_sample_count: 300,
        total_sample_count: 1000,
      };
      if (selectedRowIds?.length) {
        scatterParams.selected_row_ids = selectedRowsKey;
      }

      queryPreviewScatterplot(scatterParams)
        .then(result => {
          if (!isActive) return;
          if (result?.success) {
            setData(result.scatterplot_data);
          } else {
            setError(result?.error || "Failed to load preview");
          }
          setLoading(false);
        });
    }

    return () => {
      isActive = false;
    };
  }, [tableName, sourceTableName, cols, colsKey, chartType, selectedRowIds, selectedRowsKey]);

  useEffect(() => {
    let isActive = true;
    queueMicrotask(() => {
      if (isActive) setSourceScatterData(null);
    });

    if (
      chartType !== "scatterplot" ||
      !animationType ||
      !sourceTableName ||
      !cols ||
      cols.length < 2 ||
      !selectedRowsKey
    ) {
      return () => {
        isActive = false;
      };
    }

    queryPreviewScatterplot({
      tablename: sourceTableName,
      x_column: cols[0],
      y_column: cols[1],
      error_sample_count: 0,
      total_sample_count: 0,
      selected_row_ids: selectedRowsKey,
    }).then(result => {
      if (!isActive) return;
      if (result?.success) {
        setSourceScatterData(result.scatterplot_data);
      }
    });

    return () => {
      isActive = false;
    };
  }, [sourceTableName, cols, colsKey, chartType, animationType, selectedRowsKey]);

  useEffect(() => {
    let isActive = true;
    queueMicrotask(() => {
      if (isActive) setHighlightBins(null);
    });

    if (!tableName || !cols || cols.length === 0 || !selectedRowIds?.length) {
      return () => {
        isActive = false;
      };
    }

    if (chartType === "scatterplot") {
      return () => {
        isActive = false;
      };
    }

    if (chartType === "histogram") {
      queryBinsForRows({
        table: tableName,
        type: "1d",
        column: cols[0],
        row_ids: selectedRowIds,
        reference_table: sourceTableName,
      }).then(result => {
        if (!isActive || !result?.success) return;
        setHighlightBins(new Set((result.bins || []).map(String)));
      });
    } else if (chartType === "heatmap" && cols.length >= 2) {
      queryBinsForRows({
        table: tableName,
        type: "2d",
        column_x: cols[0],
        column_y: cols[1],
        row_ids: selectedRowIds,
        reference_table: sourceTableName,
      }).then(result => {
        if (!isActive || !result?.success) return;
        setHighlightBins(new Set((result.bins || []).map(b => `${b.xBin}|${b.yBin}`)));
      });
    }

    return () => {
      isActive = false;
    };
  }, [tableName, sourceTableName, cols, colsKey, chartType, selectedRowIds, selectedRowsKey]);

  // ── draw chart ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!data || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const canvas = svg.append("g")
      .attr("transform", `translate(${LEFT_M}, ${TOP_M})`);

    if (chartType === "histogram") {
      draw1D(canvas, data, colorScale, highlightBins, {
        comparisonData,
        sharedCountDomainMax,
      });
    } else if (chartType === "heatmap") {
      draw2D(canvas, data, colorScale, highlightBins, comparisonData);
    } else if (chartType === "scatterplot") {
      drawScatter(canvas, data, colorScale, selectedRowIds, {
        animationType,
        sourceScatterData,
      });
    }
  }, [
    data,
    comparisonData,
    sourceScatterData,
    chartType,
    highlightBins,
    selectedRowsKey,
    animationType,
    sharedCountDomainMax,
    colorScale,
    selectedRowIds,
  ]);

  const cardClassName = [
    "repair-method",
    "preview-card",
    onSelect ? "preview-card--selectable" : "",
    isSelected ? "preview-card--selected" : "",
  ].filter(Boolean).join(" ");

  const handleCardKeyDown = (event) => {
    if (!onSelect || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onSelect();
  };

  return (
    <div
      className={cardClassName}
      onClick={onSelect || undefined}
      onKeyDown={handleCardKeyDown}
      role={onSelect ? "button" : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-pressed={onSelect ? isSelected : undefined}
    >
      <div className="preview-card-chart">
        <div className="preview-card-label">{label}</div>
        {loading && <div className="preview-card-loading">Loading…</div>}
        {error   && <div className="preview-card-error">{error}</div>}
        {!loading && !error && (
          <svg ref={svgRef} viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ width: "100%", height: "auto" }} />
        )}
      </div>
      {impact && (
        <div className="preview-card-impact" aria-label={`${label} impact`}>
          <div>
            <span>Rows affected</span>
            <strong>{formatImpactValue(impact.rowsAffected, impact.loading)}</strong>
          </div>
          <div>
            <span>Values changed</span>
            <strong>{formatImpactValue(impact.valuesChanged, impact.loading)}</strong>
          </div>
        </div>
      )}
      {onExecuteWrangle && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onExecuteWrangle();
          }}
          className={`regButton preview-card-execute ${isDestructive ? "preview-card-execute--destructive" : ""}`}
        >
          {isDestructive ? "Review deletion" : "Apply repair"}
        </button>
      )}
    </div>
  );
}

// ── 1-D bar chart renderer ─────────────────────────────────────────────────
function formatImpactValue(value, loading) {
  if (loading) return "...";
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, number).toLocaleString() : "-";
}

function draw1D(canvas, histogramData, colorScale, highlightBins = null, options = {}) {
  const { comparisonData = null, sharedCountDomainMax = null } = options;
  const referenceNumeric = comparisonData?.scaleX?.numeric || [];
  const numHistDataX = referenceNumeric.length > 0
    ? referenceNumeric
    : (histogramData.scaleX.numeric || []);
  const catHistDataX = mergeCategoricalScale(
    comparisonData?.scaleX?.categorical,
    histogramData.scaleX.categorical,
  );

  const numDomainY = (numHistDataX.length === 0 || !numHistDataX[0])
    ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
  const catDomainY = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);

  const xScale = createHybridScales(
    PLOT_SIZE, numHistDataX, catHistDataX, numDomainY, catDomainY, "horizontal"
  );
  const currentMax = d3.max(histogramData.histograms, d => d.count.items) || 1;
  const comparisonMax = d3.max(comparisonData?.histograms || [], d => d.count.items) || 1;
  const requestedDomainMax = Number(sharedCountDomainMax);
  const yDomainMax = Number.isFinite(requestedDomainMax) && requestedDomainMax > 0
    ? Math.max(requestedDomainMax, currentMax, comparisonMax)
    : Math.max(currentMax, comparisonMax);
  const yScale = d3.scaleLinear()
    .domain([0, yDomainMax]).nice()
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

  const hasHighlights = highlightBins instanceof Set && highlightBins.size > 0;
  const isHighlighted = (d) => hasHighlights && highlightBins.has(String(d.bin));

  const bars = canvas.append("g")
    .selectAll("rect")
    .data(myData)
    .join("rect")
    .attr("x", d => xScale.apply(d.type === "numeric" ? numHistDataX[d.bin]?.x0 : d.bin, d.type))
    .attr("y", d => yScale(d.top))
    .attr("height", d => Math.max(0, yScale(d.bottom) - yScale(d.top)))
    .attr("width", d => d.type === "numeric"
      ? xScale.numericalBandwidth(numHistDataX[d.bin]?.x0, numHistDataX[d.bin]?.x1)
      : xScale.categoricalBandwidth())
    .attr("fill", d => isHighlighted(d) ? HIGHLIGHT_COLOR : colorScale(d.name))
    .attr("opacity", d => hasHighlights ? (isHighlighted(d) ? 1 : 0.22) : 1)
    .attr("stroke", "white")
    .attr("stroke-width", 1);

  bars.filter(isHighlighted).raise();

  canvas.append("g").call(d3.axisLeft(yScale).ticks(4)).style("font-size", "7px");
  if (xScale && typeof xScale.draw === "function") xScale.draw(canvas, PREVIEW_AXIS_OPTIONS);
}

// ── 2-D heatmap renderer ───────────────────────────────────────────────────
function draw2D(canvas, histogramData, colorScale, highlightBins = null, comparisonData = null) {
  const referenceNumericX = comparisonData?.scaleX?.numeric || [];
  const referenceNumericY = comparisonData?.scaleY?.numeric || [];
  const numHistDataX = referenceNumericX.length > 0
    ? referenceNumericX
    : (histogramData.scaleX.numeric || []);
  const catHistDataX = mergeCategoricalScale(
    comparisonData?.scaleX?.categorical,
    histogramData.scaleX.categorical,
  );
  const numHistDataY = referenceNumericY.length > 0
    ? referenceNumericY
    : (histogramData.scaleY.numeric || []);
  const catHistDataY = mergeCategoricalScale(
    comparisonData?.scaleY?.categorical,
    histogramData.scaleY.categorical,
  );

  const numDomainX = (numHistDataX.length === 0 || !numHistDataX[0])
    ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
  const catDomainX = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);
  const numDomainY = (numHistDataY.length === 0 || !numHistDataY[0])
    ? null : [d3.min(numHistDataY, d => d.x0), d3.max(numHistDataY, d => d.x1)];
  const catDomainY = catHistDataY.length === 0 ? null : catHistDataY.map(d => d);

  const xScale = createHybridScales(PLOT_SIZE, numHistDataX, catHistDataX, numDomainX, catDomainX, "horizontal");
  const yScale = createHybridScales(PLOT_SIZE, numHistDataY, catHistDataY, numDomainY, catDomainY, "vertical");

  xScale.draw(canvas, PREVIEW_AXIS_OPTIONS);
  yScale.draw(canvas, PREVIEW_AXIS_OPTIONS);

  const tileFill = (d) => {
    const keys = Object.keys(d.count).filter(k => k !== "items");
    if (keys.length === 0) return colorScale("none");
    return colorScale(keys[0]);
  };

  const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);
  const hasHighlights = highlightBins instanceof Set && highlightBins.size > 0;
  const isHighlighted = (d) => hasHighlights && highlightBins.has(`${d.xBin}|${d.yBin}`);

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
    .attr("fill", d => isHighlighted(d) ? HIGHLIGHT_COLOR : tileFill(d))
    .attr("opacity", d => hasHighlights ? (isHighlighted(d) ? 1 : 0.22) : 1)
    .attr("stroke", "white")
    .attr("stroke-width", 1);

  tiles.filter(isHighlighted).raise();

  createTooltip(tiles,
    d => `<strong>Items:</strong> ${d.count.items}`,
    () => {}, () => {}, () => {}
  );
}

// ── Scatterplot renderer ───────────────────────────────────────────────────
function drawScatter(canvas, scatterData, colorScale, selectedRowIds = [], options = {}) {
  const { animationType = null, sourceScatterData = null } = options;
  const animationSourceData = animationType ? sourceScatterData : null;

  const numHistDataX = mergeNumericScale(scatterData.scaleX?.numeric, animationSourceData?.scaleX?.numeric);
  const numHistDataY = mergeNumericScale(scatterData.scaleY?.numeric, animationSourceData?.scaleY?.numeric);

  const rowsForScale = [
    ...(scatterData.data || []),
    ...((animationSourceData?.data || [])),
  ];
  const actualXCats = new Set(rowsForScale.filter(d => d.xType === "categorical").map(d => String(d.x)));
  const actualYCats = new Set(rowsForScale.filter(d => d.yType === "categorical").map(d => String(d.y)));
  const catHistDataX = colorScale
    ? mergeCategoricalScale(scatterData.scaleX?.categorical, animationSourceData?.scaleX?.categorical)
        .filter(v => actualXCats.has(String(v)))
    : [];
  const catHistDataY = colorScale
    ? mergeCategoricalScale(scatterData.scaleY?.categorical, animationSourceData?.scaleY?.categorical)
        .filter(v => actualYCats.has(String(v)))
    : [];

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

  xScale.draw(canvas, PREVIEW_AXIS_OPTIONS);
  yScale.draw(canvas, PREVIEW_AXIS_OPTIONS);

  const circleFill = (d) => {
    if (!d.errors || d.errors.length === 0) return colorScale("none");
    return colorScale(d.errors[0]);
  };

  const selectedIdSet = new Set((selectedRowIds || []).map(String));
  const hasHighlights = selectedIdSet.size > 0;
  const isHighlighted = (d) => selectedIdSet.has(String(d.ID));

  const plottedPoints = (scatterData.data || [])
    .map(row => ({ row, position: pointPosition(row, xScale, yScale) }))
    .filter(d => d.position);

  const circles = canvas.append("g")
    .attr("class", "preview-point-layer")
    .selectAll("circle")
    .data(plottedPoints)
    .join("circle")
    .attr("cx", d => d.position.cx)
    .attr("cy", d => d.position.cy)
    .attr("r", 3)
    .attr("fill", d => isHighlighted(d.row) ? HIGHLIGHT_COLOR : circleFill(d.row))
    .attr("opacity", d => hasHighlights ? (isHighlighted(d.row) ? 1 : 0.22) : 0.7)
    .attr("stroke", d => isHighlighted(d.row) ? HIGHLIGHT_STROKE : "white")
    .attr("stroke-width", d => isHighlighted(d.row) ? 1.2 : 0.5);

  circles.filter(d => isHighlighted(d.row)).raise();

  drawScatterAnimation(
    canvas,
    scatterData,
    animationSourceData,
    selectedRowIds,
    animationType,
    xScale,
    yScale
  );
}

function mergeNumericScale(primary = [], secondary = []) {
  const values = [...numericValues(primary), ...numericValues(secondary)];
  if (values.length === 0) return [];
  return [d3.min(values), d3.max(values)];
}

function numericValues(values = []) {
  if (!Array.isArray(values)) return [];
  return values
    .filter(v => v !== null && v !== undefined && v !== "")
    .map(Number)
    .filter(Number.isFinite);
}

function mergeCategoricalScale(primary = [], secondary = []) {
  const seen = new Set();
  const merged = [];

  [...safeArray(primary), ...safeArray(secondary)].forEach(value => {
    if (value === null || value === undefined) return;
    const key = String(value);
    if (seen.has(key)) return;
    seen.add(key);
    merged.push(value);
  });

  return merged;
}

function safeArray(values) {
  return Array.isArray(values) ? values : [];
}

function pointPosition(row, xScale, yScale) {
  const cx = xScale ? xScale.apply(row.x, row.xType, true) : null;
  const cy = yScale ? yScale.apply(row.y, row.yType, true) : null;

  if (!Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  return { cx, cy };
}

function rowsById(rows = []) {
  const lookup = new Map();
  rows.forEach(row => lookup.set(String(row.ID), row));
  return lookup;
}

function drawScatterAnimation(canvas, scatterData, sourceScatterData, selectedRowIds, animationType, xScale, yScale) {
  if (!animationType || !sourceScatterData || !selectedRowIds?.length) return;

  const selectedIds = selectedRowIds.map(String);
  const sourceRows = rowsById(sourceScatterData.data || []);
  const previewRows = rowsById(scatterData.data || []);
  const layer = canvas.append("g")
    .attr("class", "preview-animation-layer")
    .attr("pointer-events", "none");

  if (animationType === "delete") {
    drawDeleteAnimation(layer, selectedIds, sourceRows, xScale, yScale);
  } else if (animationType === "impute") {
    drawImputeAnimation(layer, selectedIds, sourceRows, previewRows, xScale, yScale);
  }
}

function drawDeleteAnimation(layer, selectedIds, sourceRows, xScale, yScale) {
  const deletedPoints = selectedIds
    .map(id => sourceRows.get(id))
    .filter(Boolean)
    .map(row => ({ row, position: pointPosition(row, xScale, yScale) }))
    .filter(d => d.position);

  if (deletedPoints.length === 0) return;

  layer.selectAll("circle.preview-delete-dot")
    .data(deletedPoints)
    .join("circle")
    .attr("class", "preview-delete-dot")
    .attr("cx", d => d.position.cx)
    .attr("cy", d => d.position.cy)
    .attr("r", 3)
    .attr("fill", HIGHLIGHT_COLOR)
    .attr("stroke", HIGHLIGHT_STROKE)
    .attr("stroke-width", 1.4)
    .attr("opacity", 0)
    .transition()
    .delay((_, i) => i * 70)
    .duration(300)
    .ease(d3.easeCubicOut)
    .attr("opacity", 1)
    .attr("r", 6)
    .transition()
    .delay(450)
    .duration(600)
    .ease(d3.easeCubicIn)
    .attr("opacity", 0)
    .attr("r", 0);
}

function drawImputeAnimation(layer, selectedIds, sourceRows, previewRows, xScale, yScale) {
  const moves = selectedIds
    .map(id => {
      const sourceRow = sourceRows.get(id);
      const previewRow = previewRows.get(id);
      if (!sourceRow || !previewRow) return null;

      const start = pointPosition(sourceRow, xScale, yScale);
      const end = pointPosition(previewRow, xScale, yScale);
      if (!start || !end) return null;

      return { id, start, end };
    })
    .filter(Boolean);

  if (moves.length === 0) return;

  const pathBack = layer.append("g")
    .selectAll("line.preview-impute-path-back")
    .data(moves)
    .join("line")
    .attr("class", "preview-impute-path-back")
    .attr("x1", d => d.start.cx)
    .attr("y1", d => d.start.cy)
    .attr("x2", d => d.start.cx)
    .attr("y2", d => d.start.cy)
    .attr("stroke", HIGHLIGHT_STROKE)
    .attr("stroke-width", 3)
    .attr("stroke-linecap", "round")
    .attr("stroke-dasharray", "3 3")
    .attr("opacity", 0);

  const pathFront = layer.append("g")
    .selectAll("line.preview-impute-path-front")
    .data(moves)
    .join("line")
    .attr("class", "preview-impute-path-front")
    .attr("x1", d => d.start.cx)
    .attr("y1", d => d.start.cy)
    .attr("x2", d => d.start.cx)
    .attr("y2", d => d.start.cy)
    .attr("stroke", HIGHLIGHT_COLOR)
    .attr("stroke-width", 1.5)
    .attr("stroke-linecap", "round")
    .attr("stroke-dasharray", "3 3")
    .attr("opacity", 0);

  layer.append("g")
    .selectAll("circle.preview-impute-start")
    .data(moves)
    .join("circle")
    .attr("class", "preview-impute-start")
    .attr("cx", d => d.start.cx)
    .attr("cy", d => d.start.cy)
    .attr("r", 3.5)
    .attr("fill", HIGHLIGHT_COLOR)
    .attr("stroke", HIGHLIGHT_STROKE)
    .attr("stroke-width", 1)
    .attr("opacity", 0.35);

  pathBack.transition()
    .delay((_, i) => 180 + i * 70)
    .duration(1000)
    .ease(d3.easeCubicInOut)
    .attr("x2", d => d.end.cx)
    .attr("y2", d => d.end.cy)
    .attr("opacity", 0.35);

  pathFront.transition()
    .delay((_, i) => 180 + i * 70)
    .duration(1000)
    .ease(d3.easeCubicInOut)
    .attr("x2", d => d.end.cx)
    .attr("y2", d => d.end.cy)
    .attr("opacity", 0.85);

  layer.append("g")
    .selectAll("circle.preview-impute-dot")
    .data(moves)
    .join("circle")
    .attr("class", "preview-impute-dot")
    .attr("cx", d => d.start.cx)
    .attr("cy", d => d.start.cy)
    .attr("r", 5)
    .attr("fill", HIGHLIGHT_COLOR)
    .attr("stroke", HIGHLIGHT_STROKE)
    .attr("stroke-width", 1.4)
    .attr("opacity", 0)
    .transition()
    .delay((_, i) => 120 + i * 70)
    .duration(180)
    .attr("opacity", 1)
    .transition()
    .duration(1000)
    .ease(d3.easeCubicInOut)
    .attr("cx", d => d.end.cx)
    .attr("cy", d => d.end.cy)
    .transition()
    .delay(200)
    .duration(350)
    .attr("opacity", 0);
}
