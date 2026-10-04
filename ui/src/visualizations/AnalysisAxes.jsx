// AnalysisAxes.jsx
// The chart axes laid over the provenance graph in analysis mode. Drawn in screen space from React Flow's
// pan and zoom, as a zoomable chart's axes are, so the ticks stay crisp and readable at any zoom and always
// cover what is in view. Gridlines sit behind the nodes, where React Flow's own background would; the axes
// are strips pinned to the canvas's left and bottom edges, over the nodes, so the numbers are never hidden.

import * as d3 from "d3";
import { useStore, useViewport } from "@xyflow/react";
import {
    AXIS_BOTTOM as BOTTOM, AXIS_LABEL_GAP, AXIS_TICK as TICK, AXIS_TITLE_ROOM, METRIC_LABELS, TITLE_FONT,
    axisLeftFor, errorTickCount, errorTicks, metricTitle, textWidth,
} from "./analysisLayout.js";

/* The part of a scale's domain in view: the visible screen span read back into data values, kept inside the
   axis's own range - a drift or an error rate below zero means nothing. Null when none of it is in view. */
function visibleSpan(screen, [from, to]) {
    const [lo, hi] = screen.domain();
    const a = Math.max(lo, Math.min(screen.invert(from), screen.invert(to)));
    const b = Math.min(hi, Math.max(screen.invert(from), screen.invert(to)));
    return b > a ? [a, b] : null;
}

// The drift axis's ticks over a span, at the precision the step between them needs
function driftTicks([a, b], count) {
    const values = d3.ticks(a, b, count);
    const step = values.length > 1 ? values[1] - values[0] : b - a;
    const format = d3.format(`.${Math.max(0, d3.precisionFixed(step))}f`);
    return values.map((value) => ({ value, label: format(value) }));
}

/**
 * Props:
 *  - scales: {x, y, axisLeft} from analysisScales - drift and error in the canvas's own units, and how wide
 *    the y axis's strip is for the plot's own labels
 *  - metric: which error the y axis shows, for its title
 */
export default function AnalysisAxes({ scales, metric }) {
    const { x: panX, y: panY, zoom } = useViewport();
    const width = useStore((state) => state.width);
    const height = useStore((state) => state.height);
    if (!width || !height) return null;

    // The plot's scales carried through the pan and zoom onto the screen
    const toScreen = (scale, pan) => scale.copy().range(scale.range().map((value) => value * zoom + pan));
    const x = toScreen(scales.x, panX);
    const y = toScreen(scales.y, panY);

    /* The error ticks come first, since the strip's width follows from their labels: as wide as the plot's own
       labels need, and wider still when zooming in brings finer ones. The title keeps a column of its own at
       the strip's left edge, so a long label never runs into it. */
    const ySpan = visibleSpan(y, [0, height - BOTTOM]);
    const yTicks = (ySpan ? errorTicks(...ySpan, errorTickCount(height)) : [])
        .map((tick) => ({ ...tick, at: y(tick.value) }));
    const LEFT = Math.max(scales.axisLeft, axisLeftFor(yTicks));
    const xSpan = visibleSpan(x, [LEFT, width]);
    const xTicks = (xSpan ? driftTicks(xSpan, Math.max(2, Math.round((width - LEFT) / 110))) : [])
        .map((tick) => ({ ...tick, at: x(tick.value) }));

    // The full title where the axis is tall enough for it, its short name where it is not
    const yTitle = textWidth(metricTitle(metric), TITLE_FONT) <= height - BOTTOM - 16
        ? metricTitle(metric) : METRIC_LABELS[metric];

    return (
        <>
            <svg className="analysis-grid" width={width} height={height} aria-hidden="true">
                {xTicks.map((tick) => <line key={`x${tick.value}`} x1={tick.at} x2={tick.at} y1={0} y2={height}/>)}
                {yTicks.map((tick) => <line key={`y${tick.value}`} x1={0} x2={width} y1={tick.at} y2={tick.at}/>)}
            </svg>
            <svg className="analysis-axes" width={width} height={height} aria-hidden="true">
                <rect className="analysis-axis-strip" x={0} y={0} width={LEFT} height={height - BOTTOM}/>
                <rect className="analysis-axis-strip" x={0} y={height - BOTTOM} width={width} height={BOTTOM}/>
                <line className="analysis-axis-line" x1={LEFT} x2={LEFT} y1={0} y2={height - BOTTOM}/>
                <line className="analysis-axis-line" x1={LEFT} x2={width} y1={height - BOTTOM} y2={height - BOTTOM}/>

                {yTicks.filter((tick) => tick.at >= 8 && tick.at <= height - BOTTOM).map((tick) => (
                    <g key={`y${tick.value}`} transform={`translate(${LEFT}, ${tick.at})`}>
                        <line className="analysis-axis-line" x1={-TICK} x2={0}/>
                        <text className="analysis-tick" x={-TICK - AXIS_LABEL_GAP} dy="0.32em" textAnchor="end">{tick.label}</text>
                    </g>
                ))}
                {xTicks.filter((tick) => tick.at >= LEFT && tick.at <= width - 8).map((tick) => (
                    <g key={`x${tick.value}`} transform={`translate(${tick.at}, ${height - BOTTOM})`}>
                        <line className="analysis-axis-line" y1={0} y2={TICK}/>
                        <text className="analysis-tick" y={TICK + 3} dy="0.71em" textAnchor="middle">{tick.label}</text>
                    </g>
                ))}

                <text className="analysis-axis-title" textAnchor="middle" dominantBaseline="central"
                      transform={`translate(${AXIS_TITLE_ROOM / 2 + 1}, ${(height - BOTTOM) / 2}) rotate(-90)`}>
                    {yTitle}
                </text>
                <text className="analysis-axis-title" x={LEFT + (width - LEFT) / 2} y={height - 6} textAnchor="middle">
                    Drift from root
                </text>
            </svg>
        </>
    );
}
