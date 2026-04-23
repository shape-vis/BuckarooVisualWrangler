import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { querySample2d, querySample2dRange } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useRowRange } from "../store/RowRangeContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";

// Module-level cache so base samples survive component unmount/remount (e.g. focus zoom in/out).
import { scatterPlotCache } from "../store/visualizationCaches.jsx";
const baseSampleCache = scatterPlotCache;

function ScatterPlot({
  cellID,
  xPos,
  yPos,
  size,
  attrX,
  attrY,
  errorColors,
  errorSampleCount = 300,
  totalSampleCount = 1000,
}) {
  const { tableName: table_name } = useTableName();
  const drawingRef = useRef(null);
  const clearSelectionRef = useRef(() => {});
  const [sampleData, setSampleData] = React.useState(null);

  // Refs to D3 selections / scales so the highlight effect can re-color
  // without rebuilding the whole chart.
  const circlesRef = useRef(null);
  const colorScaleRef = useRef(() => "steelblue");

  const { highlightedRowIds, setHighlightedRowIds, clearHighlight, highlightRevision } = useSelection();

  // Keep a stable ref to setHighlightedRowIds so closures inside the draw
  // effect always call the latest version without stale captures.
  const setHighlightedRef = useRef(setHighlightedRowIds);
  const highlightRevisionRef = useRef(highlightRevision);
  useEffect(() => { setHighlightedRef.current = setHighlightedRowIds; }, [setHighlightedRowIds]);
  useEffect(() => { highlightRevisionRef.current = highlightRevision; }, [highlightRevision]);

  const { useRange, minId, maxId } = useRowRange();

  // ── data fetch ────────────────────────────────────────────────────────────
  useEffect(() => {
    const cacheKey = `${table_name}|${attrX}|${attrY}`;

    async function fetchData() {
      // Restore cached base sample instead of re-fetching (survives unmount/remount from focus zoom).
      if (!useRange && baseSampleCache.has(cacheKey)) {
        setSampleData(baseSampleCache.get(cacheKey));
        return;
      }

      try {
        const response = useRange
          ? await querySample2dRange(table_name, attrX, attrY, errorSampleCount, totalSampleCount, minId, maxId)
          : await querySample2d(table_name, attrX, attrY, errorSampleCount, totalSampleCount);
        console.log("[SCATTERPLOT] Response:", response);

        if (!response || !response.success) {
          console.error("[SCATTERPLOT] API call failed:", response);
          throw new Error(`2D ScatterPlot API failed: ${response?.error || "Unknown error"}`);
        }

        const data = response.scatterplot_data;
        if (!data) throw new Error("No scatterplot data returned from server");

        setSampleData(data);

        // Cache the base sample so future mounts restore it without re-fetching.
        if (!useRange) {
          baseSampleCache.set(cacheKey, data);
        }
      } catch (err) {
        console.error(err?.message || err);
      }
    }
    fetchData();
  }, [table_name, attrX, attrY, errorSampleCount, totalSampleCount, useRange, minId, maxId]);

  // ── draw chart ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sampleData) return;

    const canvas = d3.select(drawingRef.current);
    canvas.selectAll("*").remove();

    const colorScale = errorColors || (() => "steelblue");
    colorScaleRef.current = colorScale;

    const numHistDataX = sampleData.scaleX.numeric || [];
    const numHistDataY = sampleData.scaleY.numeric || [];

    const actualXCats = new Set((sampleData.data || []).filter(d => d.xType === "categorical").map(d => d.x));
    const actualYCats = new Set((sampleData.data || []).filter(d => d.yType === "categorical").map(d => d.y));
    const catHistDataX = errorColors ? (sampleData.scaleX.categorical || []).filter(v => actualXCats.has(v)) : [];
    const catHistDataY = errorColors ? (sampleData.scaleY.categorical || []).filter(v => actualYCats.has(v)) : [];

    const xScale = createHybridScales(
      size, numHistDataX, catHistDataX,
      numHistDataX.length === 0 ? null : numHistDataX,
      catHistDataX.length === 0 ? null : catHistDataX,
      "horizontal"
    );
    const yScale = createHybridScales(
      size, numHistDataY, catHistDataY,
      numHistDataY.length === 0 ? null : numHistDataY,
      catHistDataY.length === 0 ? null : catHistDataY,
      "vertical"
    );

    xScale.draw(canvas);
    yScale.draw(canvas);

    const circleFill = (d, highlightSet) => {
      if (highlightSet && highlightSet.has(d.ID)) return "gold";
      if (!d.errors || d.errors.length === 0) return colorScale("none");
      if (d.errors.length === 1) return colorScale(d.errors[0]);
      return colorScale(d.errors[0]);
    };

    // When no null columns, filter out categorical-null points so no null area is rendered.
    const chartData = errorColors
      ? (sampleData.data || [])
      : (sampleData.data || []).filter(d => d.xType !== "categorical" && d.yType !== "categorical");

    const circles = canvas.selectAll("circle")
      .data(chartData)
      .join("circle")
      .attr("cx", d => xScale ? xScale.apply(d.x, d.xType, true) : 0)
      .attr("cy", d => yScale ? yScale.apply(d.y, d.yType, true) : 0)
      .attr("r", 4)
      .attr("cursor", "pointer")
      .attr("fill", d => circleFill(d, null));

    circlesRef.current = circles;

    // ── Brush for drag-to-select-multiple-points ───────────────────────────
    const brushGroup = canvas.append("g").attr("class", "scatter-brush");

    let lastBrushEnd = 0;

    const brush = d3.brush()
      .extent([[0, 0], [size, size]])
      .on("brush end", (event) => {
        if (event.type === "end") lastBrushEnd = Date.now();
        if (!event.selection) {
          circles.attr("fill", d => circleFill(d, null));
          if (event.type === "end" && event.sourceEvent) {
            clearHighlight();
          }
          return;
        }
        const [[x0, y0], [x1, y1]] = event.selection;
        const brushedIds = [];
        const requestRevision = highlightRevisionRef.current;
        circles.each(function (d) {
          const cx = +d3.select(this).attr("cx");
          const cy = +d3.select(this).attr("cy");
          const inside = cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1;
          d3.select(this).attr("fill", inside ? "gold" : circleFill(d, null));
          if (inside) brushedIds.push(d.ID);
        });

        if (event.type === "end" && brushedIds.length > 0) {
          if (highlightRevisionRef.current !== requestRevision) return;
          setHighlightedRef.current([...new Set(brushedIds)], [attrX, attrY], "scatterplot");
        }
      });

    brushGroup.call(brush);
    brushGroup.lower();

    clearSelectionRef.current = () => {
      circles.attr("fill", d => circleFill(d, null));
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
      (d, event) => {
        // Skip click if a brush drag just ended (prevents overwriting multi-select).
        if (Date.now() - lastBrushEnd < 300) return;
        // Left click: set this point's ID as the cross-chart highlight.
        setHighlightedRef.current([d.ID], [attrX, attrY], "scatterplot");
      },
      (d) => { /* right click – unused */ },
      (d) => { /* double click – unused */ }
    );

    return () => { canvas.selectAll("*").remove(); };
  }, [size, sampleData]);

  // ── react to cross-chart highlight changes ────────────────────────────────
  useEffect(() => {
    if (!circlesRef.current) return;
    const rowIdSet = highlightedRowIds ? new Set(highlightedRowIds) : null;
    const colorScale = colorScaleRef.current;
    circlesRef.current.attr("fill", d => {
      if (rowIdSet && rowIdSet.has(d.ID)) return "gold";
      if (!d.errors || d.errors.length === 0) return colorScale("none");
      if (d.errors.length === 1) return colorScale(d.errors[0]);
      return colorScale(d.errors[0]);
    });
  }, [highlightedRowIds, sampleData]);

  function handleBackgroundClick() {
    clearSelectionRef.current();
    clearHighlight();
  }

  return (
    <g key={cellID} transform={`translate(${xPos}, ${yPos})`} className="scatter-canvas">
      <rect width={size} height={size} fill="#ffffff00" onClick={handleBackgroundClick} />
      <g ref={drawingRef}></g>
    </g>
  );
}

// Adds memoization (shallow copy) - may need to make a custom checker.
export default React.memo(ScatterPlot);
