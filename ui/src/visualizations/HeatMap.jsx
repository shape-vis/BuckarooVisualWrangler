// HeatMap.jsx
import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram2d } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../utils/SelectionContext.jsx";

export default function Heatmap({
  cellID,
  xPos,
  yPos,
  size,
  table_name,
  attrX,
  attrY,
  errorColors,
}) {
  const drawingRef = useRef(null);
  const [histogramData, setHistogramData] = React.useState(null);

  const { selection, filterVersion, addFilter, clearFilters } = useSelection();

  const tilesRef = useRef(null);
  const localSelectedRef = useRef([]);

  // Re-fetch whenever the filter changes (filterVersion increments on every add/clear)
  useEffect(() => {
    async function fetchData() {
      try {
        const response = await queryHistogram2d(table_name, attrX, attrY, 10);
        if (!response || !response.Success) {
          throw new Error(`2D Histogram API failed: ${response?.Error || "Unknown error"}`);
        }
        setHistogramData(response.histogram);
      } catch (err) {
        console.error("[HEATMAP]", err?.message || err);
      }
    }
    fetchData();
  }, [table_name, attrX, attrY, filterVersion]); // <-- filterVersion triggers re-fetch

  // Re-color tiles when selection changes (cross-plot highlight)
  useEffect(() => {
    if (!tilesRef.current) return;
    // Capture selection in this effect's closure so tileFill reads the fresh value
    const currentSelection = selection;
    tilesRef.current.attr("fill", d => {
      if (isHighlightedWith(d, currentSelection)) return "gold";
      return defaultFill(d);
    });
  }, [selection]);

  const colorScale = errorColors || (() => "steelblue");

  function defaultFill(d) {
    const keys = Object.keys(d.count).filter(k => k !== "items");
    if (keys.length === 0) return colorScale("none");
    return colorScale(keys[0]);
  }

  // Accepts selection explicitly so it's never stale regardless of closure timing
  function isHighlightedWith(d, sel) {
    if (!sel) return false;

    if (sel.viewType === "heatmap") {
      // Same heatmap (same X and Y cols) — use local selection ref
      if (sel.cols?.[0] === attrX && sel.cols?.[1] === attrY)
        return localSelectedRef.current.includes(d);

      // Different heatmap — highlight tiles that share an axis with the selection
      const selXCol = sel.cols[0], selYCol = sel.cols[1];
      const heatSharesX = selXCol === attrX || selXCol === attrY;
      const heatSharesY = selYCol === attrX || selYCol === attrY;
      if (!heatSharesX && !heatSharesY) return false;

      return sel.data.some(s => {
        const matchAttrX = selXCol === attrX
          ? (s.xBin === d.xBin && s.xType === d.xType)
          : selYCol === attrX
            ? (s.yBin === d.xBin && s.yType === d.xType)
            : true;
        const matchAttrY = selXCol === attrY
          ? (s.xBin === d.yBin && s.xType === d.yType)
          : selYCol === attrY
            ? (s.yBin === d.yBin && s.yType === d.yType)
            : true;
        return matchAttrX && matchAttrY;
      });
    }

    if (sel.viewType === "barchart") {
      const srcCol = sel.cols[0];
      if (srcCol === attrX)
        return sel.data.some(s => s.bin === d.xBin && s.type === d.xType);
      if (srcCol === attrY)
        return sel.data.some(s => s.bin === d.yBin && s.type === d.yType);
      return false;
    }

    if (sel.viewType === "scatterplot" && histogramData) {
      const scatterXCol = sel.cols[0], scatterYCol = sel.cols[1];

      // If the scatterplot shares no columns with this heatmap, don't highlight
      const scatterXMatchesHeatX = scatterXCol === attrX;
      const scatterXMatchesHeatY = scatterXCol === attrY;
      const scatterYMatchesHeatX = scatterYCol === attrX;
      const scatterYMatchesHeatY = scatterYCol === attrY;
      if (!scatterXMatchesHeatX && !scatterXMatchesHeatY && !scatterYMatchesHeatX && !scatterYMatchesHeatY)
        return false;

      return sel.data.some(point => {
        // matchX: does this point's relevant value fall in this tile's X bin?
        const matchX = scatterXMatchesHeatX
          ? _valueInBin(point.x, d.xBin, d.xType, histogramData.scaleX)
          : scatterYMatchesHeatX
            ? _valueInBin(point.y, d.xBin, d.xType, histogramData.scaleX)
            : true; // no scatter col maps to this heatmap's X — unconstrained

        // matchY: does this point's relevant value fall in this tile's Y bin?
        const matchY = scatterXMatchesHeatY
          ? _valueInBin(point.x, d.yBin, d.yType, histogramData.scaleY)
          : scatterYMatchesHeatY
            ? _valueInBin(point.y, d.yBin, d.yType, histogramData.scaleY)
            : true; // no scatter col maps to this heatmap's Y — unconstrained

        return matchX && matchY;
      });
    }

    return false;
  }

  // Keep tileFill for the draw effect (passes selection at draw time)
  function tileFill(d, sel) {
    if (isHighlightedWith(d, sel)) return "gold";
    return defaultFill(d);
  }

  useEffect(() => {
    if (!histogramData) return;

    const numHistDataX = histogramData.scaleX.numeric || [];
    const catHistDataX = histogramData.scaleX.categorical || [];
    const numHistDataY = histogramData.scaleY.numeric || [];
    const catHistDataY = histogramData.scaleY.categorical || [];

    const numDomainX = numHistDataX.length === 0 ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
    const catDomainX = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);
    const numDomainY = numHistDataY.length === 0 ? null : [d3.min(numHistDataY, d => d.x0), d3.max(numHistDataY, d => d.x1)];
    const catDomainY = catHistDataY.length === 0 ? null : catHistDataY.map(d => d);

    const xScale = createHybridScales(size, numHistDataX, catHistDataX, numDomainX, catDomainX, "horizontal");
    const yScale = createHybridScales(size, numHistDataY, catHistDataY, numDomainY, catDomainY, "vertical");

    const drawingGroup = d3.select(drawingRef.current);
    drawingGroup.selectAll("*").remove();

    xScale.draw(drawingGroup);
    yScale.draw(drawingGroup);

    const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);

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
      .attr("fill", d => tileFill(d, selection))
      .attr("stroke", "white")
      .attr("cursor", "pointer")
      .attr("stroke-width", 1);

    tilesRef.current = tiles;

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
        if (errorList) errorList = "<br><strong>Errors: </strong>" + errorList;
        return `<strong>Bin:</strong> ${xBin} x ${yBin}<br><strong>Items: </strong>${d.count.items}${errorList}`;
      },
      (d, event) => {
        if (event.shiftKey) {
          if (localSelectedRef.current.includes(d)) {
            localSelectedRef.current = localSelectedRef.current.filter(item => item !== d);
          } else {
            localSelectedRef.current = [...localSelectedRef.current, d];
          }
        } else {
          localSelectedRef.current = [d];
        }
        tiles.attr("fill", d => tileFill(d, selection));

        addFilter({
          table: table_name,
          viewType: "heatmap",
          cols: [attrX, attrY],
          data: localSelectedRef.current,
          scaleX: histogramData.scaleX,
          scaleY: histogramData.scaleY,
        });
      },
      (d) => { console.log("[HEATMAP] Right click", d); },
      (d) => { console.log("[HEATMAP] Double click", d); }
    );

    return () => { drawingGroup.selectAll("*").remove(); };
  }, [size, histogramData]);

  function handleDeselect(e) {
    e.preventDefault();
    localSelectedRef.current = [];
    clearFilters();
  }

  return (
    <g key={cellID} transform={`translate(${xPos}, ${yPos})`} className="heatmap-canvas">
      <rect width={size} height={size} fill="#ffffff00" onContextMenu={handleDeselect} />
      <g ref={drawingRef}></g>
    </g>
  );
}

// ── internal helper ──────────────────────────────────────────────────────────
function _valueInBin(value, binIdx, binType, scale) {
  if (value == null) return false;
  if (binType === "numeric") {
    const bins = scale?.numeric;
    if (!bins || binIdx == null || parseInt(binIdx) >= bins.length) return false;
    const { x0, x1 } = bins[parseInt(binIdx)];
    const num = Number(value);
    return num >= x0 && num <= x1;
  }
  if (binType === "categorical") return String(value) === String(binIdx);
  return false;
}
