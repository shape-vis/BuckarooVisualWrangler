import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { querySample2d, querySample2dRange } from "../utils/serverCalls.jsx";
import { createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import {
  BRUSH_CLICK_GUARD_MS, HIGHLIGHT_FILL, plainColorScale, pointColor, useCachedPlotData, useLatestRef,
} from "./errorPlots.js";
import { scatterScales } from "./previewPlots.js";

// Module-level cache so base samples survive component unmount/remount (e.g. focus zoom in/out).
import { scatterPlotCache } from "../store/visualizationCaches.jsx";

function ScatterPlot({
  xPos,
  yPos,
  size,
  attrX,
  attrY,
  errorColors,
  errorSampleCount = 300,
  totalSampleCount = 1000,
}) {
  const { tableName } = useTableName();
  const drawingRef = useRef(null);
  const clearSelectionRef = useRef(() => {});

  // Refs to D3 selections / scales so the highlight effect can re-color
  // without rebuilding the whole chart.
  const circlesRef = useRef(null);
  const colorScaleRef = useRef(plainColorScale);

  const { highlightedRowIds, setHighlightedRowIds, clearHighlight } = useSelection();

  // Keep a stable ref to setHighlightedRowIds so closures inside the draw
  // effect always call the latest version without stale captures.
  const setHighlightedRef = useLatestRef(setHighlightedRowIds);

  // ── data fetch ────────────────────────────────────────────────────────────
  const sampleData = useCachedPlotData(
    scatterPlotCache,
    `${tableName}|${attrX}|${attrY}`,
    async ({ useRange, minId, maxId }) => {
      const response = useRange
        ? await querySample2dRange(tableName, attrX, attrY, errorSampleCount, totalSampleCount, minId, maxId)
        : await querySample2d(tableName, attrX, attrY, errorSampleCount, totalSampleCount);

      if (!response || !response.success) {
        console.error("[SCATTERPLOT] API call failed:", response);
        throw new Error(`2D ScatterPlot API failed: ${response?.error || "Unknown error"}`);
      }

      const data = response.scatterplot_data;
      if (!data) throw new Error("No scatterplot data returned from server");
      return data;
    },
    [tableName, attrX, attrY, errorSampleCount, totalSampleCount],
  );

  // ── draw chart ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sampleData) return;

    const canvas = d3.select(drawingRef.current);
    canvas.selectAll("*").remove();

    const colorScale = errorColors || plainColorScale;
    colorScaleRef.current = colorScale;

    // Without error colours the categorical (null) values are left off the axes
    const { xScale, yScale } = scatterScales(sampleData, size, Boolean(errorColors));

    xScale.draw(canvas);
    yScale.draw(canvas);

    const circleFill = (d) => pointColor(colorScale, d);

    // When no null columns, filter out categorical-null points so no null area is rendered.
    let chartData = sampleData.data || [];
    if (!errorColors) chartData = chartData.filter(d => d.xType !== "categorical" && d.yType !== "categorical");

    const circles = canvas.selectAll("circle")
      .data(chartData)
      .join("circle")
      .attr("cx", d => xScale.apply(d.x, d.xType, true))
      .attr("cy", d => yScale.apply(d.y, d.yType, true))
      .attr("r", 4)
      .attr("cursor", "pointer")
      .attr("fill", circleFill);

    circlesRef.current = circles;

    // ── Brush for drag-to-select-multiple-points ───────────────────────────
    const brushGroup = canvas.append("g").attr("class", "scatter-brush");

    let lastBrushEnd = 0;

    const brush = d3.brush()
      .extent([[0, 0], [size, size]])
      .on("brush end", (event) => {
        if (event.type === "end") lastBrushEnd = Date.now();
        if (!event.selection) {
          circles.attr("fill", circleFill);
          if (event.type === "end" && event.sourceEvent) {
            clearHighlight();
          }
          return;
        }
        const [[x0, y0], [x1, y1]] = event.selection;
        const brushedIds = [];
        circles.each(function (d) {
          const cx = +d3.select(this).attr("cx");
          const cy = +d3.select(this).attr("cy");
          const inside = cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1;
          d3.select(this).attr("fill", inside ? HIGHLIGHT_FILL : circleFill(d));
          if (inside) brushedIds.push(d.ID);
        });

        if (event.type === "end" && brushedIds.length > 0) {
          setHighlightedRef.current([...new Set(brushedIds)], [attrX, attrY], "scatterplot");
        }
      });

    brushGroup.call(brush);
    brushGroup.lower();

    clearSelectionRef.current = () => {
      circles.attr("fill", circleFill);
      brushGroup.call(brush.move, null);
    };

    createTooltip(circles,
      d => {
        const bin = String(d.x) + " x " + String(d.y);
        let errorList = "";
        if (d.errors && d.errors.length >= 1) errorList = "<br><strong>Errors: </strong>" + d.errors[0];
        if (d.errors && d.errors.length > 1) d.errors.slice(1).forEach(k => { errorList += `, ${k}`; });
        return `<strong>Data:</strong> ${bin}${errorList}`;
      },
      (d) => {
        // Skip click if a brush drag just ended (prevents overwriting multi-select).
        if (Date.now() - lastBrushEnd < BRUSH_CLICK_GUARD_MS) return;
        // Left click: set this point's ID as the cross-chart highlight.
        setHighlightedRef.current([d.ID], [attrX, attrY], "scatterplot");
      },
    );

    return () => { canvas.selectAll("*").remove(); };
  }, [size, sampleData]);

  // ── react to cross-chart highlight changes ────────────────────────────────
  useEffect(() => {
    if (!circlesRef.current) return;
    const rowIdSet = highlightedRowIds ? new Set(highlightedRowIds) : null;
    const colorScale = colorScaleRef.current;
    circlesRef.current.attr("fill", d => {
      if (rowIdSet && rowIdSet.has(d.ID)) return HIGHLIGHT_FILL;
      return pointColor(colorScale, d);
    });
  }, [highlightedRowIds, sampleData]);

  function handleBackgroundClick() {
    clearSelectionRef.current();
    clearHighlight();
  }

  return (
    <g transform={`translate(${xPos}, ${yPos})`} className="scatter-canvas">
      <rect width={size} height={size} fill="#ffffff00" onClick={handleBackgroundClick} />
      <g ref={drawingRef}></g>
    </g>
  );
}

// Adds memoization (shallow compare) - may need to make a custom checker.
export default React.memo(ScatterPlot);
