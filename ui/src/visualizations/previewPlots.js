// previewPlots.js
// The small error plots the repair preview draws - a stacked histogram (1D), a heatmap (2D) or a scatterplot -
// for a graph node's own table. Fetched from /api/plots/preview-histogram and /api/plots/preview-scatterplot,
// which read whichever table they are named, so the session's current table is left alone. Shared by
// PreviewCard and the error-plot sub-node, so the two always look the same.

import { useEffect, useState } from "react";
import * as d3 from "d3";
import { queryPreviewHistogram, queryPreviewScatterplot } from "../utils/serverCalls.jsx";
import { createBinnedScales, createHybridScales, createTooltip } from "../utils/visCommon.jsx";
import { pointColor, stackBars, tileColor } from "./errorPlots.js";

const PLOT_SIZE = 150;   // px – inner chart area (square)
export const LEFT_M = 35;
export const TOP_M = 10;
const BOTTOM_M = 40;
const RIGHT_M = 10;
export const SVG_W = PLOT_SIZE + LEFT_M + RIGHT_M;
export const SVG_H = PLOT_SIZE + TOP_M + BOTTOM_M;

/* The request for one kind of preview plot, answering [the server's reply, the data in it] */
function requestFor(kind, table, x, y) {
    if (kind === "histogram") {
        return queryPreviewHistogram({ type: "1d", tablename: table, column: x, bins: 10 })
            .then((result) => [result, result?.histogram]);
    }
    if (kind === "heatmap") {
        return queryPreviewHistogram({ type: "2d", tablename: table, column_x: x, column_y: y, x_bins: 10, y_bins: 10 })
            .then((result) => [result, result?.histogram]);
    }
    return queryPreviewScatterplot({
        tablename: table, x_column: x, y_column: y, error_sample_count: 300, total_sample_count: 1000,
    }).then((result) => [result, result?.scatterplot_data]);
}

/**
 * The data one preview plot draws, refetched as the table, kind or columns change. A reply that arrives after
 * they have moved on is dropped, so a quick change of columns never draws the last one's data.
 *
 * @param table   the table to plot
 * @param kind    "histogram" (1 column), "heatmap" or "scatterplot" (2 columns)
 * @param columns the column names, in x, y order
 * @param enabled false holds the request back - for a plot not yet scrolled into view
 * @returns {data, loading, error}
 */
export function usePreviewPlotData({ table, kind, columns, enabled = true }) {
    const [state, setState] = useState({ key: null, data: null, error: null });
    const key = [table, kind, ...(columns ?? [])].join("|");
    const ready = Boolean(table) && (columns?.length ?? 0) >= (kind === "histogram" ? 1 : 2);

    useEffect(() => {
        if (!enabled || !ready) return undefined;
        let stale = false;
        const [x, y] = columns;
        requestFor(kind, table, x, y).then(([result, data]) => {
            if (stale) return;
            if (result?.success) {
                setState({ key, data, error: null });
            } else {
                setState({ key, data: null, error: result?.error || "Failed to load preview" });
            }
        });
        return () => { stale = true; };
        // columns is read through key, which names them
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key, enabled, ready]);

    const current = state.key === key ? state : null;
    return { data: current?.data ?? null, loading: ready && !current, error: current?.error ?? null };
}

/**
 * A scatterplot's two scales. The categorical part of each axis keeps only the categories some point actually
 * has - and is left off altogether when keepCategories is false, for a plot drawn without error colours.
 */
export function scatterScales(scatterData, size, keepCategories) {
    const points = scatterData.data || [];
    const numHistDataX = scatterData.scaleX.numeric || [];
    const numHistDataY = scatterData.scaleY.numeric || [];

    const actualXCats = new Set(points.filter(d => d.xType === "categorical").map(d => d.x));
    const actualYCats = new Set(points.filter(d => d.yType === "categorical").map(d => d.y));
    let catHistDataX = [];
    let catHistDataY = [];
    if (keepCategories) {
        catHistDataX = (scatterData.scaleX.categorical || []).filter(v => actualXCats.has(v));
        catHistDataY = (scatterData.scaleY.categorical || []).filter(v => actualYCats.has(v));
    }

    // A scatterplot's numeric scale arrives as its domain already, rather than as bins
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
    return { xScale, yScale };
}

