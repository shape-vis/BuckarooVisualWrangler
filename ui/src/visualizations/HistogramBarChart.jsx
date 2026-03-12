// HistogramBarChart.jsx
import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram1d } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../utils/SelectionContext.jsx";

export default function HistogramBarChart({
    cellID,
    pos,
    size,
    table_name,
    attrX,
    errorColors,
}) {
    const drawingRef = useRef(null);
    const clearSelectionRef = useRef(() => {});
    const barsRef = useRef(null);

    const [histogramData, setHistogramData] = React.useState(null);

    const { selection, filterVersion, addFilter, clearFilters } = useSelection();

    // Re-fetch when filter changes
    useEffect(() => {
        async function fetchData() {
            try {
                const response = await queryHistogram1d(table_name, attrX, 10);
                if (!response || !response.Success) {
                    throw new Error(`API failed: ${response?.Error || "Unknown error"}`);
                }
                setHistogramData(response.histogram);
            } catch (err) {
                console.error("[HistogramBarChart]", err?.message || err);
            }
        }
        fetchData();
    }, [table_name, attrX, filterVersion]);

    // Re-color bars on cross-plot selection change (no re-fetch needed)
    useEffect(() => {
        if (!barsRef.current) return;
        const colorScale = errorColors || (k => "steelblue");
        const currentSelection = selection;
        barsRef.current.attr("fill", d => isBarHighlighted(d, currentSelection, attrX) ? "gold" : colorScale(d.name));
    }, [selection]);

    useEffect(() => {
        if (!histogramData) return;

        const canvas = d3.select(drawingRef.current);
        canvas.selectAll("*").remove();

        const numHistDataX = histogramData.scaleX.numeric || [];
        const catHistDataX = histogramData.scaleX.categorical || [];

        const numDomainY = numHistDataX.length === 0 ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
        const catDomainY = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);

        const xScale = createHybridScales(size.w, numHistDataX, catHistDataX, numDomainY, catDomainY, "horizontal");

        const yScale = d3.scaleLinear()
            .domain([0, d3.max(histogramData.histograms, d => d.count.items)]).nice()
            .range([size.h, 0]);

        const colorScale = errorColors || (k => "steelblue");

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

        let localSelected = [];
        const barColor = d => localSelected.includes(d) ? "gold" : colorScale(d.name);

        const brushGroup = canvas.append("g").attr("class", "histogram-brush");

        const bars = canvas.append("g")
            .selectAll("rect")
            .data(myData)
            .join("rect")
            .attr("x", d => xScale.apply(d.type === "numeric" ? numHistDataX[d.bin].x0 : d.bin, d.type))
            .attr("y", d => yScale(d.top))
            .attr("height", d => Math.max(0, yScale(d.bottom) - yScale(d.top)))
            .attr("width", d => d.type === "numeric"
                ? xScale.numericalBandwidth(numHistDataX[d.bin].x0, numHistDataX[d.bin].x1)
                : xScale.categoricalBandwidth())
            .attr("fill", barColor)
            .attr("stroke", "white")
            .attr("cursor", "pointer")
            .attr("stroke-width", 2);

        barsRef.current = bars;

        function pushFilter(currentSelected) {
            addFilter({
                table: table_name,
                viewType: "barchart",
                cols: [attrX],
                data: currentSelected,
                scaleX: histogramData.scaleX,
                scaleY: null,
            });
        }

        const brush = d3.brushX()
            .extent([[0, 0], [size.w, size.h]])
            .on("brush end", (event) => {
                if (!event.selection) {
                    localSelected = [];
                    bars.attr("fill", barColor);
                    return;
                }
                const [x0, x1] = event.selection;
                const brushedItems = myData.filter(d => {
                    if (d.type === "numeric") {
                        const bin = numHistDataX[d.bin];
                        if (!bin) return false;
                        const start = xScale.apply(bin.x0, "numeric");
                        const end = xScale.apply(bin.x1, "numeric");
                        return end >= x0 && start <= x1;
                    }
                    const start = xScale.apply(d.bin, "categorical");
                    const end = start + xScale.categoricalBandwidth();
                    return end >= x0 && start <= x1;
                });

                if (event.sourceEvent && event.sourceEvent.shiftKey) {
                    brushedItems.forEach(d => { if (!localSelected.includes(d)) localSelected.push(d); });
                } else {
                    localSelected = brushedItems;
                }
                bars.attr("fill", barColor);
                // Only push filter on "end" to avoid hammering the backend while dragging
                if (event.type === "end" && localSelected.length > 0) {
                    pushFilter(localSelected);
                }
            });

        brushGroup.call(brush);
        brushGroup.lower();

        clearSelectionRef.current = () => {
            localSelected = [];
            bars.attr("fill", barColor);
            brushGroup.call(brush.move, null);
            clearFilters();
        };

        if (xScale && typeof xScale.draw === "function") xScale.draw(canvas);
        canvas.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

        createTooltip(bars,
            d => {
                const bin = d.type === "numeric"
                    ? `${Math.round(numHistDataX[d.bin].x0)}-${Math.round(numHistDataX[d.bin].x1)}`
                    : d.bin;
                return `<strong>Bin: </strong>${bin}<br><strong>Items: </strong>${d.value}<br><strong>Errors: </strong>${d.name}`;
            },
            (d, event) => {
                if (event.shiftKey) {
                    if (localSelected.includes(d)) localSelected = localSelected.filter(item => item !== d);
                    else localSelected.push(d);
                } else {
                    localSelected = [d];
                }
                bars.attr("fill", barColor);
                pushFilter(localSelected);
            },
            (d) => { console.log("[HistogramBarChart] Right click", d); },
            (d) => { console.log("[HistogramBarChart] Double click", d); }
        );

        return () => { canvas.selectAll("*").remove(); };
    }, [size, histogramData]);

    function handleDeselect(e) {
        e.preventDefault();
        clearSelectionRef.current();
    }

    return (
        <g key={cellID} transform={`translate(${pos.x}, ${pos.y})`} className="barchart-canvas">
            <rect width={size.w} height={size.h} fill="#ffffff00" onContextMenu={handleDeselect} />
            <g ref={drawingRef}></g>
        </g>
    );
}

// ── cross-plot highlight helpers ─────────────────────────────────────────────
function isBarHighlighted(barDatum, selection, attrX) {
    if (!selection) return false;

    if (selection.viewType === "barchart") {
        if (selection.cols[0] !== attrX) return false;
        return selection.data.some(sel => sel.bin === barDatum.bin && sel.type === barDatum.type);
    }

    if (selection.viewType === "heatmap") {
        const xCol = selection.cols[0], yCol = selection.cols[1];
        if (xCol === attrX)
            return selection.data.some(sel => sel.xBin === barDatum.bin && sel.xType === barDatum.type);
        if (yCol === attrX)
            return selection.data.some(sel => sel.yBin === barDatum.bin && sel.yType === barDatum.type);
        return false;
    }

    if (selection.viewType === "scatterplot") {
        const xCol = selection.cols[0], yCol = selection.cols[1];
        if (xCol === attrX)
            return selection.data.some(point => _valueInBin(point.x, barDatum.bin, barDatum.type, selection.scaleX));
        if (yCol === attrX)
            return selection.data.some(point => _valueInBin(point.y, barDatum.bin, barDatum.type, selection.scaleY));
        return false;
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
