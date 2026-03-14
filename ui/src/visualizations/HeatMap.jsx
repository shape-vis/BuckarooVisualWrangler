// Heatmap.jsx
import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram2d, queryRowsInBin, queryBinsForRows } from "../utils/serverCalls.jsx";
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
  errorColors
}) {
  const drawingRef = useRef(null);
  const clearSelectionRef = useRef(() => {});
  const [histogramData, setHistogramData] = React.useState(null);

  // Refs to D3 elements so the highlight effect can re-color without rebuild.
  const tilesRef = useRef(null);
  const colorScaleRef = useRef(() => "steelblue");
  const numHistDataXRef = useRef([]);
  const numHistDataYRef = useRef([]);

  const { highlightedRowIds, setHighlightedRowIds, clearHighlight } = useSelection();
  const setHighlightedRef = useRef(setHighlightedRowIds);
  useEffect(() => { setHighlightedRef.current = setHighlightedRowIds; }, [setHighlightedRowIds]);

  // ── data fetch ─────────────────────────────────────────────────────────
  useEffect(() => {
    async function fetchData() {
      try {
        const response = await queryHistogram2d(table_name, attrX, attrY, 10);
        console.log("[HEATMAP] Response:", response);

        if (!response || !response.Success) {
          console.error("[HEATMAP] API call failed:", response);
          throw new Error(`2D Histogram API failed: ${response?.Error || "Unknown error"}`);
        }

        setHistogramData(response.histogram);
      } catch (err) {
        console.error(err?.message || err);
      }
    }
    fetchData();
  }, [table_name, attrX, attrY]);

  // ── draw chart ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!histogramData) return;

    const numHistDataX = histogramData.scaleX.numeric || [];
    const catHistDataX = histogramData.scaleX.categorical || [];
    const numHistDataY = histogramData.scaleY.numeric || [];
    const catHistDataY = histogramData.scaleY.categorical || [];

    numHistDataXRef.current = numHistDataX;
    numHistDataYRef.current = numHistDataY;

    const numDomainX = (numHistDataX.length === 0 || !numHistDataX[0]) ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
    const catDomainX = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);
    const numDomainY = (numHistDataY.length === 0 || !numHistDataY[0]) ? null : [d3.min(numHistDataY, d => d.x0), d3.max(numHistDataY, d => d.x1)];
    const catDomainY = catHistDataY.length === 0 ? null : catHistDataY.map(d => d);

    console.log("[HEATMAP] Domains:", { numDomainX, catDomainX, numDomainY, catDomainY });

    const xScale = createHybridScales(size, numHistDataX, catHistDataX, numDomainX, catDomainX, "horizontal");
    const yScale = createHybridScales(size, numHistDataY, catHistDataY, numDomainY, catDomainY, "vertical");

    const drawingGroup = d3.select(drawingRef.current);
    drawingGroup.selectAll("*").remove();

    xScale.draw(drawingGroup);
    yScale.draw(drawingGroup);

    const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);
    const colorScale = errorColors || (() => "steelblue");
    colorScaleRef.current = colorScale;

    const tileFill = (d) => {
      const keys = Object.keys(d.count).filter(k => k !== "items");
      if (keys.length === 0) return colorScale("none");
      if (keys.length === 1) return colorScale(keys[0]);
      return colorScale(keys[0]);
    };

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
      .attr("stroke-width", 1);

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
          return;
        }
        const [[bx0, by0], [bx1, by1]] = event.selection;
        const brushedBins = [];
        tiles.each(function (d) {
          const pos = tilePositions.get(`${d.xBin}|${d.yBin}`);
          if (!pos) return;
          const { tx, ty, tw, th } = pos;
          const overlaps = tx < bx1 && tx + tw > bx0 && ty < by1 && ty + th > by0;
          d3.select(this).attr("fill", overlaps ? "gold" : tileFill(d));
          if (overlaps) brushedBins.push(d);
        });

        if (event.type === "end" && brushedBins.length > 0) {
          Promise.all(brushedBins.map(d =>
            queryRowsInBin({
              type: "2d",
              column_x: attrX,
              column_y: attrY,
              x_bin: d.xBin,
              y_bin: d.yBin,
              x_bins: 10,
              y_bins: 10,
            })
          )).then(results => {
            const allIds = [];
            results.forEach(r => { if (r?.Success) allIds.push(...r.row_ids); });
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
      (d, _event) => {
        // Skip click if a brush drag just ended (prevents overwriting multi-select).
        if (Date.now() - lastBrushEnd < 300) return;
        // Left click: fetch row IDs for this tile then update context.
        queryRowsInBin({
          type: "2d",
          column_x: attrX,
          column_y: attrY,
          x_bin: d.xBin,
          y_bin: d.yBin,
          x_bins: 10,
          y_bins: 10,
        }).then(result => {
          if (result?.Success) {
            setHighlightedRef.current(result.row_ids, [attrX, attrY], "heatmap");
          }
        });
      },
      (d) => { console.log("Right click on heatmap bin", d); },
      (d) => { console.log("Double click on heatmap bin", d); }
    );

    return () => { drawingGroup.selectAll("*").remove(); };
  }, [size, histogramData]);

  // ── react to cross-chart highlight changes ──────────────────────────────
  useEffect(() => {
    if (!tilesRef.current) return;
    const colorScale = colorScaleRef.current;

    const tileFill = (d) => {
      const keys = Object.keys(d.count).filter(k => k !== "items");
      if (keys.length === 0) return colorScale("none");
      if (keys.length === 1) return colorScale(keys[0]);
      return colorScale(keys[0]);
    };

    if (!highlightedRowIds || highlightedRowIds.length === 0) {
      tilesRef.current.attr("fill", tileFill);
      return;
    }

    queryBinsForRows({
      type: "2d",
      column_x: attrX,
      column_y: attrY,
      row_ids: highlightedRowIds,
      x_bins: 10,
      y_bins: 10,
    }).then(result => {
      if (!result?.Success || !tilesRef.current) return;
      // Build a Set of "xBin|yBin" keys for O(1) lookup.
      const highlightSet = new Set(result.bins.map(b => `${b.xBin}|${b.yBin}`));
      tilesRef.current.attr("fill", d =>
        highlightSet.has(`${d.xBin}|${d.yBin}`) ? "gold" : tileFill(d)
      );
    });
  }, [highlightedRowIds, attrX, attrY]);

  function handleBackgroundClick() {
    clearSelectionRef.current();
    clearHighlight();
  }

  return (
    <g key={cellID} transform={`translate(${xPos}, ${yPos})`} className="heatmap-canvas">
      <rect width={size} height={size} fill="#ffffff00" onClick={handleBackgroundClick} />
      <g ref={drawingRef}></g>
    </g>
  );
}
