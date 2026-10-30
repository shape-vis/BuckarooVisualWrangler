// compare/binnedViews.js
// The compare panel's histograms and heatmaps: the two nodes side by side, overlaid, or as their difference.

import * as d3 from "d3";
import {errorColors} from "../../store/errorColors.js";
import {MEASURES, ROLE_COLORS, measureOf} from "../../utils/comparison.js";
import {
    GREEN, NEUTRAL_FILL, RED, binLabel, binScale, divergingFill, formatDelta, spanX, spanY, stackSegments,
} from "../binnedPlot.js";
import {axisLabels, drawCountAxis, drawXAxis, drawYAxis, layoutPanels, pairTitle, panelTitle} from "./frames.js";
import {countsTooltip, differenceTooltip} from "./tooltip.js";

/* A difference is colored by what it means. Rows gained or lost are neither good nor bad, so they get
   a neutral pair; errors going down is an improvement, and gets the attribute panel's green. */
const DIFFERENCE_COLORS = {
    rows: {fewer: "#7c4dff", more: "#e8710a"},
    errors: {fewer: GREEN, more: RED},
};

// A changed tile starts this far toward its colour, so a small change still reads
const DIFFERENCE_FLOOR = 0.25;

export function differenceColors(measure) {
    if (measure === "items") return DIFFERENCE_COLORS.rows;
    return DIFFERENCE_COLORS.errors;
}

// The ramps for rows and for all errors together; a single error type ramps up to its own colour instead
const SEQUENTIAL_RAMPS = {
    items: (t) => d3.interpolateBlues(0.15 + 0.85 * t),
    errors: (t) => d3.interpolateOrRd(0.15 + 0.85 * t),
};

const errorTypeRamp = (measure) => (t) => d3.interpolateRgb("#f3f3f3", errorColors(measure))(0.2 + 0.8 * t);

/* Darker means more of the measure. Zero gets NEUTRAL_FILL rather than the ramp's pale end, so a tile whose
   rows carry no flags still reads as occupied. */
export function sequentialColor(measure, peak) {
    const ramp = SEQUENTIAL_RAMPS[measure] ?? errorTypeRamp(measure);
    return (value) => {
        if (value > 0) return ramp(Math.min(1, value / peak));
        return NEUTRAL_FILL;
    };
}

function divergingColor(measure, extent) {
    const {fewer, more} = differenceColors(measure);
    return (delta) => divergingFill(delta, extent, {fewer, more, floor: DIFFERENCE_FLOOR});
}

const tileLabel = (data, tile) => `${data.x}: ${binLabel(data.scaleX, tile.xType, tile.xBin)} · `
    + `${data.y}: ${binLabel(data.scaleY, tile.yType, tile.yBin)}`;

// ── Histograms ───────────────────────────────────────────────────────────────

export function drawHistogramSide(svg, data, ctx) {
    // One y domain for both panels, or bars of equal height would not be equal counts
    const peak = d3.max(data.bins, (bin) => Math.max(...ctx.roles.map((role) => bin[role].items))) || 1;

    layoutPanels(svg, ctx.width, ctx.height, ctx.roles.length).forEach(({g, w, h}, i) => {
        const role = ctx.roles[i];
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
            .attr("stroke-width", 0.5)
            // For the end-to-end tests: whose bar this is, which bin, and how many rows the bin holds on that side
            .attr("data-role", role)
            .attr("data-bin", (d) => String(d.bin.xBin))
            .attr("data-bin-type", (d) => d.bin.xType)
            .attr("data-segment", (d) => d.type)
            .attr("data-bin-items", (d) => d.bin[role].items);
        ctx.tooltip.attach(bars, (d) => countsTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

        drawXAxis(g, xScale, w, h);
        drawCountAxis(g, y);
        panelTitle(g, role, ctx);
        axisLabels(g, w, h, data.x, i === 0 ? "Rows" : null);
    });
}

export function drawHistogramOverlay(svg, data, ctx) {
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const peak = d3.max(data.bins, (bin) => Math.max(bin.a.items, bin.b.items)) || 1;
    const y = d3.scaleLinear().domain([0, peak]).nice().range([h, 0]);

    // Each bin is split down the middle: selection A's bar on the left, selection B's on the right
    const bars = data.bins.flatMap((bin) => [{bin, role: "a"}, {bin, role: "b"}]);
    const marks = g.append("g").selectAll("rect").data(bars).join("rect")
        .attr("class", "compare-mark")
        .attr("x", (d) => {
            const span = spanX(xScale, data.scaleX, d.bin);
            return span.x + (d.role === "a" ? 1 : span.w / 2);
        })
        .attr("width", (d) => Math.max(0, spanX(xScale, data.scaleX, d.bin).w / 2 - 1))
        .attr("y", (d) => y(d.bin[d.role].items))
        .attr("height", (d) => Math.max(0, h - y(d.bin[d.role].items)))
        .attr("fill", (d) => ROLE_COLORS[d.role])
        .attr("fill-opacity", 0.85)
        // For the end-to-end tests, as the side-by-side bars carry them
        .attr("data-role", (d) => d.role)
        .attr("data-bin", (d) => String(d.bin.xBin))
        .attr("data-bin-type", (d) => d.bin.xType)
        .attr("data-bin-items", (d) => d.bin[d.role].items);
    ctx.tooltip.attach(marks, (d) => countsTooltip(binLabel(data.scaleX, d.bin.xType, d.bin.xBin), d.bin, ctx));

    drawXAxis(g, xScale, w, h);
    drawCountAxis(g, y);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, "Rows");
}

export function drawHistogramDifference(svg, data, ctx) {
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const deltas = data.bins.map((bin) => ({
        bin,
        delta: measureOf(bin.b, ctx.measure) - measureOf(bin.a, ctx.measure),
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

export function drawHeatmapSide(svg, data, ctx) {
    // One color scale for both panels, so equal shades are equal counts
    const peak = d3.max(data.tiles, (tile) => Math.max(
        ...ctx.roles.map((role) => measureOf(tile[role], ctx.measure)))) || 1;
    const fill = sequentialColor(ctx.measure, peak);

    layoutPanels(svg, ctx.width, ctx.height, ctx.roles.length).forEach(({g, w, h}, i) => {
        const role = ctx.roles[i];
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

export function drawHeatmapDifference(svg, data, ctx) {
    const [{g, w, h}] = layoutPanels(svg, ctx.width, ctx.height, 1);
    const xScale = binScale(data.scaleX, w, "horizontal");
    const yScale = binScale(data.scaleY, h, "vertical");
    const delta = (tile) => measureOf(tile.b, ctx.measure) - measureOf(tile.a, ctx.measure);
    const extent = d3.max(data.tiles, (tile) => Math.abs(delta(tile))) || 1;
    const fill = divergingColor(ctx.measure, extent);

    const tiles = drawTiles(g, data, xScale, yScale, data.tiles).attr("fill", (tile) => fill(delta(tile)));
    ctx.tooltip.attach(tiles, (tile) => differenceTooltip(tileLabel(data, tile), tile, ctx));

    drawXAxis(g, xScale, w, h);
    drawYAxis(g, yScale);
    pairTitle(g, ctx);
    axisLabels(g, w, h, data.x, data.y);
}
