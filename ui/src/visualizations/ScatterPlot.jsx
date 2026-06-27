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
const SELECTED_FILL = "#facc15";
const SELECTED_STROKE = "#1f2937";

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
  detailMode = "focused",
}) {
  const { tableName: table_name } = useTableName();
  const drawingRef = useRef(null);
  const clearSelectionRef = useRef(() => {});
  const [sampleData, setSampleData] = React.useState(null);

  // Refs to D3 selections / scales so the highlight effect can re-color
  // without rebuilding the whole chart.
  const circlesRef = useRef(null);
  const colorScaleRef = useRef(() => "steelblue");
  // Holds the current selection set so the draw effect can re-apply the selected
  // highlight whenever the chart is (re)drawn — e.g. on zoom in/out or resize.
  const highlightSetRef = useRef(null);

  const { highlightedRowIds, highlightedCols, setHighlightedRowIds, clearHighlight, highlightRevision } = useSelection();
  const isFocused = detailMode === "focused";
  const shouldHighlightSelection = highlightedRowIds?.length > 0 && (
    highlightedCols?.length === 1
      ? highlightedCols.includes(attrX) || highlightedCols.includes(attrY)
      : highlightedCols?.includes(attrX) && highlightedCols?.includes(attrY)
  );
  highlightSetRef.current = shouldHighlightSelection ? new Set(highlightedRowIds.map(String)) : null;

  // Keep a stable ref to setHighlightedRowIds so closures inside the draw
  // effect always call the latest version without stale captures.
  const setHighlightedRef = useRef(setHighlightedRowIds);
  const highlightRevisionRef = useRef(highlightRevision);
  const highlightedRowIdsRef = useRef(highlightedRowIds);
  const highlightedColsRef = useRef(highlightedCols);
  useEffect(() => { setHighlightedRef.current = setHighlightedRowIds; }, [setHighlightedRowIds]);
  useEffect(() => { highlightRevisionRef.current = highlightRevision; }, [highlightRevision]);
  useEffect(() => { highlightedRowIdsRef.current = highlightedRowIds; }, [highlightedRowIds]);
  useEffect(() => { highlightedColsRef.current = highlightedCols; }, [highlightedCols]);

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

    xScale.draw(canvas, { detailMode });
    yScale.draw(canvas, { detailMode });

    const circleFill = (d) => {
      if (!d.errors || d.errors.length === 0) return colorScale("none");
      if (d.errors.length === 1) return colorScale(d.errors[0]);
      return colorScale(d.errors[0]);
    };

    const applyCircleEmphasis = (highlightSet = null) => {
      const activeHighlightSet = highlightSet?.size ? highlightSet : null;

      circles
        .attr("fill", d => activeHighlightSet?.has(String(d.ID)) ? SELECTED_FILL : circleFill(d))
        .attr("opacity", d => !activeHighlightSet ? 0.92 : activeHighlightSet.has(String(d.ID)) ? 1 : 0.18)
        .attr("r", d => activeHighlightSet?.has(String(d.ID)) ? 5 : 4)
        .attr("stroke", d => activeHighlightSet?.has(String(d.ID)) ? SELECTED_STROKE : "rgba(255,255,255,0.55)")
        .attr("stroke-width", d => activeHighlightSet?.has(String(d.ID)) ? 1.6 : 0.75);

      if (activeHighlightSet) {
        circles.filter(d => activeHighlightSet.has(String(d.ID))).raise();
      }
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
      .attr("fill", circleFill)
      .attr("opacity", 0.92)
      .attr("stroke", "rgba(255,255,255,0.55)")
      .attr("stroke-width", 0.75);

    circlesRef.current = circles;

    // Re-apply any active selection immediately after (re)drawing so the selected
    // dot persists across zoom in/out and resize, not just on selection change.
    applyCircleEmphasis(highlightSetRef.current);

    // ── Brush for drag-to-select-multiple-points ───────────────────────────
    const brushGroup = canvas.append("g").attr("class", "scatter-brush");

    let lastBrushEnd = 0;
    let clickTimer = null;
    const clickDelayMs = 320;

    const brush = d3.brush()
      .extent([[0, 0], [size, size]])
      .on("brush end", (event) => {
        if (event.type === "end") lastBrushEnd = Date.now();
        if (!event.selection) {
          applyCircleEmphasis();
          if (event.type === "end" && event.sourceEvent) {
            clearHighlight("scatterplot_brush_empty", { source: "scatterplot", cols: [attrX, attrY] });
          }
          return;
        }
        const [[x0, y0], [x1, y1]] = event.selection;
        const brushedIds = [];
        const requestRevision = highlightRevisionRef.current;
        const appendToSelection = event.sourceEvent?.shiftKey === true;
        circles.each(function (d) {
          const cx = +d3.select(this).attr("cx");
          const cy = +d3.select(this).attr("cy");
          const inside = cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1;
          if (inside) brushedIds.push(d.ID);
        });
        const currentCols = highlightedColsRef.current || [];
        const currentIds = (
          currentCols.includes(attrX) && currentCols.includes(attrY)
            ? highlightedRowIdsRef.current || []
            : []
        );
        const nextIds = appendToSelection
          ? [...new Set([...currentIds, ...brushedIds])]
          : [...new Set(brushedIds)];
        const brushedIdSet = new Set(nextIds.map(String));
        applyCircleEmphasis(brushedIdSet);

        if (event.type === "end") {
          if (highlightRevisionRef.current !== requestRevision) return;
          if (nextIds.length > 0) {
            setHighlightedRef.current(nextIds, [attrX, attrY], "scatterplot", {
              action: appendToSelection ? "shift_brush" : "brush",
              brushedRowIds: brushedIds,
              brushedCount: brushedIds.length,
            });
          } else if (!appendToSelection) {
            clearHighlight("scatterplot_brush_empty", { source: "scatterplot", cols: [attrX, attrY] });
          }
        }
      });

    brushGroup.call(brush);
    brushGroup.selectAll(".overlay").attr("cursor", "crosshair");
    brushGroup.selectAll(".selection")
      .attr("fill", SELECTED_FILL)
      .attr("fill-opacity", 0.16)
      .attr("stroke", SELECTED_STROKE)
      .attr("stroke-width", 1)
      .attr("stroke-dasharray", "4 3");
    brushGroup.lower();

    clearSelectionRef.current = () => {
      applyCircleEmphasis();
      brushGroup.call(brush.move, null);
    };

    createTooltip(circles,
      d => {
        const bin = String(d.x) + " x " + String(d.y);
        const rowId = isFocused ? `<br><strong>ID:</strong> ${d.ID}` : "";
        let errorList = "";
        if (d.errors && d.errors.length >= 1) errorList = "<br><strong>Errors: </strong>" + d.errors[0];
        if (d.errors && d.errors.length > 1) d.errors.slice(1).forEach(k => { errorList += `, ${k}`; });
        return `<strong>Data:</strong> ${bin}${rowId}${errorList}`;
      },
      (d, event) => {
        // Skip click if a brush drag just ended (prevents overwriting multi-select).
        if (Date.now() - lastBrushEnd < 300) return;
        if (clickTimer) window.clearTimeout(clickTimer);

        clickTimer = window.setTimeout(() => {
          // Left click: set this point's ID as the cross-chart highlight.
          setHighlightedRef.current([d.ID], [attrX, attrY], "scatterplot", {
            action: "click",
            clickedRowId: d.ID,
          });
          clickTimer = null;
        }, clickDelayMs);
      },
      (d) => { /* right click – unused */ },
      (d) => { /* double click – unused */ },
      { showTooltip: isFocused, hoverOpacity: isFocused ? 0.65 : null }
    );

    circles.on("dblclick", function(event, d) {
      event.preventDefault();
      event.stopPropagation();
      if (clickTimer) {
        window.clearTimeout(clickTimer);
        clickTimer = null;
      }
      if (Date.now() - lastBrushEnd < 300) return;

      const currentCols = highlightedColsRef.current || [];
      const currentIds = (
        currentCols.includes(attrX) && currentCols.includes(attrY)
          ? highlightedRowIdsRef.current || []
          : []
      );
      const clickedId = d.ID;
      const clickedKey = String(clickedId);
      const hasClicked = currentIds.some(id => String(id) === clickedKey);
      const nextIds = hasClicked
        ? currentIds.filter(id => String(id) !== clickedKey)
        : [...currentIds, clickedId];

      if (nextIds.length > 0) {
        setHighlightedRef.current(nextIds, [attrX, attrY], "scatterplot", {
          action: hasClicked ? "double_click_remove" : "double_click_add",
          clickedRowId: clickedId,
        });
      } else {
        clearHighlight("scatterplot_double_click_removed_last", {
          source: "scatterplot",
          cols: [attrX, attrY],
          clickedRowId: clickedId,
        });
      }
    });

    return () => {
      if (clickTimer) window.clearTimeout(clickTimer);
      canvas.selectAll("*").remove();
    };
  }, [size, sampleData, detailMode]);

  // ── react to cross-chart highlight changes ────────────────────────────────
  useEffect(() => {
    if (!circlesRef.current) return;
    const rowIdSet = shouldHighlightSelection ? new Set(highlightedRowIds.map(String)) : null;
    const colorScale = colorScaleRef.current;
    const baseFill = d => {
      if (!d.errors || d.errors.length === 0) return colorScale("none");
      if (d.errors.length === 1) return colorScale(d.errors[0]);
      return colorScale(d.errors[0]);
    };

    circlesRef.current
      .attr("fill", d => rowIdSet?.has(String(d.ID)) ? SELECTED_FILL : baseFill(d))
      .attr("opacity", d => !rowIdSet ? 0.92 : rowIdSet.has(String(d.ID)) ? 1 : 0.18)
      .attr("r", d => rowIdSet?.has(String(d.ID)) ? 5 : 4)
      .attr("stroke", d => rowIdSet?.has(String(d.ID)) ? SELECTED_STROKE : "rgba(255,255,255,0.55)")
      .attr("stroke-width", d => rowIdSet?.has(String(d.ID)) ? 1.6 : 0.75);

    if (rowIdSet) {
      circlesRef.current.filter(d => rowIdSet.has(String(d.ID))).raise();
    }
  }, [highlightedRowIds, highlightedCols, shouldHighlightSelection, attrX, attrY, sampleData]);

  function handleBackgroundClick() {
    clearSelectionRef.current();
    clearHighlight("scatterplot_background_click", { source: "scatterplot", cols: [attrX, attrY] });
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
