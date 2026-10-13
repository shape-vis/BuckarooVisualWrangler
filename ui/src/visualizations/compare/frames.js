// compare/frames.js
// The frame every compare view draws inside: its panels laid out across the canvas, their titles, axes and axis
// labels, and the message a view draws when it has nothing to plot.

import * as d3 from "d3";
import {ROLE_COLORS, ROLE_NAMES} from "../../utils/comparison.js";
import {drawXAxisOnFloor, formatCount} from "../binnedPlot.js";
import {roleName} from "./tooltip.js";

export const MARGIN = {top: 34, right: 18, bottom: 72, left: 76};
const PANEL_GAP = 28;

/* Split the canvas into side-by-side plot areas, each with room for its own axes. */
export function layoutPanels(svg, width, height, count) {
    const slot = (width - PANEL_GAP * (count - 1)) / count;
    return d3.range(count).map((i) => ({
        g: svg.append("g").attr("transform", `translate(${i * (slot + PANEL_GAP) + MARGIN.left}, ${MARGIN.top})`),
        w: Math.max(10, slot - MARGIN.left - MARGIN.right),
        h: Math.max(10, height - MARGIN.top - MARGIN.bottom),
    }));
}

// Draws one colored chip and its label, returning where the next one can start
export function titleChip(title, x, role, text) {
    title.append("rect")
        .attr("x", x).attr("y", -9).attr("width", 10).attr("height", 10).attr("rx", 2)
        .attr("fill", ROLE_COLORS[role]);
    const label = title.append("text").attr("x", x + 16).text(text);
    return x + 16 + label.node().getComputedTextLength() + 18;
}

export function panelTitle(g, role, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    titleChip(title, 0, role, roleName(role, ctx));
}

export function pairTitle(g, ctx) {
    const title = g.append("g").attr("class", "compare-panel-title").attr("transform", "translate(0, -14)");
    const next = titleChip(title, 0, "a", `${ROLE_NAMES.a} · ${ctx.labels.a}`);
    titleChip(title, next, "b", `${ROLE_NAMES.b} · ${ctx.labels.b}`);
}

// These panels are not square, so the x axis is moved down onto the panel's floor
export function drawXAxis(g, xScale, w, h) {
    drawXAxisOnFloor(g.append("g").attr("class", "compare-axis"), xScale, w, h);
}

export function drawYAxis(g, yScale) {
    yScale.draw(g.append("g").attr("class", "compare-axis"));
}

export function drawCountAxis(g, y, format = formatCount) {
    g.append("g").attr("class", "compare-axis")
        .call(d3.axisLeft(y).ticks(5).tickFormat(format))
        .selectAll("text").attr("class", "left-axis-text");
}

export function axisLabels(g, w, h, xLabel, yLabel) {
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

export function drawEmpty(svg, {width, height}, message = "Neither node has rows to plot for this selection") {
    svg.append("text").attr("class", "compare-empty")
        .attr("x", width / 2).attr("y", height / 2).attr("text-anchor", "middle")
        .text(message);
}
