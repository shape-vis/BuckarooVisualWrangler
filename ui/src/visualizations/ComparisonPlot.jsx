// ComparisonPlot.jsx
// Draws two nodes' data against each other for the compare modal. The data arrives from
// /api/pgraph/compare already binned on axes both states share - see app/pgraph/compare.py - so every
// view here can put the two on the same scales.

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { createHybridScales } from "../utils/visCommon.jsx";
import { ERROR_DIMENSIONS, errorColors } from "../store/errorColors.js";
import { MEASURES, ROLE_COLORS, ROLE_NAMES, measureOf } from "../utils/comparison.js";

/* A difference is colored by what it means. Rows gained or lost are neither good nor bad, so they get
   a neutral pair; errors going down is an improvement, and gets the attribute panel's green. */
const DIFFERENCE_COLORS = {
    rows: { fewer: "#7c4dff", more: "#e8710a" },
    errors: { fewer: "#1a7f37", more: "#c1121f" },
};

// A tile that exists but measures zero - distinct from the white of no data at all
const NEUTRAL = "#eef0f2";

// How a scatter point's row fared between the two states
const STATUS_COLORS = { changed: "#f59e0b", added: "#7c3aed", removed: "#8a8d91" };
const STATUS_TEXT = {
    same: "unchanged",
    changed: "value changed",
    removed: "removed in the comparator",
    added: "added in the comparator",
};

const MARGIN = { top: 34, right: 18, bottom: 72, left: 76 };
const PANEL_GAP = 28;
const TOOLTIP_GAP = 12;
// Below this the canvas is mid-resize or collapsed, and there is nothing useful to lay out
const MIN_CANVAS = 120;

const formatCount = d3.format(",");
const formatDelta = (value) => (value > 0 ? `+${formatCount(value)}` : formatCount(value));
const formatValue = (value) => (Math.abs(value) >= 1e4 ? d3.format(".3~s")(value) : d3.format(".4~g")(value));

// Category labels are the user's data, and tooltips are set as html
function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]
    ));
}

const differenceColors = (measure) => (measure === "items" ? DIFFERENCE_COLORS.rows : DIFFERENCE_COLORS.errors);

/* Darker means more of the measure. Zero gets NEUTRAL rather than the ramp's pale end, so a tile whose
   rows carry no flags still reads as occupied. */
function sequentialColor(measure, peak) {
    const ramp = measure === "items" ? (t) => d3.interpolateBlues(0.15 + 0.85 * t)
        : measure === "errors" ? (t) => d3.interpolateOrRd(0.15 + 0.85 * t)
        : (t) => d3.interpolateRgb("#f3f3f3", errorColors(measure))(0.2 + 0.8 * t);
    return (value) => (value > 0 ? ramp(Math.min(1, value / peak)) : NEUTRAL);
}

