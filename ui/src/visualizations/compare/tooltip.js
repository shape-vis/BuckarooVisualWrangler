// compare/tooltip.js
// The compare plot's own tooltip, and the text the views put in it.

import * as d3 from "d3";
import {ERROR_DIMENSIONS} from "../../store/errorColors.js";
import {MEASURES, ROLE_COLORS, ROLE_NAMES, measureOf} from "../../utils/comparison.js";
import {escapeHtml} from "../../utils/html.js";
import {formatCount, formatDelta} from "../binnedPlot.js";

const TOOLTIP_GAP = 12;

/* The panel can be in a window of its own, out of reach of the app's shared #tooltip, so the plot keeps its own. It is placed within the
   canvas, and flips away from whichever edge it would run off. */
export function makeTooltip(element, container) {
    const place = (event) => {
        /* In the canvas's own pixels. A plot drawn in a graph sub-node sits under the graph's zoom, a CSS scale,
           so the pointer's screen offset is scaled back first - in the compare window the scale is 1. */
        const bounds = container.getBoundingClientRect();
        const scale = bounds.width / (container.offsetWidth || bounds.width) || 1;
        const x = (event.clientX - bounds.left) / scale;
        const y = (event.clientY - bounds.top) / scale;
        const {offsetWidth: width, offsetHeight: height} = element;
        const room = {width: container.offsetWidth, height: container.offsetHeight};
        const left = x + TOOLTIP_GAP + width > room.width ? x - TOOLTIP_GAP - width : x + TOOLTIP_GAP;
        const top = y + TOOLTIP_GAP + height > room.height ? y - TOOLTIP_GAP - height : y + TOOLTIP_GAP;
        element.style.left = `${Math.max(0, left)}px`;
        element.style.top = `${Math.max(0, top)}px`;
    };
    const hide = () => {
        element.style.display = "none";
    };
    // For content that follows the pointer, as a crosshair's does, as well as for one mark's fixed text
    const show = (event, html) => {
        element.innerHTML = html;
        element.style.display = "block";
        place(event);
    };

    return {
        hide,
        show,
        attach(selection, html) {
            selection
                .on("mouseover", (event, d) => {
                    show(event, html(d));
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

export const swatch = (color) => `<span class="compare-tooltip-swatch" style="background:${color}"></span>`;

/* What a side is called: its selection and its node, or just the node when it is the only one drawn */
export function roleName(role, ctx, separator = " · ") {
    return ctx.roles.length > 1 ? `${ROLE_NAMES[role]}${separator}${ctx.labels[role]}` : ctx.labels[role];
}

function countLine(role, ctx, count) {
    const flags = ERROR_DIMENSIONS
        .filter((type) => count?.[type])
        .map((type) => `${formatCount(count[type])} ${MEASURES[type].noun}`);
    let flagNote = "";
    if (flags.length) flagNote = ` (${flags.join(", ")})`;
    return `${swatch(ROLE_COLORS[role])}${escapeHtml(roleName(role, ctx, " "))}: `
        + `<strong>${formatCount(count?.items ?? 0)}</strong> rows${flagNote}`;
}

export function countsTooltip(title, datum, ctx) {
    return `<strong>${escapeHtml(title)}</strong><br>`
        + ctx.roles.map((role) => countLine(role, ctx, datum[role])).join("<br>");
}

export function differenceTooltip(title, datum, ctx) {
    const before = measureOf(datum.a, ctx.measure);
    const after = measureOf(datum.b, ctx.measure);
    return `<strong>${escapeHtml(title)}</strong><br>`
        + `${MEASURES[ctx.measure].label}: ${formatCount(before)} → ${formatCount(after)} `
        + `(<strong>${formatDelta(after - before)}</strong>)<br>`
        + `${countLine("a", ctx, datum.a)}<br>${countLine("b", ctx, datum.b)}`;
}
