// ComparisonPlot.jsx
// Draws two nodes' data against each other for the compare modal. The data arrives from
// /api/pgraph/compare already binned on axes both states share - see app/pgraph/compare.py - so every
// view here can put the two on the same scales.

import {useCallback, useEffect, useId, useMemo, useRef, useState} from "react";
import * as d3 from "d3";
import RidgelineBrush from "./RidgelineBrush.jsx";
import {createHybridScales} from "../utils/visCommon.jsx";
import {ERROR_DIMENSIONS, errorColors} from "../store/errorColors.js";
import {MEASURES, ROLE_COLORS, ROLE_NAMES, measureOf} from "../utils/comparison.js";
import {NULL_FLAG_TITLE, formatDrift} from "../utils/drift.js";

/* A difference is colored by what it means. Rows gained or lost are neither good nor bad, so they get
   a neutral pair; errors going down is an improvement, and gets the attribute panel's green. */
const DIFFERENCE_COLORS = {
    rows: {fewer: "#7c4dff", more: "#e8710a"},
    errors: {fewer: "#1a7f37", more: "#c1121f"},
};

// A tile that exists but measures zero - distinct from the white of no data at all
const NEUTRAL = "#eef0f2";

const MARGIN = {top: 34, right: 18, bottom: 72, left: 76};
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
        {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]
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
    const {fewer, more} = differenceColors(measure);
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
        const {offsetWidth: width, offsetHeight: height} = element;
        const left = x + TOOLTIP_GAP + width > bounds.width ? x - TOOLTIP_GAP - width : x + TOOLTIP_GAP;
        const top = y + TOOLTIP_GAP + height > bounds.height ? y - TOOLTIP_GAP - height : y + TOOLTIP_GAP;
        element.style.left = `${Math.max(0, left)}px`;
        element.style.top = `${Math.max(0, top)}px`;
    };
    const hide = () => {
        element.style.display = "none";
    };

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

function spanX(xScale, scale, datum) {
    if (datum.xType === "numeric") {
        const {x0, x1} = scale.numeric[datum.xBin];
        return {x: xScale.apply(x0, "numeric"), w: xScale.numericalBandwidth(x0, x1)};
    }
    return {x: xScale.apply(datum.xBin, "categorical"), w: xScale.categoricalBandwidth()};
}

// The vertical scale runs bottom to top, so a numeric bin's top edge is its x1
function spanY(yScale, scale, datum) {
    if (datum.yType === "numeric") {
        const {x0, x1} = scale.numeric[datum.yBin];
        return {y: yScale.apply(x1, "numeric"), h: yScale.numericalBandwidth(x1, x0)};
    }
    return {y: yScale.apply(datum.yBin, "categorical"), h: yScale.categoricalBandwidth()};
}

function binLabel(scale, type, bin) {
    if (type !== "numeric") return String(bin);
    const {x0, x1} = scale.numeric[bin];
    return `${formatValue(x0)} – ${formatValue(x1)}`;
}

const tileLabel = (data, tile) => `${data.x}: ${binLabel(data.scaleX, tile.xType, tile.xBin)} · `
    + `${data.y}: ${binLabel(data.scaleY, tile.yType, tile.yBin)}`;

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
        segments.push({type, top, bottom: Math.max(0, top - value)});
        top -= value;
    });
    if (top > 0) segments.push({type: "none", top, bottom: 0});
    return segments;
}

