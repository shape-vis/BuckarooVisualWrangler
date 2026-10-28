// binnedPlot.js
// What the two charts of /api/pgraph/compare's binned data share - the compare panel's histograms and heatmaps,
// and the wrangle diff beside an edge: its scales, where a bin falls on them, how a bin and a count read, and the
// colours of a change. The binning itself is app/db_utils/compare_sql.py's.

import * as d3 from "d3";
import { createHybridScales } from "../utils/visCommon.jsx";
import { ERROR_DIMENSIONS } from "../store/errorColors.js";

// A tile that exists but did not change, or measures zero - distinct from the white of no data at all
export const NEUTRAL_FILL = "#eef0f2";
// The two ends of a change: green for fewer errors or rows gained, red for more errors or rows lost
export const GREEN = "#1a7f37";
export const RED = "#c1121f";

export const formatCount = d3.format(",");

export function formatDelta(value) {
    if (value > 0) return `+${formatCount(value)}`;
    return formatCount(value);
}

export function formatValue(value) {
    if (Math.abs(value) >= 1e4) return d3.format(".3~s")(value);
    return d3.format(".4~g")(value);
}

/* The shared hybrid scale, fed the shape the backend sends for binned axes: numeric bin edges, then
   categorical labels. */
export function binScale(scale, size, direction) {
    const numeric = scale.numeric ?? [];
    const categorical = scale.categorical ?? [];
    const numericDomain = numeric.length ? [numeric[0].x0, numeric[numeric.length - 1].x1] : null;
    const categoricalDomain = categorical.length ? categorical : null;
    return createHybridScales(size, numeric, categorical, numericDomain, categoricalDomain, direction);
}

export function spanX(xScale, scale, datum) {
    if (datum.xType === "numeric") {
        const {x0, x1} = scale.numeric[datum.xBin];
        return {x: xScale.apply(x0, "numeric"), w: xScale.numericalBandwidth(x0, x1)};
    }
    return {x: xScale.apply(datum.xBin, "categorical"), w: xScale.categoricalBandwidth()};
}

// The vertical scale runs bottom to top, so a numeric bin's top edge is its x1
export function spanY(yScale, scale, datum) {
    if (datum.yType === "numeric") {
        const {x0, x1} = scale.numeric[datum.yBin];
        return {y: yScale.apply(x1, "numeric"), h: yScale.numericalBandwidth(x1, x0)};
    }
    return {y: yScale.apply(datum.yBin, "categorical"), h: yScale.categoricalBandwidth()};
}

export function binLabel(scale, type, bin) {
    if (type !== "numeric") return String(bin);
    const {x0, x1} = scale.numeric[bin];
    return `${formatValue(x0)} – ${formatValue(x1)}`;
}

/* createHybridScales draws its x axis at y = size, which assumes a square plot. A plot that is not square gets
   the axis in a group shifted by the difference, landing it on the plot's floor. */
export function drawXAxisOnFloor(axisGroup, xScale, width, height) {
    xScale.draw(axisGroup.attr("transform", `translate(0, ${height - width})`));
}

/* One bar's stack: error flags from the top down, clean rows beneath - the preview's and main histograms' order */
export function stackSegments(count) {
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

/* A change's colour, stronger for a bigger change: from NEUTRAL_FILL toward fewer's colour or more's, starting
   at floor so a small change still reads. No change at all is NEUTRAL_FILL itself. */
export function divergingFill(delta, extent, {fewer, more, floor}) {
    if (delta === 0) return NEUTRAL_FILL;
    const toward = delta > 0 ? more : fewer;
    const strength = Math.min(1, Math.abs(delta) / extent);
    return d3.interpolateRgb(NEUTRAL_FILL, toward)(floor + (1 - floor) * strength);
}
