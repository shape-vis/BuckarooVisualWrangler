import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram1d, queryHistogram1dRange, queryRowsInBin, queryBinsForRows } from "../utils/serverCalls.jsx";
import { createBinnedScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";
import { HIGHLIGHT_FILL, plainColorScale, stackBars, useCachedPlotData, useLatestRef } from "./errorPlots.js";

// Module-level cache so base histogram data survives component unmount/remount (e.g. focus zoom in/out).
import { histogramCache } from "../store/visualizationCaches.jsx";

/**
 * HistogramBarChart renders a stacked histogram with optional brushing/selection.
 */
function HistogramBarChart({
    pos,
    size,
    attrX,
    errorColors,
}) {
    const { tableName } = useTableName();

    const drawingRef = useRef(null);
    const clearSelectionRef = useRef(() => {});

    // Refs to D3 elements / helpers so the highlight effect can re-color
    // without rebuilding the chart.
    const barsRef = useRef(null);
    const colorScaleRef = useRef(plainColorScale);

    const { highlightedRowIds, setHighlightedRowIds, clearHighlight, highlightRevision } = useSelection();
    const setHighlightedRef = useLatestRef(setHighlightedRowIds);
    const highlightRevisionRef = useLatestRef(highlightRevision);

    // ── data fetch ─────────────────────────────────────────────────────────
    const histogramData = useCachedPlotData(
        histogramCache,
        `${tableName}|${attrX}`,
        async ({ useRange, minId, maxId }) => {
            const response = useRange
                ? await queryHistogram1dRange(tableName, attrX, 10, minId, maxId)
                : await queryHistogram1d(tableName, attrX, 10);
            if (!response || !response.success) {
                throw new Error(`API failed: ${response?.error || "Unknown error"}`);
            }
            return response.histogram;
        },
        [tableName, attrX],
        "[HistogramBarChart] ",
    );

    // ── draw chart ──────────────────────────────────────────────────────────
    useEffect(() => {
        if (!histogramData) return;

        const canvas = d3.select(drawingRef.current);
        canvas.selectAll("*").remove();

        const numHistDataX = histogramData.scaleX.numeric || [];
        const catHistDataX = errorColors ? (histogramData.scaleX.categorical || []) : [];

        const xScale = createBinnedScales(size.w, numHistDataX, catHistDataX, "horizontal");

        const yScale = d3.scaleLinear()
            .domain([0, d3.max(histogramData.histograms, d => d.count.items)]).nice()
            .range([size.h, 0]);

        const colorScale = errorColors || plainColorScale;
        colorScaleRef.current = colorScale;

        // When no null columns, skip categorical bins entirely.
        let shownBins = histogramData.histograms;
        if (!errorColors) shownBins = shownBins.filter(d => d.xType !== "categorical");
        const segments = stackBars(shownBins);

        // Each bin's rows, for the end-to-end tests: a row flagged twice is in two segments, so they cannot sum to it
        const itemsByBin = new Map();
        shownBins.forEach((bin) => itemsByBin.set(String(bin.xBin), bin.count.items));

        const barColor = d => colorScale(d.name);

        const brushGroup = canvas.append("g").attr("class", "histogram-brush");

        const bars = canvas.append("g")
            .selectAll("rect")
            .data(segments)
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
            .attr("stroke-width", 2)
            // For the end-to-end tests: which bin and error type a segment is, and how many rows it holds
            .attr("data-bin", d => String(d.bin))
            .attr("data-bin-type", d => d.type)
            .attr("data-segment", d => d.name)
            .attr("data-count", d => d.value)
            .attr("data-bin-items", d => itemsByBin.get(String(d.bin)));

        barsRef.current = bars;

        // Brush for range selection.
        const brush = d3.brushX()
            .extent([[0, 0], [size.w, size.h]])
            .on("brush end", (event) => {
                if (!event.selection) {
                    bars.attr("fill", barColor);
                    if (event.type === "end" && event.sourceEvent) {
                        clearHighlight();
                    }
                    return;
                }
                const [x0, x1] = event.selection;
                const brushedBins = new Set();
                segments.forEach(d => {
                    let start, end;
                    if (d.type === "numeric") {
                        const bin = numHistDataX[d.bin];
                        if (!bin) return;
                        start = xScale.apply(bin.x0, "numeric");
                        end = xScale.apply(bin.x1, "numeric");
                    } else {
                        start = xScale.apply(d.bin, "categorical");
                        end = start + xScale.categoricalBandwidth();
                    }
                    if (end >= x0 && start <= x1) brushedBins.add(String(d.bin));
                });

                bars.attr("fill", d => brushedBins.has(String(d.bin)) ? HIGHLIGHT_FILL : barColor(d));

                // Async: fetch row IDs for all brushed bins and push to context.
                if (event.type === "end" && brushedBins.size > 0) {
                    const requestRevision = highlightRevisionRef.current;
                    const binsToQuery = [...brushedBins];
                    Promise.all(binsToQuery.map(b =>
                        queryRowsInBin({ type: "1d", column: attrX, bin: b})
                    )).then(results => {
                        if (highlightRevisionRef.current !== requestRevision) return;
                        const allIds = [];
                        results.forEach(r => { if (r?.success) allIds.push(...r.row_ids); });
                        setHighlightedRef.current([...new Set(allIds)], [attrX], "histogram");
                    });
                }
            });

        brushGroup.call(brush);
        brushGroup.lower();

        clearSelectionRef.current = () => {
            bars.attr("fill", barColor);
            brushGroup.call(brush.move, null);
        };

        xScale.draw(canvas);
        canvas.append("g").call(d3.axisLeft(yScale)).selectAll("text").attr("class", "left-axis-text");

        createTooltip(bars,
            d => {
                const bin = d.type === "numeric"
                    ? `${Math.round(numHistDataX[d.bin].x0)}-${Math.round(numHistDataX[d.bin].x1)}`
                    : d.bin;
                return `<strong>Bin: </strong>${bin}<br><strong>Items: </strong>${d.value}<br><strong>Errors: </strong>${d.name}`;
            },
            (d) => {
                // Left click: fetch row IDs for this bin then update context.
                const requestRevision = highlightRevisionRef.current;
                queryRowsInBin({ type: "1d", column: attrX, bin: d.bin})
                    .then(result => {
                        if (highlightRevisionRef.current !== requestRevision) return;
                        if (result?.success) {
                            setHighlightedRef.current(result.row_ids, [attrX], "histogram");
                        }
                    });
            },
        );

        return () => { canvas.selectAll("*").remove(); };
        // The panels pass size as a new object every render, so the chart is redrawn only when its numbers change
    }, [size.w, size.h, histogramData, errorColors]);

    // ── react to cross-chart highlight changes ──────────────────────────────
    useEffect(() => {
        if (!barsRef.current) return;
        const colorScale = colorScaleRef.current;

        if (!highlightedRowIds || highlightedRowIds.length === 0) {
            clearSelectionRef.current();
            return;
        }

        let isActive = true;

        queryBinsForRows({ type: "1d", column: attrX, row_ids: highlightedRowIds})
            .then(result => {
                if (!isActive || !result?.success || !barsRef.current) return;
                const highlightedBins = new Set(result.bins.map(String));
                barsRef.current.attr("fill", d =>
                    highlightedBins.has(String(d.bin)) ? HIGHLIGHT_FILL : colorScale(d.name)
                );
            });

        return () => {
            isActive = false;
        };
    }, [highlightedRowIds, attrX, highlightRevision, histogramData]);

    function clearSelection() {
        clearSelectionRef.current();
        clearHighlight();
    }

    return (
        <g transform={`translate(${pos.x}, ${pos.y})`} className="barchart-canvas" data-testid="histogram"
           data-column={attrX} data-height={size.h}>
            <rect width={size.w} height={size.h} fill="#ffffff00" onClick={clearSelection} />
            <g ref={drawingRef}></g>
        </g>
    );
}

// Adds memoization (shallow compare) - may need to make a custom checker.
export default React.memo(HistogramBarChart);
