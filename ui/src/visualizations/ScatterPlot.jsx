// ScatterPlot.jsx
import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { querySample2d } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../utils/SelectionContext.jsx";

export default function ScatterPlot({
  cellID,
  xPos,
  yPos,
  size,
  table_name,
  attrX,
  attrY,
  errorColors,
  errorSampleCount = 300,
  totalSampleCount = 1000,
}) {
  const drawingRef = useRef(null);
  const dragLayerRef = useRef(null);
  const [sampleData, setSampleData] = React.useState(null);

  const { selection, filterVersion, addFilter, clearFilters } = useSelection();

  const circlesRef = useRef(null);
  const selectedRef = useRef([]);

  // Re-fetch when filter changes
  useEffect(() => {
    async function fetchData() {
      try {
        const response = await querySample2d(table_name, attrX, attrY, errorSampleCount, totalSampleCount);
        if (!response || !response.Success) {
          throw new Error(`2D ScatterPlot API failed: ${response?.Error || "Unknown error"}`);
        }
        if (!response.scatterplot_data) {
          throw new Error("No scatterplot data returned from server");
        }
        setSampleData(response.scatterplot_data);
      } catch (err) {
        console.error("[SCATTERPLOT]", err?.message || err);
      }
    }
    fetchData();
  }, [table_name, attrX, attrY, errorSampleCount, totalSampleCount, filterVersion]);

  // Re-color circles on cross-plot selection change (no re-fetch needed)
  useEffect(() => {
    if (!circlesRef.current || !sampleData) return;
    const colorScale = errorColors || (() => "steelblue");
    const currentSelection = selection;
    circlesRef.current.attr("fill", d => {
      if (isPointHighlighted(d, currentSelection, attrX, attrY)) return "gold";
      if (!d.errors || d.errors.length === 0) return colorScale("none");
      return colorScale(d.errors[0]);
    });
  }, [selection]);

  useEffect(() => {
    if (!sampleData) return;

    const canvas = d3.select(drawingRef.current);
    canvas.selectAll("*").remove();

    const colorScale = errorColors || (() => "steelblue");

    const numHistDataX = sampleData.scaleX.numeric || [];
    const catHistDataX = sampleData.scaleX.categorical || [];
    const numHistDataY = sampleData.scaleY.numeric || [];
    const catHistDataY = sampleData.scaleY.categorical || [];

    const xScale = createHybridScales(
      size, numHistDataX, catHistDataX,
      numHistDataX.length === 0 ? null : numHistDataX,
      catHistDataX.length === 0 ? null : catHistDataX.map(d => d),
      "horizontal"
    );
    const yScale = createHybridScales(
      size, numHistDataY, catHistDataY,
      numHistDataY.length === 0 ? null : numHistDataY,
      catHistDataY.length === 0 ? null : catHistDataY.map(d => d),
      "vertical"
    );

    xScale.draw(canvas);
    yScale.draw(canvas);

    const circleFill = d => {
      if (selectedRef.current.includes(d)) return "gold";
      if (!d.errors || d.errors.length === 0) return colorScale("none");
      return colorScale(d.errors[0]);
    };

    function pushFilter(currentSelected) {
      addFilter({
        table: table_name,
        viewType: "scatterplot",
        cols: [attrX, attrY],
        data: currentSelected,
        scaleX: sampleData.scaleX,
        scaleY: sampleData.scaleY,
      });
    }

    const circles = canvas.selectAll("circle")
      .data(sampleData.data || [])
      .join("circle")
      .attr("cx", d => xScale ? xScale.apply(d.x, d.xType, true) : 0)
      .attr("cy", d => yScale ? yScale.apply(d.y, d.yType, true) : 0)
      .attr("r", 4)
      .attr("fill", circleFill)
      .attr("cursor", "pointer");

    circlesRef.current = circles;

    // Drag-to-select — lives on dragLayerRef so canvas.selectAll("*").remove() never kills it
    let dragStart = null;
    let selectionRect = null;
    const dragLayer = d3.select(dragLayerRef.current);
    dragLayer.selectAll(".scatter-drag-bg").remove();

    dragLayer.append("rect")
      .attr("class", "scatter-drag-bg")
      .attr("width", size)
      .attr("height", size)
      .attr("fill", "transparent")
      .call(
        d3.drag()
          .on("start", function (event) {
            dragStart = { x: event.x, y: event.y };
            dragLayer.select(".selection-box").remove();
            selectionRect = dragLayer.append("rect")
              .attr("class", "selection-box")
              .attr("x", dragStart.x).attr("y", dragStart.y)
              .attr("width", 0).attr("height", 0)
              .attr("fill", "rgba(100,150,255,0.15)")
              .attr("stroke", "#6699ff")
              .attr("stroke-width", 1)
              .attr("stroke-dasharray", "4,2")
              .attr("pointer-events", "none");
          })
          .on("drag", function (event) {
            if (!dragStart || !selectionRect) return;
            const x = Math.min(event.x, dragStart.x);
            const y = Math.min(event.y, dragStart.y);
            const w = Math.abs(event.x - dragStart.x);
            const h = Math.abs(event.y - dragStart.y);
            selectionRect.attr("x", x).attr("y", y).attr("width", w).attr("height", h);
            const x0 = x, x1 = x + w, y0 = y, y1 = y + h;
            selectedRef.current = (sampleData.data || []).filter(d => {
              const cx = xScale ? xScale.apply(d.x, d.xType, true) : 0;
              const cy = yScale ? yScale.apply(d.y, d.yType, true) : 0;
              return cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1;
            });
            circles.attr("fill", circleFill);
          })
          .on("end", function () {
            dragLayer.select(".selection-box").remove();
            dragStart = null;
            selectionRect = null;
            if (selectedRef.current.length > 0) {
              pushFilter(selectedRef.current);
            }
          })
      );

    createTooltip(
      circles,
      d => {
        const bin = `${String(d.x)} x ${String(d.y)}`;
        let errorList = "";
        if (d.errors && d.errors.length >= 1) errorList = "<br><strong>Errors: </strong>" + d.errors[0];
        if (d.errors && d.errors.length > 1) d.errors.slice(1).forEach(key => { errorList += `, ${key}`; });
        return `<strong>Data:</strong> ${bin}${errorList}`;
      },
      (d, event) => {
        if (event.shiftKey) {
          if (selectedRef.current.includes(d)) {
            selectedRef.current = selectedRef.current.filter(item => item !== d);
          } else {
            selectedRef.current = [...selectedRef.current, d];
          }
        } else {
          selectedRef.current = [d];
        }
        circles.attr("fill", circleFill);
        pushFilter(selectedRef.current);
      },
      (d) => { console.log("[SCATTERPLOT] Right click", d); },
      (d) => { console.log("[SCATTERPLOT] Double click", d); }
    );

    return () => { canvas.selectAll("*").remove(); };
  }, [size, sampleData]);

  function handleDeselect(e) {
    e.preventDefault();
    selectedRef.current = [];
    if (circlesRef.current) {
      const colorScale = errorColors || (() => "steelblue");
      circlesRef.current.attr("fill", d => {
        if (!d.errors || d.errors.length === 0) return colorScale("none");
        return colorScale(d.errors[0]);
      });
    }
    clearFilters();
  }

  return (
    <g key={cellID} transform={`translate(${xPos}, ${yPos})`} className="scatter-canvas">
      <rect width={size} height={size} fill="#ffffff00" onContextMenu={handleDeselect} />
      <g ref={dragLayerRef} />
      <g ref={drawingRef}></g>
    </g>
  );
}