function divergingColor(measure, extent) {
    const { fewer, more } = differenceColors(measure);
    return (delta) => (delta === 0
        ? NEUTRAL
        : d3.interpolateRgb(NEUTRAL, delta > 0 ? more : fewer)(0.25 + 0.75 * Math.min(1, Math.abs(delta) / extent)));
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

/* The modal sits above the app's shared #tooltip, so the plot keeps its own. It is placed within the
   canvas, and flips away from whichever edge it would run off. */
function makeTooltip(element, container) {
    const place = (event) => {
        const bounds = container.getBoundingClientRect();
        const x = event.clientX - bounds.left;
        const y = event.clientY - bounds.top;
        const { offsetWidth: width, offsetHeight: height } = element;
        const left = x + TOOLTIP_GAP + width > bounds.width ? x - TOOLTIP_GAP - width : x + TOOLTIP_GAP;
        const top = y + TOOLTIP_GAP + height > bounds.height ? y - TOOLTIP_GAP - height : y + TOOLTIP_GAP;
        element.style.left = `${Math.max(0, left)}px`;
        element.style.top = `${Math.max(0, top)}px`;
    };
    const hide = () => { element.style.display = "none"; };

    return {
        hide,
        attach(selection, html) {
            selection
                .on("mouseover", (event, d) => {
                    element.innerHTML = html(d);
                    element.style.display = "block";
                    place(event);
                    d3.select(event.currentTarget).classed("compare-mark--hover", true);
                })
                .on("mousemove", place)
                .on("mouseout", (event) => {
                    hide();
                    d3.select(event.currentTarget).classed("compare-mark--hover", false);
                });
        },
    };
}

const swatch = (color) => `<span class="compare-tooltip-swatch" style="background:${color}"></span>`;

function countLine(role, ctx, count) {
    const flags = ERROR_DIMENSIONS
        .filter((type) => count?.[type])
        .map((type) => `${formatCount(count[type])} ${MEASURES[type].noun}`);
    return `${swatch(ROLE_COLORS[role])}${ROLE_NAMES[role]} ${escapeHtml(ctx.labels[role])}: `
        + `<strong>${formatCount(count?.items ?? 0)}</strong> rows${flags.length ? ` (${flags.join(", ")})` : ""}`;
}

function countsTooltip(title, datum, ctx) {
    return `<strong>${escapeHtml(title)}</strong><br>`
        + `${countLine("base", ctx, datum.base)}<br>${countLine("other", ctx, datum.other)}`;
}

function differenceTooltip(title, datum, ctx) {
    const before = measureOf(datum.base, ctx.measure);
    const after = measureOf(datum.other, ctx.measure);
    return `<strong>${escapeHtml(title)}</strong><br>`
        + `${MEASURES[ctx.measure].label}: ${formatCount(before)} → ${formatCount(after)} `
        + `(<strong>${formatDelta(after - before)}</strong>)<br>`
        + `${countLine("base", ctx, datum.base)}<br>${countLine("other", ctx, datum.other)}`;
}

function pointTooltip(point, ctx) {
    const position = (value) => (typeof value === "number" ? formatValue(value) : value);
    const describe = (side) => (side
        ? `${escapeHtml(position(side.x))}, ${escapeHtml(position(side.y))}`
            + (side.errors.length ? ` · ${escapeHtml(side.errors.join(", "))}` : "")
        : "<em>not in this state</em>");

    return `<strong>Row ${escapeHtml(point.ID)}</strong> · ${STATUS_TEXT[point.status]}<br>`
        + `${swatch(ROLE_COLORS.base)}${ROLE_NAMES.base} ${escapeHtml(ctx.labels.base)}: ${describe(point.base)}<br>`
        + `${swatch(ROLE_COLORS.other)}${ROLE_NAMES.other} ${escapeHtml(ctx.labels.other)}: ${describe(point.other)}`;
}

// ── Scales and geometry ──────────────────────────────────────────────────────

/* The shared hybrid scale, fed the shape the backend sends for binned axes: numeric bin edges, then
   categorical labels. */
function binScale(scale, size, direction) {
    const numeric = scale.numeric ?? [];
    const categorical = scale.categorical ?? [];
    const numericDomain = numeric.length ? [numeric[0].x0, numeric[numeric.length - 1].x1] : null;
    return createHybridScales(size, numeric, categorical, numericDomain,
        categorical.length ? categorical : null, direction);
}

/* The same for a scatterplot, which sends a numeric domain rather than bins. Only bands some point
   actually uses are drawn, as the main scatterplot does. */
function pointScales(data, w, h) {
    const sides = data.points.flatMap((point) => [point.base, point.other]).filter(Boolean);

    const scaleFor = (axis, size, direction) => {
        const scale = axis === "x" ? data.scaleX : data.scaleY;
        const used = new Set(sides.filter((side) => side[`${axis}Type`] === "categorical").map((side) => side[axis]));
        const categories = (scale.categorical ?? []).filter((label) => used.has(label));
        const numeric = scale.numeric ?? [];
        return createHybridScales(size, numeric, categories, numeric.length ? numeric : null,
            categories.length ? categories : null, direction);
    };

    return { xScale: scaleFor("x", w, "horizontal"), yScale: scaleFor("y", h, "vertical") };
}

function spanX(xScale, scale, datum) {
    if (datum.xType === "numeric") {
        const { x0, x1 } = scale.numeric[datum.xBin];
        return { x: xScale.apply(x0, "numeric"), w: xScale.numericalBandwidth(x0, x1) };
    }
    return { x: xScale.apply(datum.xBin, "categorical"), w: xScale.categoricalBandwidth() };
}

// The vertical scale runs bottom to top, so a numeric bin's top edge is its x1
function spanY(yScale, scale, datum) {
    if (datum.yType === "numeric") {
        const { x0, x1 } = scale.numeric[datum.yBin];
        return { y: yScale.apply(x1, "numeric"), h: yScale.numericalBandwidth(x1, x0) };
    }
    return { y: yScale.apply(datum.yBin, "categorical"), h: yScale.categoricalBandwidth() };
}

function binLabel(scale, type, bin) {
    if (type !== "numeric") return String(bin);
    const { x0, x1 } = scale.numeric[bin];
    return `${formatValue(x0)} – ${formatValue(x1)}`;
}

const tileLabel = (data, tile) => `${data.x}: ${binLabel(data.scaleX, tile.xType, tile.xBin)} · `
    + `${data.y}: ${binLabel(data.scaleY, tile.yType, tile.yBin)}`;

const position = (scale, side, axis) => scale.apply(side[axis], side[`${axis}Type`], true);
const pointFill = (side) => errorColors(side.errors[0] ?? "none");

// ── Frames ───────────────────────────────────────────────────────────────────

/* Split the canvas into side-by-side plot areas, each with room for its own axes. */
function layoutPanels(svg, width, height, count) {
    const slot = (width - PANEL_GAP * (count - 1)) / count;
    return d3.range(count).map((i) => ({
        g: svg.append("g").attr("transform", `translate(${i * (slot + PANEL_GAP) + MARGIN.left}, ${MARGIN.top})`),
        w: Math.max(10, slot - MARGIN.left - MARGIN.right),
        h: Math.max(10, height - MARGIN.top - MARGIN.bottom),
    }));
}

// Draws one colored chip and its label, returning where the next one can start
function titleChip(title, x, role, text) {
    title.append("rect")
        .attr("x", x).attr("y", -9).attr("width", 10).attr("height", 10).attr("rx", 2)
        .attr("fill", ROLE_COLORS[role]);
    const label = title.append("text").attr("x", x + 16).text(text);
    return x + 16 + label.node().getComputedTextLength() + 18;
}

function panelTitle(g, role, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    titleChip(title, 0, role, `${ROLE_NAMES[role]} · ${ctx.labels[role]}`);
}

function pairTitle(g, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    const next = titleChip(title, 0, "base", `${ROLE_NAMES.base} · ${ctx.labels.base}`);
    titleChip(title, next, "other", `${ROLE_NAMES.other} · ${ctx.labels.other}`);
}

/* createHybridScales draws its x axis at y = size, which assumes a square plot. These panels are not
   square, so the axis goes into a group shifted by the difference, landing it on the panel's floor. */
function drawXAxis(g, xScale, w, h) {
    xScale.draw(g.append("g").attr("class", "compare-axis").attr("transform", `translate(0, ${h - w})`));
}

function drawYAxis(g, yScale) {
    yScale.draw(g.append("g").attr("class", "compare-axis"));
}

function drawCountAxis(g, y, format = formatCount) {
    g.append("g").attr("class", "compare-axis")
        .call(d3.axisLeft(y).ticks(5).tickFormat(format))
        .selectAll("text").attr("class", "left-axis-text");
}

function axisLabels(g, w, h, xLabel, yLabel) {
    g.append("text").attr("class", "compare-axis-label")
        .attr("x", w / 2).attr("y", h + MARGIN.bottom - 10).attr("text-anchor", "middle")
        .text(xLabel);
    if (yLabel) {
        g.append("text").attr("class", "compare-axis-label")
            .attr("transform", `translate(${14 - MARGIN.left}, ${h / 2}) rotate(-90)`)
            .attr("text-anchor", "middle")
            .text(yLabel);
    }
}

// ── Histograms ───────────────────────────────────────────────────────────────

/* One bar's stack: error flags from the top down, clean rows beneath - the main histograms' order. */
function stackSegments(count) {
    const segments = [];
    let top = count.items;
    ERROR_DIMENSIONS.forEach((type) => {
        const value = count[type] ?? 0;
        if (!value) return;
        segments.push({ type, top, bottom: Math.max(0, top - value) });
        top -= value;
    });
    if (top > 0) segments.push({ type: "none", top, bottom: 0 });
    return segments;
}

function drawHistogramSide(svg, data, ctx) {
    // One y domain for both panels, or bars of equal height would not be equal counts
    const peak = d3.max(data.bins, (bin) => Math.max(bin.base.items, bin.other.items)) || 1;

    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({ g, w, h }, i) => {
        const role = i === 0 ? "base" : "other";
        const xScale = binScale(data.scaleX, w, "horizontal");
        const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

        const segments = data.bins.flatMap((bin) => stackSegments(bin[role]).map((segment) => ({ ...segment, bin })));
        const bars = g.append("g").selectAll("rect").data(segments).join("rect")
            .attr("class", "compare-mark")
            .attr("x", (d) => spanX(xScale, data.scaleX, d.bin).x)
            .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w - 1))
            .attr("y", (d) => y(d.top))
            .attr("height", (d) => Math.max(0, y(d.bottom) - y(d.top)))
            .attr("fill", (d) => errorColors(d.type))
            .attr("stroke", "white")
            .attr("stroke-width", 0.5);
        ctx.tooltip.attach(bars, (d) => countsTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

        drawXAxis(g, xScale, w, h);
        drawCountAxis(g, y);
        panelTitle(g, role, ctx);
        axisLabels(g, w, h, data.x, i === 0 ? "Rows" : null);
    });
}

