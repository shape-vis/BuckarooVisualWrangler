import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram1d, queryHistogram1dRange, queryRowsInBin, queryBinsForRows } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { useRowRange } from "../store/RowRangeContext.jsx";
import { useTableName } from "../store/TableNameContext.jsx";

// Module-level cache so base histogram data survives component unmount/remount (e.g. focus zoom in/out).
import { histogramCache } from "../store/visualizationCaches.jsx";
const baseSampleCache = histogramCache;

/**
 * HistogramBarChart renders a stacked histogram with optional brushing/selection.
 */
function HistogramBarChart({
    cellID,
    pos,
    size,
    attrX,
    errorColors,
    detailMode = "focused",
}) {
    const { tableName: table_name } = useTableName();
    const isFocused = detailMode === "focused";

    const drawingRef = useRef(null);
    const clearSelectionRef = useRef(() => {});

    const [histogramData, setHistogramData] = React.useState(null);

    // Refs to D3 elements / helpers so the highlight effect can re-color
    // without rebuilding the chart.
    const barsRef = useRef(null);
    const colorScaleRef = useRef(k => "steelblue");
    const numHistDataXRef = useRef([]);

    const { highlightedRowIds, highlightedCols, setHighlightedRowIds, clearHighlight, highlightRevision } = useSelection();
    const shouldHighlightSelection = highlightedRowIds?.length > 0 && highlightedCols?.includes(attrX);
    const setHighlightedRef = useRef(setHighlightedRowIds);
    const highlightRevisionRef = useRef(highlightRevision);
    useEffect(() => { setHighlightedRef.current = setHighlightedRowIds; }, [setHighlightedRowIds]);
    useEffect(() => { highlightRevisionRef.current = highlightRevision; }, [highlightRevision]);

    const { useRange, minId, maxId } = useRowRange();

    // ── data fetch ─────────────────────────────────────────────────────────
    useEffect(() => {
        const cacheKey = `${table_name}|${attrX}`;

        async function fetchData() {
            // Restore cached base data instead of re-fetching (survives unmount/remount from focus zoom).
            if (!useRange && baseSampleCache.has(cacheKey)) {
                setHistogramData(baseSampleCache.get(cacheKey));
                return;
            }

            try {
                const response = useRange
                    ? await queryHistogram1dRange(table_name, attrX, 10, minId, maxId)
                    : await queryHistogram1d(table_name, attrX, 10);
                if (!response || !response.success) {
                    throw new Error(`API failed: ${response?.error || "Unknown error"}`);
                }
                setHistogramData(response.histogram);

                // Cache the base data so future mounts restore it without re-fetching.
                if (!useRange) {
                    baseSampleCache.set(cacheKey, response.histogram);
                }
            } catch (err) {
                console.error("[HistogramBarChart] " + (err?.message || err));
            }
        }
        fetchData();
    }, [table_name, attrX, useRange, minId, maxId]);

    // ── draw chart ──────────────────────────────────────────────────────────
    useEffect(() => {
        if (!histogramData) return;

        const canvas = d3.select(drawingRef.current);
        canvas.selectAll("*").remove();

        const numHistDataX = histogramData.scaleX.numeric || [];
        const catHistDataX = errorColors ? (histogramData.scaleX.categorical || []) : [];
        numHistDataXRef.current = numHistDataX;

        const numDomainY = (numHistDataX.length === 0 || !numHistDataX[0])
            ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
        const catDomainY = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);

        const xScale = createHybridScales(size.w, numHistDataX, catHistDataX, numDomainY, catDomainY, "horizontal");

        const yScale = d3.scaleLinear()
            .domain([0, d3.max(histogramData.histograms, d => d.count.items)]).nice()
            .range([size.h, 0]);

        const colorScale = errorColors || (k => "steelblue");
        colorScaleRef.current = colorScale;

        // Flatten stacked data per bin. When no null columns, skip categorical bins entirely.
        const myData = [];
        (errorColors ? histogramData.histograms : histogramData.histograms.filter(d => d.xType !== "categorical")).forEach(d => {
            let items = d.count.items;
            Object.keys(d.count).filter(k => k !== "items").forEach(key => {
                myData.push({ bin: d.xBin, type: d.xType, value: d.count[key], name: key, top: items, bottom: items - d.count[key] });
                items -= d.count[key];
            });
            if (items > 0) {
                myData.push({ bin: d.xBin, type: d.xType, value: items, name: "none", top: items, bottom: 0 });
            }
        });

        console.log("[HistogramBarChart] Transformed histogram data for bars:", myData);

        const barColor = d => colorScale(d.name);

        const applyBarEmphasis = (highlightedBins = null) => {
            bars
                .attr("fill", d => highlightedBins?.has(String(d.bin)) ? "gold" : barColor(d))
                .attr("opacity", d => !highlightedBins ? 0.95 : highlightedBins.has(String(d.bin)) ? 1 : 0.22)
                .attr("stroke", "white")
                .attr("stroke-width", 2);

            if (highlightedBins) {
                bars.filter(d => highlightedBins.has(String(d.bin))).raise();
            }
        };

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
            .attr("stroke-width", 2)
            .attr("opacity", 0.95);

        barsRef.current = bars;

        // Brush for range selection.
        const brush = d3.brushX()
            .extent([[0, 0], [size.w, size.h]])
            .on("brush end", (event) => {
                if (!event.selection) {
                    applyBarEmphasis();
                    if (event.type === "end" && event.sourceEvent) {
                        clearHighlight("histogram_brush_empty", { source: "histogram", cols: [attrX] });
                    }
                    return;
                }
                const [x0, x1] = event.selection;
                const brushedBins = new Set();
                myData.forEach(d => {
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

                applyBarEmphasis(brushedBins);

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
                        setHighlightedRef.current([...new Set(allIds)], [attrX], "histogram", {
                            action: "brush",
                            bins: binsToQuery,
                        });
                    });
                }
            });

        brushGroup.call(brush);
        brushGroup.lower();

        clearSelectionRef.current = () => {
            applyBarEmphasis();
            brushGroup.call(brush.move, null);
        };

        if (xScale && typeof xScale.draw === "function") xScale.draw(canvas, { detailMode });
        canvas.append("g")
            .attr("class", isFocused ? "axis axis--focused" : "axis axis--compact")
            .call(
                d3.axisLeft(yScale)
                    .ticks(isFocused ? 5 : 2)
                    .tickFormat(d3.format(".2s"))
                    .tickSizeOuter(0)
            )
            .selectAll("text")
            .attr("class", "left-axis-text");

        createTooltip(bars,
            d => {
                const bin = d.type === "numeric"
                    ? `${Math.round(numHistDataX[d.bin].x0)}-${Math.round(numHistDataX[d.bin].x1)}`
                    : d.bin;
                return `<strong>Bin: </strong>${bin}<br><strong>Items: </strong>${d.value}<br><strong>Errors: </strong>${d.name}`;
            },
            (d, event) => {
                if (isFocused && d3.select(event.currentTarget).attr("fill") === "gold") {
                    clearHighlight("histogram_selected_bin_click", { source: "histogram", cols: [attrX], bin: d.bin });
                    return;
                }
                // Left click: fetch row IDs for this bin then update context.
                const requestRevision = highlightRevisionRef.current;
                queryRowsInBin({ type: "1d", column: attrX, bin: d.bin})
                    .then(result => {
                        if (highlightRevisionRef.current !== requestRevision) return;
                        if (result?.success) {
                            setHighlightedRef.current(result.row_ids, [attrX], "histogram", {
                                action: "click",
                                bin: d.bin,
                            });
                        }
                    });
            },
            (d) => { console.log("Right click on bar", d); },
            (d) => { console.log("Double click on bar", d); },
            { showTooltip: isFocused, hoverOpacity: isFocused ? 0.65 : null }
        );

        return () => { canvas.selectAll("*").remove(); };
    }, [size, histogramData, detailMode]);

    // ── react to cross-chart highlight changes ──────────────────────────────
    useEffect(() => {
        if (!barsRef.current) return;
        const colorScale = colorScaleRef.current;

        if (!shouldHighlightSelection) {
            clearSelectionRef.current();
            return;
        }

        let isActive = true;

        queryBinsForRows({ type: "1d", column: attrX, row_ids: highlightedRowIds})
            .then(result => {
                if (!isActive || !result?.success || !barsRef.current) return;
                const highlightedBins = new Set(result.bins.map(String));
                barsRef.current
                    .attr("fill", d => highlightedBins.has(String(d.bin)) ? "gold" : colorScale(d.name))
                    .attr("opacity", d => highlightedBins.has(String(d.bin)) ? 1 : 0.22)
                    .attr("stroke", "white")
                    .attr("stroke-width", 2);
                barsRef.current.filter(d => highlightedBins.has(String(d.bin))).raise();
            });

        return () => {
            isActive = false;
        };
    }, [highlightedRowIds, highlightedCols, shouldHighlightSelection, attrX, highlightRevision, histogramData]);

    function clearSelection() {
        clearSelectionRef.current();
        clearHighlight("histogram_background_click", { source: "histogram", cols: [attrX] });
    }

    return (
        <g key={cellID} transform={`translate(${pos.x}, ${pos.y})`} className="barchart-canvas">
            <rect width={size.w} height={size.h} fill="#ffffff00" onClick={clearSelection} />
            <g ref={drawingRef}></g>
        </g>
    );
}

// Adds memoization (shallow copy) - may need to make a custom checker.
export default React.memo(HistogramBarChart);