// ── 1-D bar chart renderer ─────────────────────────────────────────────────
export function draw1D(canvas, histogramData, colorScale, size = PLOT_SIZE) {
    const numHistDataX = histogramData.scaleX.numeric || [];
    const catHistDataX = histogramData.scaleX.categorical || [];

    const xScale = createBinnedScales(size, numHistDataX, catHistDataX, "horizontal");
    const yScale = d3.scaleLinear()
        .domain([0, d3.max(histogramData.histograms, d => d.count.items) || 1]).nice()
        .range([size, 0]);

    canvas.append("g")
        .selectAll("rect")
        .data(stackBars(histogramData.histograms))
        .join("rect")
        .attr("x", d => xScale.apply(d.type === "numeric" ? numHistDataX[d.bin]?.x0 : d.bin, d.type))
        .attr("y", d => yScale(d.top))
        .attr("height", d => Math.max(0, yScale(d.bottom) - yScale(d.top)))
        .attr("width", d => d.type === "numeric"
            ? xScale.numericalBandwidth(numHistDataX[d.bin]?.x0, numHistDataX[d.bin]?.x1)
            : xScale.categoricalBandwidth())
        .attr("fill", d => colorScale(d.name))
        .attr("stroke", "white")
        .attr("stroke-width", 1);

    canvas.append("g").call(d3.axisLeft(yScale).ticks(4)).style("font-size", "7px");
    xScale.draw(canvas);
}

// ── 2-D heatmap renderer ───────────────────────────────────────────────────
export function draw2D(canvas, histogramData, colorScale, size = PLOT_SIZE) {
    const numHistDataX = histogramData.scaleX.numeric || [];
    const catHistDataX = histogramData.scaleX.categorical || [];
    const numHistDataY = histogramData.scaleY.numeric || [];
    const catHistDataY = histogramData.scaleY.categorical || [];

    const xScale = createBinnedScales(size, numHistDataX, catHistDataX, "horizontal");
    const yScale = createBinnedScales(size, numHistDataY, catHistDataY, "vertical");

    xScale.draw(canvas);
    yScale.draw(canvas);

    const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);

    const tiles = canvas.append("g")
        .selectAll("rect")
        .data(binsToRender)
        .join("rect")
        .attr("x", d => xScale.apply(d.xType === "numeric" ? xScale.numHistData[d.xBin]?.x0 : d.xBin, d.xType))
        .attr("y", d => yScale.apply(d.yType === "numeric" ? yScale.numHistData[d.yBin]?.x1 : d.yBin, d.yType))
        .attr("height", d => d.yType === "numeric"
            ? yScale.numericalBandwidth(yScale.numHistData[d.yBin]?.x1, yScale.numHistData[d.yBin]?.x0)
            : yScale.categoricalBandwidth())
        .attr("width", d => d.xType === "numeric"
            ? xScale.numericalBandwidth(xScale.numHistData[d.xBin]?.x0, xScale.numHistData[d.xBin]?.x1)
            : xScale.categoricalBandwidth())
        .attr("fill", d => tileColor(colorScale, d))
        .attr("stroke", "white")
        .attr("stroke-width", 1);

    createTooltip(tiles, d => `<strong>Items:</strong> ${d.count.items}`);
}

// ── Scatterplot renderer ───────────────────────────────────────────────────
export function drawScatter(canvas, scatterData, colorScale, size = PLOT_SIZE) {
    const { xScale, yScale } = scatterScales(scatterData, size, Boolean(colorScale));

    xScale.draw(canvas);
    yScale.draw(canvas);

    canvas.selectAll("circle")
        .data(scatterData.data || [])
        .join("circle")
        .attr("cx", d => xScale.apply(d.x, d.xType, true))
        .attr("cy", d => yScale.apply(d.y, d.yType, true))
        .attr("r", 3)
        .attr("fill", d => pointColor(colorScale, d))
        .attr("opacity", 0.7);
}