function drawHistogramOverlay(svg, data, ctx) {
    const [{ g, w, h }] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const peak = d3.max(data.bins, (bin) => Math.max(bin.base.items, bin.other.items)) || 1;
    const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

    // Each bin is split down the middle: the baseline's bar on the left, the comparator's on the right
    const bars = data.bins.flatMap((bin) => [{ bin, role: "base" }, { bin, role: "other" }]);
    const marks = g.append("g").selectAll("rect").data(bars).join("rect")
        .attr("class", "compare-mark")
        .attr("x", (d) => {
            const span = spanX(xScale, data.scaleX, d.bin);
            return span.x + (d.role === "base" ? 1 : span.w / 2);
        })
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w / 2 - 1))
        .attr("y", (d) => y(d.bin[d.role].items))
        .attr("height", (d) => Math.max(0, h - y(d.bin[d.role].items)))
        .attr("fill", (d) => ROLE_COLORS[d.role])
        .attr("fill-opacity", 0.85);
    ctx.tooltip.attach(marks, (d) => countsTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

    drawXAxis(g, xScale, w, h);
    drawCountAxis(g, y);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, "Rows");
}

function drawHistogramDifference(svg, data, ctx) {
    const [{ g, w, h }] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const deltas = data.bins.map((bin) => ({
        bin,
        delta: measureOf(bin.other, ctx.measure) - measureOf(bin.base, ctx.measure),
    }));
    // Symmetric about zero, so a gain and a loss of the same size are bars of the same length
    const extent = d3.max(deltas, (d) => Math.abs(d.delta)) || 1;
    const y = d3.scaleLinear().domain([-extent, extent]).nice().range([h, 0]);
    const { fewer, more } = differenceColors(ctx.measure);

    g.append("g").selectAll("rect").data(deltas.filter((d) => d.delta !== 0)).join("rect")
        .attr("x", (d) => spanX(xScale, data.scaleX, d.bin).x)
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w - 1))
        .attr("y", (d) => y(Math.max(0, d.delta)))
        .attr("height", (d) => Math.abs(y(d.delta) - y(0)))
        .attr("fill", (d) => (d.delta > 0 ? more : fewer));
    g.append("line").attr("class", "compare-zero").attr("x1", 0).attr("x2", w).attr("y1", y(0)).attr("y2", y(0));

    // Full-height hit areas, so a bin that did not change can still be hovered for its numbers
    const hits = g.append("g").selectAll("rect").data(deltas).join("rect")
        .attr("class", "compare-hit")
        .attr("x", (d) => spanX(xScale, data.scaleX, d.bin).x)
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w))
        .attr("y", 0)
        .attr("height", h);
    ctx.tooltip.attach(hits, (d) => differenceTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

    drawXAxis(g, xScale, w, h);
    drawCountAxis(g, y, formatDelta);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, `Change in ${MEASURES[ctx.measure].noun}`);
}