// ── cross-plot highlight helpers ─────────────────────────────────────────────
function isPointHighlighted(point, selection, attrX, attrY) {
  if (!selection) return false;

  if (selection.viewType === "scatterplot") {
    if (selection.cols[0] !== attrX || selection.cols[1] !== attrY) return false;
    return selection.data.some(d => d.ID === point.ID);
  }

  if (selection.viewType === "barchart") {
    const srcCol = selection.cols[0];
    if (srcCol === attrX)
      return selection.data.some(sel => _valueInBin(point.x, sel.bin, sel.type, selection.scaleX));
    if (srcCol === attrY)
      return selection.data.some(sel => _valueInBin(point.y, sel.bin, sel.type, selection.scaleX));
    return false;
  }

  if (selection.viewType === "heatmap") {
    const heatXCol = selection.cols[0], heatYCol = selection.cols[1];
    return selection.data.some(sel => {
      // For each scatter axis, check if that axis maps to one of the heatmap axes.
      // If neither heatmap axis matches the scatter axis, that scatter axis is unconstrained (true).
      // But if NO heatmap axis matches either scatter axis at all, don't highlight anything.
      const scatterXMatchesHeatX = heatXCol === attrX;
      const scatterXMatchesHeatY = heatYCol === attrX;
      const scatterYMatchesHeatX = heatXCol === attrY;
      const scatterYMatchesHeatY = heatYCol === attrY;

      // If the heatmap shares no columns with this scatterplot, don't highlight
      if (!scatterXMatchesHeatX && !scatterXMatchesHeatY && !scatterYMatchesHeatX && !scatterYMatchesHeatY)
        return false;

      const matchX = scatterXMatchesHeatX
        ? _valueInBin(point.x, sel.xBin, sel.xType, selection.scaleX)
        : scatterXMatchesHeatY
          ? _valueInBin(point.x, sel.yBin, sel.yType, selection.scaleY)
          : true; // scatter X col not in heatmap — unconstrained

      const matchY = scatterYMatchesHeatX
        ? _valueInBin(point.y, sel.xBin, sel.xType, selection.scaleX)
        : scatterYMatchesHeatY
          ? _valueInBin(point.y, sel.yBin, sel.yType, selection.scaleY)
          : true; // scatter Y col not in heatmap — unconstrained

      return matchX && matchY;
    });
  }

  return false;
}

function _valueInBin(value, binIdx, binType, scale) {
  if (value == null) return false;
  if (binType === "numeric") {
    const bins = scale?.numeric;
    if (!bins || binIdx == null || parseInt(binIdx) >= bins.length) return false;
    const { x0, x1 } = bins[parseInt(binIdx)];
    return Number(value) >= x0 && Number(value) <= x1;
  }
  if (binType === "categorical") return String(value) === String(binIdx);
  return false;
}