function drawHistogramSide(svg, data, ctx) {
    // One y domain for both panels, or bars of equal height would not be equal counts
    const peak = d3.max(data.bins, (bin) => Math.max(bin.base.items, bin.other.items)) || 1;

    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({g, w, h}, i) => {
        const role = i === 0 ? "base" : "other";
        const xScale = binScale(data.scaleX, w, "horizontal");
        const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

        const segments = data.bins.flatMap((bin) => stackSegments(bin[role]).map((segment) => ({...segment, bin})));
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
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const peak = d3.max(data.bins, (bin) => Math.max(bin.base.items, bin.other.items)) || 1;
    const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

    // Each bin is split down the middle: the baseline's bar on the left, the comparator's on the right
    const bars = data.bins.flatMap((bin) => [{bin, role: "base"}, {bin, role: "other"}]);
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
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const deltas = data.bins.map((bin) => ({
        bin,
        delta: measureOf(bin.other, ctx.measure) - measureOf(bin.base, ctx.measure),
    }));
    // Symmetric about zero, so a gain and a loss of the same size are bars of the same length
    const extent = d3.max(deltas, (d) => Math.abs(d.delta)) || 1;
    const y = d3.scaleLinear().domain([-extent, extent]).nice().range([h, 0]);
    const {fewer, more} = differenceColors(ctx.measure);

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

    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({g, w, h}, i) => {
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
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
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

// ── Drift ────────────────────────────────────────────────────────────────────
// Each node against root, from /api/pgraph/drift_detail - see app/pgraph/distortion.py. Drift is a cost,
// not an error, so none of these views colors it good or bad: red is kept for the null test's flag.

// Rows that stayed in their category, were recoded into another, or were deleted
const FLOW_COLORS = {stayed: "#94a3b8", recoded: "#f59e0b", removed: "#4b5563"};
const ROOT_COLOR = "#8c939d";
const FLAG_COLOR = "#d1242f";
// The server's name for the deleted rows' sink
const REMOVED_LABEL = "(removed)";
// Room at the right of a ridgeline for each row's drift
const DRIFT_GUTTER = 72;

// Which kind of column each drift view draws, so a result for the last column is never drawn as the next
const DRIFT_VIEW_KINDS = {ridgeline: "numeric", flows: "categorical"};

const formatShare = d3.format(".1%");

// The annotation bubble's radius, and how far it sits from the spot it points at
const BUBBLE_R = 11;
const BUBBLE_REACH = 34;

/* Where a node's rows changed most - the grid index its annotation bubble points at.

   A node's curve is kept at its share of root's rows rather than rescaled, so root's curve minus the node's
   is the smoothed shape of the rows removed - and, below zero, of the values filled in. Its peak is where
   most rows changed. Rescaling the two to one total first would ask where the shape changed instead, and
   that lands on the peak whenever rows leave a thin tail: the bulk lifts a little, and a little on the
   tallest part of the curve outweighs the whole tail.

   Thinning the whole column shared - rows lost to a step on another column, say - is taken out first, or
   it would win at the peak every time. It is the smallest share any well-populated part of the column
   lost. A node that changed nothing points at its own peak. */
function mostChanged(root, curve) {
    const peak = d3.max(root) || 1;
    const gap = curve.map((value, i) => root[i] - value);
    if (d3.max(gap, (value) => Math.abs(value)) < 1e-9 * peak) return d3.maxIndex(curve);

    const busy = d3.range(root.length).filter((i) => root[i] >= 0.01 * peak);
    const shared = Math.min(Math.max(d3.min(busy, (i) => gap[i] / root[i]) ?? 0, 0), 1);
    return d3.maxIndex(gap, (value, i) => Math.abs(value - shared * root[i]));
}

/* A thought bubble pinned beside the place a node's data actually moved, with an arrow to that place. The
   annotation used to be a paragraph under the plot, which left the reader to work out which part of the
   picture it described; hovering the bubble puts it next to that part instead. aside is appended to the
   sentences - a zoomed ridgeline uses it to say the spot is outside the range shown. */
function drawAnnotationBubble(g, {ax, ay, bounds, aside}, role, side, ctx) {
    const sentences = side?.annotation?.sentences ?? [];
    if (!sentences.length) return;

    const color = ROLE_COLORS[role];
    // Up and to the right of the spot, but never outside the panel it belongs to
    const bx = Math.min(Math.max(ax + BUBBLE_REACH, bounds.left + BUBBLE_R), bounds.right - BUBBLE_R);
    const by = Math.min(Math.max(ay - BUBBLE_REACH, bounds.top + BUBBLE_R), bounds.bottom - BUBBLE_R);
    const at = (t) => [bx + (ax - bx) * t, by + (ay - by) * t];
    const angle = Math.atan2(ay - by, ax - bx);
    const back = [ax - Math.cos(angle) * 9, ay - Math.sin(angle) * 9];
    const corner = (turn) => [back[0] + Math.cos(angle + turn) * 4.5, back[1] + Math.sin(angle + turn) * 4.5];

    const group = g.append("g").attr("class", "compare-bubble");
    group.append("line")
        .attr("x1", at(0.62)[0]).attr("y1", at(0.62)[1]).attr("x2", back[0]).attr("y2", back[1])
        .attr("stroke", color).attr("stroke-width", 1.4);
    group.append("polygon")
        .attr("points", [[ax, ay], corner(Math.PI / 2), corner(-Math.PI / 2)].map((point) => point.join(",")).join(" "))
        .attr("fill", color);
    // The two puffs that make it a thought bubble rather than a speech balloon
    [[0.26, 4], [0.46, 2.5]].forEach(([t, r]) => {
        const [px, py] = at(t);
        group.append("circle").attr("cx", px).attr("cy", py).attr("r", r)
            .attr("fill", "#ffffff").attr("stroke", color).attr("stroke-width", 1.2);
    });
    group.append("circle").attr("cx", bx).attr("cy", by).attr("r", BUBBLE_R)
        .attr("fill", "#ffffff").attr("stroke", color).attr("stroke-width", 1.6);
    group.append("text").attr("class", "compare-bubble-mark")
        .attr("x", bx).attr("y", by).attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("fill", color).text("i");

    /* The sentences go to the readout under the plot rather than to a tooltip over it: they run to a few
       lines, and a floating panel would cover the very spot the bubble is pointing at. */
    group
        .on("mouseover", () => {
            group.classed("compare-bubble--hover", true);
            ctx.showNote?.({role, label: ctx.labels[role], text: [...sentences, aside].filter(Boolean).join(" ")});
        })
        .on("mouseout", () => {
            group.classed("compare-bubble--hover", false);
            ctx.showNote?.(null);
        });
}

/* A panel's title for one node, with its drift for the column and the null test's flag when it fired */
function driftPanelTitle(g, role, ctx, side) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    const next = titleChip(title, 0, role, `${ROLE_NAMES[role]} · ${ctx.labels[role]} · drift ${formatDrift(side.distortion?.value)}`);
    if (side.null?.flagged) {
        title.append("text").attr("x", next - 12).attr("fill", FLAG_COLOR).text("▲")
            .append("title").text(NULL_FLAG_TITLE);
    }
}

/* The column's shape in root, the baseline and the comparator: one row each on a shared axis. Every row is
   smoothed with the bandwidth fitted on root, and root is drawn dashed over every row - where the dashed
   line vanishes under the fill, nothing moved. The rows share one vertical scale too, so a node that lost
   rows draws a smaller curve rather than a renormalised one.

   ctx.range zooms the plot to part of the column, chosen on the overview strip beneath it. The vertical
   scale then fits the tallest curve inside the window rather than the column's, which is what makes a
   change in a thin tail visible - all three rows still share it, so they stay comparable. */
function drawRidgeline(svg, data, ctx) {
    const density = data.base.density ?? data.other.density;
    if (!density) return drawEmpty(svg, ctx, "This column has too few distinct values to draw its shape");

    const rows = [
        {key: "root", label: "root", curve: density.root, color: ROOT_COLOR, drift: 0},
        {
            key: "base", label: ctx.labels.base, curve: data.base.density?.node, color: ROLE_COLORS.base,
            drift: data.base.distortion?.value, flag: data.base.null
        },
        {
            key: "other", label: ctx.labels.other, curve: data.other.density?.node, color: ROLE_COLORS.other,
            drift: data.other.distortion?.value, flag: data.other.null
        },
    ];

    const [{g, w, h}] = layoutPanels(svg, ctx.width - DRIFT_GUTTER, ctx.height, 1);
    const grid = density.grid;
    const [lo, hi] = ctx.range ?? [grid[0], grid[grid.length - 1]];
    const x = d3.scaleLinear().domain([lo, hi]).range([0, w]);
    const band = d3.scaleBand().domain(rows.map((row) => row.key)).range([0, h]).paddingInner(0.12);

    // The grid points inside the window, and one either side so each curve runs to the window's edges
    const visible = d3.range(Math.max(0, d3.bisectLeft(grid, lo) - 1), Math.min(grid.length, d3.bisectRight(grid, hi) + 1));
    const peak = d3.max(rows.flatMap((row) => (row.curve ? visible.map((i) => row.curve[i]) : []))) || 1;
    const rise = (value) => (value / peak) * band.bandwidth();

    // The points either side of the window would otherwise draw into the margins
    const clip = `url(#${ctx.clipId})`;
    g.append("clipPath").attr("id", ctx.clipId).append("rect").attr("width", w).attr("height", h);

    rows.forEach((row) => {
        const floor = band(row.key) + band.bandwidth();
        const middle = floor - band.bandwidth() / 2;
        const rowGroup = g.append("g");

        rowGroup.append("line").attr("class", "compare-ridge-floor").attr("x1", 0).attr("x2", w).attr("y1", floor).attr("y2", floor);
        if (row.curve) {
            rowGroup.append("path").datum(visible)
                .attr("d", d3.area().x((i) => x(grid[i])).y0(floor).y1((i) => floor - rise(row.curve[i])))
                .attr("clip-path", clip)
                .attr("fill", row.color).attr("fill-opacity", 0.5)
                .attr("stroke", row.color).attr("stroke-width", 1.2);
        }
        rowGroup.append("path").datum(visible)
            .attr("d", d3.line().x((i) => x(grid[i])).y((i) => floor - rise(density.root[i])))
            .attr("clip-path", clip)
            .attr("class", "compare-ridge-root");

        rowGroup.append("text").attr("class", "compare-ridge-label")
            .attr("x", -8).attr("y", middle).attr("text-anchor", "end").attr("dominant-baseline", "middle")
            .attr("fill", row.color).text(row.label);
        const drift = rowGroup.append("text").attr("class", "compare-ridge-drift")
            .attr("x", w + 10).attr("y", middle).attr("dominant-baseline", "middle").text(formatDrift(row.drift));
        if (row.flag?.flagged) drift.append("tspan").attr("fill", FLAG_COLOR).text(" ▲").append("title").text(NULL_FLAG_TITLE);

        /* Root is the reference, so only the nodes measured against it carry an annotation. The spot is found
           on the whole curve, zoomed or not; when the window leaves it out, the bubble is pinned to the edge
           of the row nearest it, pointing off the plot. The arrow meets whichever curve is higher there - root's
           dashed line where rows were removed, the node's own where values were filled in. */
        if (row.key !== "root" && row.curve) {
            const spot = mostChanged(density.root, row.curve);
            const at = grid[spot];
            const shown = at >= lo && at <= hi;
            drawAnnotationBubble(rowGroup, {
                ax: shown ? x(at) : (at < lo ? 0 : w),
                ay: shown ? floor - rise(Math.max(row.curve[spot], density.root[spot])) : middle,
                bounds: {left: 0, right: w, top: band(row.key), bottom: floor},
                aside: shown ? null : `(That spot, near ${formatValue(at)}, is ${at < lo ? "left" : "right"} of the range shown.)`,
            }, row.key, data[row.key], ctx);
        }
    });

    g.append("text").attr("class", "compare-axis-label").attr("x", w + 10).attr("y", -14).text("drift");
    g.append("g").attr("class", "compare-axis").attr("transform", `translate(0, ${h})`)
        .call(d3.axisBottom(x).ticks(6).tickFormat(d3.format(".3~s"))).selectAll("text").attr("class", "bottom-axis-text");
    axisLabels(g, w, h, ctx.range ? `${data.x} · zoomed to ${formatValue(lo)} – ${formatValue(hi)}` : data.x, null);
}

/* Where the ridgeline's panel sits in a canvas this wide - the same panel layoutPanels gives drawRidgeline,
   so the overview strip beneath lines up with it exactly */
function ridgelineFrame(width) {
    return {left: MARGIN.left, width: Math.max(10, width - DRIFT_GUTTER - MARGIN.left - MARGIN.right), total: width};
}

/* What the overview strip draws for a drift result: the whole column's curves, and the spots the bubbles
   point at. Null for anything the ridgeline does not draw. */
function ridgelineOverview(data) {
    const density = data?.kind === "drift" ? (data.base.density ?? data.other.density) : null;
    if (!density) return null;
    const curves = {base: data.base.density?.node ?? null, other: data.other.density?.node ?? null};
    const spots = {
        base: curves.base && mostChanged(density.root, curves.base),
        other: curves.other && mostChanged(density.root, curves.other),
    };
    return {density, curves, spots};
}

/* One Sankey: root's categories on the left, the node's on the right plus the deleted rows' sink.
   Ribbons are always square-root width: at true width a category holding a handful of rows is a hairline,
   and these columns usually hold most of their mass in one category. The trade is that a ribbon's width no
   longer reads as its count, so every node carries its count as a label.

   Returns where the panel's annotation should point: the biggest ribbon that actually moved - recoded or
   removed - or failing that the biggest ribbon of all, so a column where nothing moved can still say so. */
function drawSankey(g, flows, w, h, ctx) {
    const widthOf = Math.sqrt;
    const LABEL = Math.min(120, w * 0.3);
    const NODE = 10;
    const PAD = 6;

    const ribbons = flows.flows.map((flow) => ({...flow, size: widthOf(flow.rows)}));
    const total = d3.sum(ribbons, (ribbon) => ribbon.size) || 1;
    const column = (labels, key) => labels.map((label) => ({
        label,
        size: d3.sum(ribbons.filter((ribbon) => ribbon[key] === label), (ribbon) => ribbon.size),
        rows: d3.sum(ribbons.filter((ribbon) => ribbon[key] === label), (ribbon) => ribbon.rows),
    }));
    const left = column(flows.sources, "source");
    const right = column(flows.targets, "target");
    const scale = (h - PAD * (Math.max(left.length, right.length) - 1)) / total;

    // Stack a column's nodes top to bottom, centred in the panel
    const stack = (nodes) => {
        let y = 0;
        nodes.forEach((node) => {
            node.y0 = y;
            node.y1 = y + node.size * scale;
            y = node.y1 + PAD;
        });
        const offset = (h - (y - PAD)) / 2;
        nodes.forEach((node) => {
            node.y0 += offset;
            node.y1 += offset;
        });
        return Object.fromEntries(nodes.map((node) => [node.label, node]));
    };
    const sources = stack(left);
    const targets = stack(right);
    const x0 = LABEL + NODE;
    const x1 = w - LABEL - NODE;

    /* Ribbons leave each source in target order and arrive at each target in source order, which keeps
       them from crossing more than the flows themselves require */
    const sourceOrder = new Map(flows.sources.map((label, i) => [label, i]));
    const targetOrder = new Map(flows.targets.map((label, i) => [label, i]));
    const leftCursor = Object.fromEntries(left.map((node) => [node.label, node.y0]));
    const rightCursor = Object.fromEntries(right.map((node) => [node.label, node.y0]));
    const placed = [...ribbons]
        .sort((a, b) => (sourceOrder.get(a.source) - sourceOrder.get(b.source))
            || (targetOrder.get(a.target) - targetOrder.get(b.target)))
        .map((ribbon) => {
            const thickness = ribbon.size * scale;
            const placedRibbon = {...ribbon, thickness, ya: leftCursor[ribbon.source], yb: rightCursor[ribbon.target]};
            leftCursor[ribbon.source] += thickness;
            rightCursor[ribbon.target] += thickness;
            return placedRibbon;
        });

    const middle = (x0 + x1) / 2;
    const path = (r) => `M${x0},${r.ya} C${middle},${r.ya} ${middle},${r.yb} ${x1},${r.yb} `
        + `L${x1},${r.yb + r.thickness} C${middle},${r.yb + r.thickness} ${middle},${r.ya + r.thickness} ${x0},${r.ya + r.thickness} Z`;
    const kindOf = (r) => (r.target === REMOVED_LABEL ? "removed" : r.target === r.source ? "stayed" : "recoded");

    const paths = g.append("g").selectAll("path").data(placed).join("path")
        .attr("class", "compare-mark")
        .attr("d", path)
        .attr("fill", (r) => FLOW_COLORS[kindOf(r)])
        .attr("fill-opacity", (r) => (kindOf(r) === "stayed" ? 0.35 : 0.7));
    ctx.tooltip.attach(paths, (r) => `<strong>${escapeHtml(r.source)} → ${escapeHtml(r.target)}</strong><br>`
        + `${formatCount(r.rows)} rows · ${formatShare(r.rows / (sources[r.source]?.rows || 1))} of ${escapeHtml(r.source)}`);

    const drawColumn = (nodes, x, anchor, labelX) => {
        const group = g.append("g");
        Object.values(nodes).forEach((node) => {
            const removed = node.label === REMOVED_LABEL;
            group.append("rect").attr("x", x).attr("y", node.y0).attr("width", NODE)
                .attr("height", Math.max(1, node.y1 - node.y0))
                .attr("fill", removed ? FLOW_COLORS.removed : "#475569");
            const centre = (node.y0 + node.y1) / 2;
            const text = group.append("text").attr("class", "compare-flow-label")
                .attr("x", labelX).attr("y", centre).attr("text-anchor", anchor).attr("dominant-baseline", "middle")
                .classed("compare-flow-label--removed", removed);
            text.append("tspan").text(node.label.length > 16 ? `${node.label.slice(0, 16)}…` : node.label)
                .append("title").text(node.label);
            text.append("tspan").attr("class", "compare-flow-count").text(` ${formatCount(node.rows)}`);
        });
    };
    drawColumn(sources, x0 - NODE, "end", x0 - NODE - 6);
    drawColumn(targets, x1, "start", x1 + NODE + 6);

    const moved = placed.filter((ribbon) => kindOf(ribbon) !== "stayed");
    const marked = d3.greatest(moved.length ? moved : placed, (ribbon) => ribbon.rows);
    return marked ? {ax: middle, ay: (marked.ya + marked.yb + marked.thickness) / 2} : null;
}

/* Where root's rows went in this column, for each node: into the same category, into another, or out of
   the table. This is churn's picture rather than TVD's - rows swapping between two categories are ribbons
   here while leaving the shares, and so the drift number, unchanged - so both numbers sit beneath it. */
function drawFlows(svg, data, ctx) {
    layoutPanels(svg, ctx.width, ctx.height, 2).forEach(({g, w, h}, i) => {
        const role = i === 0 ? "base" : "other";
        const side = data[role];
        driftPanelTitle(g, role, ctx, side);
        if (!side.flows) return;

        const anchor = drawSankey(g, side.flows, w, h, ctx);
        if (anchor) {
            drawAnnotationBubble(g, {...anchor, bounds: {left: 0, right: w, top: 0, bottom: h}}, role, side, ctx);
        }

        g.append("text").attr("class", "compare-axis-label")
            .attr("x", w / 2).attr("y", h + 28).attr("text-anchor", "middle")
            .text(`churn ${formatShare(side.flows.churn)} of rows · TVD ${formatDrift(side.distortion?.value)}`);
    });
}

const DRAWERS = {
    histogram: {side: drawHistogramSide, overlay: drawHistogramOverlay, difference: drawHistogramDifference},
    heatmap: {side: drawHeatmapSide, difference: drawHeatmapDifference},
    drift: {ridgeline: drawRidgeline, flows: drawFlows},
};

function isEmpty(data) {
    // A categorical column is drawn as its flows, a numeric one as its curves
    if (data.kind === "drift") {
        const drawable = (side) => (side?.kind === "categorical" ? side?.flows : side?.density);
        return !drawable(data.base) && !drawable(data.other);
    }
    const marks = data.kind === "histogram" ? data.bins : data.tiles;
    return !marks?.length;
}

function drawEmpty(svg, {width, height}, message = "Neither node has rows to plot for this selection") {
    svg.append("text").attr("class", "compare-empty")
        .attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
        .text(message);
}

// ── Legend ───────────────────────────────────────────────────────────────────

function legendItems(kind, view, measure, labels) {
    const roleLabel = (role) => `${ROLE_NAMES[role]} · ${labels[role]}`;

    if (kind === "drift") {
        if (view === "flows") {
            return [
                {label: "Stayed in its category", style: {background: FLOW_COLORS.stayed}},
                {label: "Recoded into another", style: {background: FLOW_COLORS.recoded}},
                {label: "Row removed", style: {background: FLOW_COLORS.removed}},
            ];
        }
        return [
            {label: "Root", style: {background: ROOT_COLOR}},
            ...["base", "other"].map((role) => ({label: roleLabel(role), style: {background: ROLE_COLORS[role]}})),
            {
                label: "Root's shape, dashed on every row", shape: "line",
                style: {background: "repeating-linear-gradient(to right, #1c1e21 0 4px, transparent 4px 7px)"}
            },
        ];
    }
    const errorItems = [
        ...ERROR_DIMENSIONS.map((type) => ({label: MEASURES[type].label, style: {background: errorColors(type)}})),
        {label: "No errors", style: {background: errorColors("none")}},
    ];

    if (view === "difference") {
        const {fewer, more} = differenceColors(measure);
        const noun = MEASURES[measure].noun;
        const [better, worse] = measure === "items" ? ["", ""] : [" (better)", " (worse)"];
        return [
            {label: `Fewer ${noun} in the comparator${better}`, style: {background: fewer}},
            {label: `More ${noun} in the comparator${worse}`, style: {background: more}},
        ];
    }

    if (kind === "heatmap") {
        const fill = sequentialColor(measure, 1);
        const items = [{
            label: `Darker tiles hold more ${MEASURES[measure].noun}`,
            shape: "ramp",
            style: {background: `linear-gradient(to right, ${fill(0.01)}, ${fill(1)})`},
        }];
        if (measure !== "items") items.push({label: "Rows, none flagged", style: {background: NEUTRAL}});
        return items;
    }

    if (kind === "histogram" && view === "overlay") {
        return ["base", "other"].map((role) => ({label: roleLabel(role), style: {background: ROLE_COLORS[role]}}));
    }

    return errorItems;
}

/**
 * The compare modal's plot.
 *
 * Props:
 *  - data: a /api/pgraph/compare response, or null while there is none to show
 *  - view: "side" | "overlay" | "difference", or for drift "ridgeline" | "flows" -
 *    which the kind supports is the modal's call
 *  - measure: a MEASURES key, read by difference views and heatmaps
 *  - baseLabel, otherLabel: short names for the two nodes
 */
export default function ComparisonPlot({data, view, measure, baseLabel, otherLabel}) {
    const canvasRef = useRef(null);
    const svgRef = useRef(null);
    const tooltipRef = useRef(null);
    const [size, setSize] = useState({width: 0, height: 0});
    // What the hovered annotation bubble says, shown under the plot rather than over it
    const [note, setNote] = useState(null);

    /* The part of the column a zoomed ridgeline shows, stamped with the column and nodes it was chosen for.
       Another column or node pair reads it as unzoomed, so a stale zoom lapses without an effect to reset it. */
    const zoomKey = data?.kind === "drift" ? `${data.x}|${data.base.node}|${data.other.node}` : null;
    const [zoom, setZoom] = useState({key: null, range: null});
    const range = zoom.key === zoomKey ? zoom.range : null;
    // The brush reports on every move, often the same range; only a new one is worth a redraw
    const zoomTo = useCallback((next) => setZoom((previous) => (
        previous.key === zoomKey && String(previous.range) === String(next) ? previous : {key: zoomKey, range: next}
    )), [zoomKey]);

    // Ids are unique per page, and useId's own characters are not all safe in a url(#...) reference
    const clipId = `compare-ridge-clip${useId().replace(/[^\w-]/g, "")}`;
    const overview = useMemo(() => ridgelineOverview(data), [data]);
    // While the next column loads, the last one's drift result stays up - but only under a view for its kind
    const stale = data?.kind === "drift" && (data.base.kind ?? data.other.kind) !== DRIFT_VIEW_KINDS[view];

    // The canvas takes whatever room the modal gives it, and the plot is laid out from that
    useEffect(() => {
        const observer = new ResizeObserver(([entry]) => {
            setSize({width: entry.contentRect.width, height: entry.contentRect.height});
        });
        observer.observe(canvasRef.current);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        const svg = d3.select(svgRef.current);
        const draw = data && DRAWERS[data.kind]?.[view];
        if (!draw || stale || size.width < MIN_CANVAS || size.height < MIN_CANVAS) return;

        const tooltip = makeTooltip(tooltipRef.current, canvasRef.current);
        if (isEmpty(data)) {
            drawEmpty(svg, size);
        } else {
            draw(svg, data, {
                ...size, measure, tooltip, range, clipId, showNote: setNote,
                labels: {base: baseLabel, other: otherLabel},
            });
        }

        return () => {
            tooltip.hide();
            setNote(null);
            svg.selectAll("*").remove();
        };
    }, [data, view, measure, baseLabel, otherLabel, size, stale, range, clipId]);

    return (
        <div className="compare-plot-frame">
            <div ref={canvasRef} className="compare-plot-canvas">
                <svg ref={svgRef} width={size.width} height={size.height}/>
                <div ref={tooltipRef} className="compare-tooltip"/>
            </div>
            {view === "ridgeline" && overview && !stale && size.width >= MIN_CANVAS && (
                // Keyed on the column and nodes, so a new pair starts with a fresh brush rather than the last box
                <RidgelineBrush
                    key={zoomKey}
                    {...overview}
                    frame={ridgelineFrame(size.width)}
                    rootColor={ROOT_COLOR}
                    range={range}
                    onRange={zoomTo}
                />
            )}
            {data?.kind === "drift" && (
                <div className="compare-note" aria-live="polite">
                    {note ? (
                        <>
                            <span className="compare-note-role" style={{color: ROLE_COLORS[note.role]}}>
                                {ROLE_NAMES[note.role]} · {note.label}
                            </span>
                            {note.text}
                        </>
                    ) : (
                        <span className="compare-note-hint">Hover a bubble for what changed where it points.</span>
                    )}
                </div>
            )}
            {data && (
                <div className="compare-legend">
                    {legendItems(data.kind, view, measure, {base: baseLabel, other: otherLabel}).map((item) => (
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
        </div>
    );
}