// ── Heatmaps ─────────────────────────────────────────────────────────────────

function drawTiles(g, data, xScale, yScale, tiles) {
    return g.append("g").selectAll("rect").data(tiles).join("rect")
        .attr("class", "compare-mark")
        .attr("x", (tile) => spanX(xScale, data.scaleX, tile).x)
        .attr("width", (tile) => Math.max(0, spanX(xScale, data.scaleX, tile).w))
        .attr("y", (tile) => spanY(yScale, data.scaleY, tile).y)
        .attr("height", (tile) => Math.max(0, spanY(yScale, data.scaleY, tile).h))
        .attr("stroke", "white")
        .attr("stroke-width", 1);
}

function drawHeatmapSide(svg, data, ctx) {
    // One color scale for both panels, so equal shades are equal counts
    const peak = d3.max(data.tiles, (tile) => Math.max(
        measureOf(tile.base, ctx.measure), measureOf(tile.other, ctx.measure))) || 1;
    const fill = sequentialColor(ctx.measure, peak);

    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({ g, w, h }, i) => {
        const role = i === 0 ? "base" : "other";
        const xScale = binScale(data.scaleX, w, "horizontal");
        const yScale = binScale(data.scaleY, h, "vertical");

        const tiles = drawTiles(g, data, xScale, yScale, data.tiles.filter((tile) => tile[role].items > 0))
            .attr("fill", (tile) => fill(measureOf(tile[role], ctx.measure)));
        ctx.tooltip.attach(tiles, (tile) => countsTooltip(tileLabel(data, tile), tile, ctx));

        drawXAxis(g, xScale, w, h);
        drawYAxis(g, yScale);
        panelTitle(g, role, ctx);
        axisLabels(g, w, h, data.x, data.y);
    });
}

