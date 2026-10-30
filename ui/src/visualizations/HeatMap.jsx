// HeatMap.jsx
import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram2d, queryHistogram2dRange, queryRowsInBin, queryBinsForRows } from "../utils/serverCalls.jsx";
import { createBinnedScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import {
  BRUSH_CLICK_GUARD_MS, HIGHLIGHT_FILL, plainColorScale, tileColor, useCachedPlotData, useLatestRef,
} from "./errorPlots.js";

// Module-level cache so base histogram data survives component unmount/remount (e.g. focus zoom in/out).
import { heatMapCache } from "../store/visualizationCaches.jsx";

function Heatmap({
  xPos,
  yPos,
  size,
  attrX,
  attrY,
  errorColors
}) {
  const { tableName } = useTableName();
  const drawingRef = useRef(null);
  const clearSelectionRef = useRef(() => {});

  // Refs to D3 elements so the highlight effect can re-color without rebuild.
  const tilesRef = useRef(null);
  const colorScaleRef = useRef(plainColorScale);

  const { highlightedRowIds, setHighlightedRowIds, clearHighlight, highlightRevision } = useSelection();
  const setHighlightedRef = useLatestRef(setHighlightedRowIds);
  const highlightRevisionRef = useLatestRef(highlightRevision);

  // ── data fetch ─────────────────────────────────────────────────────────
  const histogramData = useCachedPlotData(
    heatMapCache,
    `${tableName}|${attrX}|${attrY}`,
    async ({ useRange, minId, maxId }) => {
      const response = useRange
        ? await queryHistogram2dRange(tableName, attrX, attrY, 10, minId, maxId)
        : await queryHistogram2d(tableName, attrX, attrY, 10);

      if (!response || !response.success) {
        console.error("[HEATMAP] API call failed:", response);
        throw new Error(`2D Histogram API failed: ${response?.error || "Unknown error"}`);
      }
      return response.histogram;
    },
    [tableName, attrX, attrY],
  );

  // ── draw chart ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!histogramData) return;

    const numHistDataX = histogramData.scaleX.numeric || [];
    const catHistDataX = histogramData.scaleX.categorical || [];
    const numHistDataY = histogramData.scaleY.numeric || [];
    const catHistDataY = histogramData.scaleY.categorical || [];

    const xScale = createBinnedScales(size, numHistDataX, catHistDataX, "horizontal");
    const yScale = createBinnedScales(size, numHistDataY, catHistDataY, "vertical");

    const drawingGroup = d3.select(drawingRef.current);
    drawingGroup.selectAll("*").remove();

    xScale.draw(drawingGroup);
    yScale.draw(drawingGroup);

    const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);
    const colorScale = errorColors || plainColorScale;
    colorScaleRef.current = colorScale;

    const tileFill = (d) => tileColor(colorScale, d);

    const tiles = drawingGroup.append("g")
      .attr("class", "heatmap-tiles")
      .selectAll("rect")
      .data(binsToRender)
      .join("rect")
      .attr("x", d => xScale.apply(d.xType === "numeric" ? xScale.numHistData[d.xBin].x0 : d.xBin, d.xType))
      .attr("y", d => yScale.apply(d.yType === "numeric" ? yScale.numHistData[d.yBin].x1 : d.yBin, d.yType))
      .attr("height", d => d.yType === "numeric"
        ? yScale.numericalBandwidth(yScale.numHistData[d.yBin].x1, yScale.numHistData[d.yBin].x0)
        : yScale.categoricalBandwidth())
      .attr("width", d => d.xType === "numeric"
        ? xScale.numericalBandwidth(xScale.numHistData[d.xBin].x0, xScale.numHistData[d.xBin].x1)
        : xScale.categoricalBandwidth())
      .attr("fill", tileFill)
      .attr("stroke", "white")
      .attr("cursor", "pointer")
      .attr("stroke-width", 1)
      // For the end-to-end tests: which tile this is, and how many rows it holds
      .attr("data-x-bin", d => String(d.xBin))
      .attr("data-y-bin", d => String(d.yBin))
      .attr("data-count", d => d.count.items);

    tilesRef.current = tiles;

    // ── Brush for drag-to-select-multiple-tiles ────────────────────────────
    const brushGroup = drawingGroup.append("g").attr("class", "heatmap-brush");

    // Pre-compute tile positions from data+scales (more reliable than reading DOM attrs).
    const tilePositions = new Map();
    binsToRender.forEach(d => {
      const key = `${d.xBin}|${d.yBin}`;
      let tx, tw, ty, th;
      if (d.xType === "numeric") {
        tx = xScale.apply(xScale.numHistData[d.xBin].x0, "numeric");
        tw = xScale.numericalBandwidth(xScale.numHistData[d.xBin].x0, xScale.numHistData[d.xBin].x1);
      } else {
        tx = xScale.apply(d.xBin, "categorical");
        tw = xScale.categoricalBandwidth();
      }
      if (d.yType === "numeric") {
        ty = yScale.apply(yScale.numHistData[d.yBin].x1, "numeric");
        th = yScale.numericalBandwidth(yScale.numHistData[d.yBin].x1, yScale.numHistData[d.yBin].x0);
      } else {
        ty = yScale.apply(d.yBin, "categorical");
        th = yScale.categoricalBandwidth();
      }
      tilePositions.set(key, { tx, ty, tw, th });
    });

    let lastBrushEnd = 0;

    const brush = d3.brush()
      .extent([[0, 0], [size, size]])
      .on("brush end", (event) => {
        if (event.type === "end") lastBrushEnd = Date.now();
        if (!event.selection) {
          tiles.attr("fill", tileFill);
          if (event.type === "end" && event.sourceEvent) {
            clearHighlight();
          }
          return;
        }
        const [[bx0, by0], [bx1, by1]] = event.selection;
        const brushedBins = [];
        tiles.each(function (d) {
          const pos = tilePositions.get(`${d.xBin}|${d.yBin}`);
          if (!pos) return;
          const { tx, ty, tw, th } = pos;
          const overlaps = tx < bx1 && tx + tw > bx0 && ty < by1 && ty + th > by0;
          d3.select(this).attr("fill", overlaps ? HIGHLIGHT_FILL : tileFill(d));
          if (overlaps) brushedBins.push(d);
        });

        if (event.type === "end" && brushedBins.length > 0) {
          const requestRevision = highlightRevisionRef.current;
          Promise.all(brushedBins.map(d =>
            queryRowsInBin({
              type: "2d",
              column_x: attrX,
              column_y: attrY,
              x_bin: d.xBin,
              y_bin: d.yBin,
            })
          )).then(results => {
            if (highlightRevisionRef.current !== requestRevision) return;
            const allIds = [];
            results.forEach(r => { if (r?.success) allIds.push(...r.row_ids); });
            setHighlightedRef.current([...new Set(allIds)], [attrX, attrY], "heatmap");
          });
        }
      });

    brushGroup.call(brush);
    brushGroup.lower();

    clearSelectionRef.current = () => {
      tiles.attr("fill", tileFill);
      brushGroup.call(brush.move, null);
    };

    createTooltip(
      tiles,
      d => {
        const xBin = d.xType === "numeric"
          ? `${Math.round(numHistDataX[d.xBin].x0)}-${Math.round(numHistDataX[d.xBin].x1)}`
          : d.xBin;
        const yBin = d.yType === "numeric"
          ? `${Math.round(numHistDataY[d.yBin].x0)}-${Math.round(numHistDataY[d.yBin].x1)}`
          : d.yBin;
        let errorList = "";
        Object.keys(d.count).forEach(key => {
          if (key === "items") return;
          errorList += `<br> - ${key}: ${d.count[key]}`;
        });
        if (errorList !== "") errorList = "<br><strong>Errors: </strong> " + errorList;
        return `<strong>Bin:</strong> ${xBin} x ${yBin}<br><strong>Items: </strong>${d.count.items}${errorList}`;
      },
      (d) => {
        // Skip click if a brush drag just ended (prevents overwriting multi-select).
        if (Date.now() - lastBrushEnd < BRUSH_CLICK_GUARD_MS) return;
        // Left click: fetch row IDs for this tile then update context.
        const requestRevision = highlightRevisionRef.current;
        queryRowsInBin({
          type: "2d",
          column_x: attrX,
          column_y: attrY,
          x_bin: d.xBin,
          y_bin: d.yBin,
        }).then(result => {
          if (highlightRevisionRef.current !== requestRevision) return;
          if (result?.success) {
            setHighlightedRef.current(result.row_ids, [attrX, attrY], "heatmap");
          }
        });
      },
    );

    return () => { drawingGroup.selectAll("*").remove(); };
  }, [size, histogramData]);

  // ── react to cross-chart highlight changes ──────────────────────────────
  useEffect(() => {
    if (!tilesRef.current) return;
    const colorScale = colorScaleRef.current;

    if (!highlightedRowIds || highlightedRowIds.length === 0) {
      clearSelectionRef.current();
      return;
    }

    let isActive = true;

    queryBinsForRows({
      type: "2d",
      column_x: attrX,
      column_y: attrY,
      row_ids: highlightedRowIds,
    }).then(result => {
      if (!isActive || !result?.success || !tilesRef.current) return;
      // Build a Set of "xBin|yBin" keys for O(1) lookup.
      const highlightSet = new Set(result.bins.map(b => `${b.xBin}|${b.yBin}`));
      tilesRef.current.attr("fill", d =>
        highlightSet.has(`${d.xBin}|${d.yBin}`) ? HIGHLIGHT_FILL : tileColor(colorScale, d)
      );
    });

    return () => {
      isActive = false;
    };
  }, [highlightedRowIds, attrX, attrY, highlightRevision, histogramData]);

  function handleBackgroundClick() {
    clearSelectionRef.current();
    clearHighlight();
  }

  return (
    <g transform={`translate(${xPos}, ${yPos})`} className="heatmap-canvas" data-testid="heatmap"
       data-x-column={attrX} data-y-column={attrY}>
      <rect width={size} height={size} fill="#ffffff00" onClick={handleBackgroundClick} />
      <g ref={drawingRef}></g>
    </g>
  );
}

// Adds memoization (shallow compare) - may need to make a custom checker.
export default React.memo(Heatmap);