function drawHeatmapDifference(svg, data, ctx) {
    const [{ g, w, h }] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const yScale = binScale(data.scaleY, h, "vertical");
    const delta = (tile) => measureOf(tile.other, ctx.measure) - measureOf(tile.base, ctx.measure);
    const extent = d3.max(data.tiles, (tile) => Math.abs(delta(tile))) || 1;
    const fill = divergingColor(ctx.measure, extent);

    const tiles = drawTiles(g, data, xScale, yScale, data.tiles).attr("fill", (tile) => fill(delta(tile)));
    ctx.tooltip.attach(tiles, (tile) => differenceTooltip(tileLabel(data, tile), tile, ctx));

    drawXAxis(g, xScale, w, h);
    drawYAxis(g, yScale);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, data.y);
}

// ── Scatterplots ─────────────────────────────────────────────────────────────

// Ghosts last so their dashed rings stay visible; changed rows above the unchanged ones
const markOrder = (mark) => (mark.ghost ? 2 : mark.point.status === "same" ? 0 : 1);

function drawScatterSide(svg, data, ctx) {
    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({ g, w, h }, i) => {
        const role = i === 0 ? "base" : "other";
        const counterpart = i === 0 ? "other" : "base";
        const { xScale, yScale } = pointScales(data, w, h);

        /* A row missing from this state is drawn as a dashed ghost where it stands in the other, so a
           delete reads as points vanishing rather than as nothing at all. */
        const marks = data.points
            .map((point) => (point[role]
                ? { point, side: point[role], ghost: false }
                : { point, side: point[counterpart], ghost: true }))
            .sort((a, b) => markOrder(a) - markOrder(b));

        const circles = g.append("g").selectAll("circle").data(marks).join("circle")
            .attr("class", "compare-mark")
            .attr("cx", (d) => position(xScale, d.side, "x"))
            .attr("cy", (d) => position(yScale, d.side, "y"))
            .attr("r", 4)
            .attr("fill", (d) => (d.ghost ? "none" : pointFill(d.side)))
            .attr("fill-opacity", 0.75)
            .attr("pointer-events", "all")
            .attr("stroke", (d) => (d.ghost ? STATUS_COLORS.removed : (STATUS_COLORS[d.point.status] ?? "none")))
            .attr("stroke-width", (d) => (d.ghost || d.point.status !== "same" ? 1.75 : 0))
            .attr("stroke-dasharray", (d) => (d.ghost ? "2 2" : null));
        ctx.tooltip.attach(circles, (d) => pointTooltip(d.point, ctx));

        drawXAxis(g, xScale, w, h);
        drawYAxis(g, yScale);
        panelTitle(g, role, ctx);
        axisLabels(g, w, h, data.x, data.y);
    });
}

function drawScatterOverlay(svg, data, ctx) {
    const [{ g, w, h }] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const { xScale, yScale } = pointScales(data, w, h);
    const at = (side) => [position(xScale, side, "x"), position(yScale, side, "y")];

    svg.append("defs").append("marker")
        .attr("id", "compare-arrow")
        .attr("viewBox", "0 0 10 10").attr("refX", 9).attr("refY", 5)
        .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
        .append("path").attr("d", "M 0 0 L 10 5 L 0 10 z").attr("fill", STATUS_COLORS.changed);

    // A changed row is drawn as a move: from where it stood in the baseline to where it stands now
    g.append("g").selectAll("line").data(data.points.filter((point) => point.status === "changed")).join("line")
        .attr("x1", (point) => at(point.base)[0])
        .attr("y1", (point) => at(point.base)[1])
        .attr("x2", (point) => at(point.other)[0])
        .attr("y2", (point) => at(point.other)[1])
        .attr("stroke", STATUS_COLORS.changed)
        .attr("stroke-width", 1.25)
        .attr("stroke-opacity", 0.85)
        .attr("marker-end", "url(#compare-arrow)");

    const before = g.append("g").selectAll("circle").data(data.points.filter((point) => point.base)).join("circle")
        .attr("class", "compare-mark")
        .attr("cx", (point) => at(point.base)[0])
        .attr("cy", (point) => at(point.base)[1])
        .attr("r", 4.5)
        .attr("fill", "none")
        .attr("pointer-events", "all")
        .attr("stroke", ROLE_COLORS.base)
        .attr("stroke-width", 1.5);

    const after = g.append("g").selectAll("circle").data(data.points.filter((point) => point.other)).join("circle")
        .attr("class", "compare-mark")
        .attr("cx", (point) => at(point.other)[0])
        .attr("cy", (point) => at(point.other)[1])
        .attr("r", 3.5)
        .attr("fill", ROLE_COLORS.other)
        .attr("fill-opacity", 0.7);

    ctx.tooltip.attach(before, (point) => pointTooltip(point, ctx));
    ctx.tooltip.attach(after, (point) => pointTooltip(point, ctx));

    drawXAxis(g, xScale, w, h);
    drawYAxis(g, yScale);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, data.y);
}

const DRAWERS = {
    histogram: { side: drawHistogramSide, overlay: drawHistogramOverlay, difference: drawHistogramDifference },
    heatmap: { side: drawHeatmapSide, difference: drawHeatmapDifference },
    scatter: { side: drawScatterSide, overlay: drawScatterOverlay },
};

function isEmpty(data) {
    const marks = data.kind === "histogram" ? data.bins : data.kind === "heatmap" ? data.tiles : data.points;
    return !marks?.length;
}

function drawEmpty(svg, { width, height }) {
    svg.append("text").attr("class", "compare-empty")
        .attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
        .text("Neither node has rows to plot for this selection");
}

// ── Legend ───────────────────────────────────────────────────────────────────

function legendItems(kind, view, measure, labels) {
    const roleLabel = (role) => `${ROLE_NAMES[role]} · ${labels[role]}`;
    const errorItems = [
        ...ERROR_DIMENSIONS.map((type) => ({ label: MEASURES[type].label, style: { background: errorColors(type) } })),
        { label: "No errors", style: { background: errorColors("none") } },
    ];

    if (view === "difference") {
        const { fewer, more } = differenceColors(measure);
        const noun = MEASURES[measure].noun;
        const [better, worse] = measure === "items" ? ["", ""] : [" (better)", " (worse)"];
        return [
            { label: `Fewer ${noun} in the comparator${better}`, style: { background: fewer } },
            { label: `More ${noun} in the comparator${worse}`, style: { background: more } },
        ];
    }

    if (kind === "heatmap") {
        const fill = sequentialColor(measure, 1);
        const items = [{
            label: `Darker tiles hold more ${MEASURES[measure].noun}`,
            shape: "ramp",
            style: { background: `linear-gradient(to right, ${fill(0.01)}, ${fill(1)})` },
        }];
        if (measure !== "items") items.push({ label: "Rows, none flagged", style: { background: NEUTRAL } });
        return items;
    }

    if (kind === "histogram") {
        return view === "overlay"
            ? ["base", "other"].map((role) => ({ label: roleLabel(role), style: { background: ROLE_COLORS[role] } }))
            : errorItems;
    }

    if (view === "overlay") {
        return [
            { label: roleLabel("base"), shape: "ring", style: { borderColor: ROLE_COLORS.base } },
            { label: roleLabel("other"), shape: "dot", style: { background: ROLE_COLORS.other } },
            { label: "Value changed", shape: "line", style: { background: STATUS_COLORS.changed } },
        ];
    }

    return [
        ...errorItems,
        { label: "Changed", shape: "ring", style: { borderColor: STATUS_COLORS.changed } },
        { label: "Added", shape: "ring", style: { borderColor: STATUS_COLORS.added } },
        { label: "Removed", shape: "ring", style: { borderColor: STATUS_COLORS.removed } },
        { label: "Not in this state", shape: "ghost" },
    ];
}

/**
 * The compare modal's plot.
 *
 * Props:
 *  - data: a /api/pgraph/compare response, or null while there is none to show
 *  - view: "side" | "overlay" | "difference" - which the kind supports is the modal's call
 *  - measure: a MEASURES key, read by difference views and heatmaps
 *  - baseLabel, otherLabel: short names for the two nodes
 */
export default function ComparisonPlot({ data, view, measure, baseLabel, otherLabel }) {
    const canvasRef = useRef(null);
    const svgRef = useRef(null);
    const tooltipRef = useRef(null);
    const [size, setSize] = useState({ width: 0, height: 0 });

    // The canvas takes whatever room the modal gives it, and the plot is laid out from that
    useEffect(() => {
        const observer = new ResizeObserver(([entry]) => {
            setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
        });
        observer.observe(canvasRef.current);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        const svg = d3.select(svgRef.current);
        const draw = data && DRAWERS[data.kind]?.[view];
        if (!draw || size.width < MIN_CANVAS || size.height < MIN_CANVAS) return;

        const tooltip = makeTooltip(tooltipRef.current, canvasRef.current);
        if (isEmpty(data)) {
            drawEmpty(svg, size);
        } else {
            draw(svg, data, { ...size, measure, tooltip, labels: { base: baseLabel, other: otherLabel } });
        }

        return () => {
            tooltip.hide();
            svg.selectAll("*").remove();
        };
    }, [data, view, measure, baseLabel, otherLabel, size]);

    return (
        <div className="compare-plot-frame">
            <div ref={canvasRef} className="compare-plot-canvas">
                <svg ref={svgRef} width={size.width} height={size.height} />
                <div ref={tooltipRef} className="compare-tooltip" />
            </div>
            {data && (
                <div className="compare-legend">
                    {legendItems(data.kind, view, measure, { base: baseLabel, other: otherLabel }).map((item) => (
                        <span key={item.label} className="compare-legend-item">
                            <span
                                className={`compare-legend-mark compare-legend-mark--${item.shape ?? "box"}`}
                                style={item.style}
                            />
                            {item.label}
                        </span>
                    ))}
                </div>
            )}
            {data?.kind === "scatter" && (
                <div className="compare-caption">
                    Showing {data.sampled.toLocaleString()} of {data.population.toLocaleString()} rows.
                    Rows that changed or carry errors are sampled first.
                </div>
            )}
        </div>
    );
}
