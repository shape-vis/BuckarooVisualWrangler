// RidgelineBrush.jsx
// Root's row under the drift ridgelines, which is also their zoom control. It always shows the whole column -
// root's shape, with each node's curve over it - and carries a brush for choosing the part the ridgelines
// above it show: focus and context, as in the visx brush demo. Root has no row of its own above, so this is
// where its shape reads. Drawn by React, with the pointer handled here, as the Sankey's minimap does: drag on
// the strip to choose a range, drag inside it to move it, or pull either of its edges. Handling the pointer
// by hand is what lets it work in a popped-out window - see localSvgPoint.

import {useEffect, useMemo, useRef, useState} from "react";
import * as d3 from "d3";
import {ROLE_COLORS} from "../utils/comparison.js";
import {useHostWindow} from "../store/HostWindowContext.jsx";
import {DRIFT_COLOR} from "../store/errorColors.js";
import {clamp, localSvgPoint} from "../utils/visCommon.jsx";

// The pins above the curves and the tick labels below. The curves' own height comes from the plot, which
// sizes root's row to match the ridgeline's; this is the height to use when it gives none.
const PIN = 6;
const AXIS = 16;
const DEFAULT_CURVE = 72;
// The strip's height beyond its curves, for the plot to work out how much is left for them
export const STRIP_CHROME = PIN + AXIS;
/* How much of a row's height its tallest curve may take. The rest is left clear above it, so a peak never
   runs into the row above - the ridgeline's rows use the same, so root's row still matches theirs. */
export const RIDGE_HEADROOM = 0.9;
// How near the range's edge a press grabs that edge rather than the range
const EDGE = 6;
// A press that moves less than this, in pixels, is a click rather than a drag
const CLICK_SLOP = 3;
// The narrowest window, in grid steps. Past this a zoomed curve has too few points to be smooth.
const MIN_STEPS = 40;

const formatTick = d3.format(".3~s");

/* A grip on one edge of the range, so it reads as something that can be pulled. Only a mark: the strip takes
   every press, and works out from where it lands whether it grabs an edge. */
function Grip({x, height}) {
    const top = (height - 14) / 2;
    return (
        <g className="compare-brush-grip">
            <rect x={x - 3.5} y={top} width={7} height={14} rx={2}/>
            <path d={`M${x - 1},${top + 4} v6 M${x + 1},${top + 4} v6`}/>
        </g>
    );
}

/**
 * Root's row of the ridgeline, and its zoom control.
 *
 * Props:
 *  - density: the drift detail's density - its grid and root's curve
 *  - curves: {a, b}, each selected node's curve on the same grid, or null
 *  - spots: {a, b}, the grid index each node's annotation bubble points at, or null
 *  - frame: {left, width, total} - where the ridgeline's panel sits, so the two line up exactly
 *  - rootColor: root's colour in the ridgeline
 *  - baseLabel: what the row is named - "root", or the common ancestor's node when the drift is measured from it
 *  - curve: how tall the curves stand, so root's row can match the ridgeline's rows above it
 *  - range: [lo, hi] the ridgelines show, or null for the whole column
 *  - onRange: called with the new range, or null
 */
export default function RidgelineBrush({density, curves, spots, frame, rootColor, baseLabel = "root", curve = DEFAULT_CURVE, range, onRange}) {
    // Frames are the host window's, which keeps drawing while this page may be minimised behind a popped-out panel
    const hostWindow = useHostWindow();
    const svgRef = useRef(null);
    const {grid, root} = density;
    const lo = grid[0];
    const hi = grid[grid.length - 1];

    const x = useMemo(() => d3.scaleLinear().domain([lo, hi]).range([0, frame.width]), [lo, hi, frame.width]);

    const paths = useMemo(() => {
        const peak = d3.max([root, curves.a, curves.b].flatMap((values) => values ?? [])) || 1;
        const rise = (value) => PIN + curve - (value / peak) * curve * RIDGE_HEADROOM;
        const line = d3.line().x((_, i) => x(grid[i])).y(rise);
        return {
            root: d3.area().x((_, i) => x(grid[i])).y0(PIN + curve).y1(rise)(root),
            a: curves.a && line(curves.a),
            b: curves.b && line(curves.b),
        };
    }, [grid, root, curves, x, curve]);

    const minSpan = ((hi - lo) / (grid.length - 1)) * MIN_STEPS;

    /* A range in the column's own units. One narrower than the closest zoom is widened about its middle, and
       kept inside the column. */
    const changed = (start, end) => {
        let from = Math.max(lo, start);
        let to = Math.min(hi, end);
        if (to - from < minSpan) {
            const middle = (from + to) / 2;
            from = clamp(middle - minSpan / 2, lo, hi - minSpan);
            to = from + minSpan;
        }
        onRange([from, to]);
    };

    // The range as drawn, in the strip's pixels, or null when the whole column shows
    let box = null;
    if (range) {
        box = {x0: x(range[0]), x1: x(range[1])};
    }

    /* What a press would do where the pointer is - "left", "right", "move" or "select" - which sets the cursor.
       While dragging it is "dragging-" and what the drag is doing. */
    const [mode, setMode] = useState(null);
    const drag = useRef(null);

    /* A drag reports on every pointer move, but the plot only needs the latest range once a frame. Held in the
       strip's pixels until then. */
    const pending = useRef(null);
    const request = useRef(0);
    const send = (left, right) => {
        pending.current = [left, right];
        if (request.current) return;
        request.current = hostWindow.requestAnimationFrame(() => {
            request.current = 0;
            const [start, end] = pending.current;
            changed(x.invert(start), x.invert(end));
        });
    };
    useEffect(() => () => hostWindow.cancelAnimationFrame(request.current), [hostWindow]);

    // The pointer's place across the strip, in its pixels, held to the strip's ends
    const stripX = (event) => {
        const point = localSvgPoint(svgRef.current, event);
        return clamp(point.x - frame.left, 0, frame.width);
    };

    const modeAt = (at) => {
        if (!box) return "select";
        const nearLeft = Math.abs(at - box.x0) <= EDGE;
        const nearRight = Math.abs(at - box.x1) <= EDGE;
        // A range narrow enough for both edges to be in reach gives each the half nearer it
        if (nearLeft && nearRight) {
            const middle = (box.x0 + box.x1) / 2;
            return at < middle ? "left" : "right";
        }
        if (nearLeft) return "left";
        if (nearRight) return "right";
        if (at > box.x0 && at < box.x1) return "move";
        return "select";
    };

    const onPointerDown = (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        const at = stripX(event);
        const grabbed = modeAt(at);
        let start = box;
        if (!start) {
            start = {x0: at, x1: at};
        }
        drag.current = {mode: grabbed, from: at, start, moved: false};
        setMode(`dragging-${grabbed}`);
        event.currentTarget.setPointerCapture(event.pointerId);
    };

    const onPointerMove = (event) => {
        const at = stripX(event);
        const current = drag.current;
        if (!current) {
            const next = modeAt(at);
            if (next !== mode) setMode(next);
            return;
        }

        const delta = at - current.from;
        if (Math.abs(delta) >= CLICK_SLOP) current.moved = true;
        if (!current.moved) return;

        const {x0, x1} = current.start;
        if (current.mode === "move") {
            const span = x1 - x0;
            const left = clamp(x0 + delta, 0, frame.width - span);
            send(left, left + span);
            return;
        }

        // An edge pulled past the other one swaps with it, as a brush's does
        let edgeA = Math.min(current.from, at);
        let edgeB = Math.max(current.from, at);
        if (current.mode === "left") {
            edgeA = x0 + delta;
            edgeB = x1;
        } else if (current.mode === "right") {
            edgeA = x0;
            edgeB = x1 + delta;
        }
        send(Math.min(edgeA, edgeB), Math.max(edgeA, edgeB));
    };

    const endDrag = (event, cancelled) => {
        const current = drag.current;
        if (!current) return;
        drag.current = null;
        event.currentTarget.releasePointerCapture(event.pointerId);
        // A click beside the range, rather than a drag, lets the zoom go - as a click beside a brush clears it
        const clickedAway = !cancelled && !current.moved && current.mode === "select";
        if (clickedAway && range) {
            onRange(null);
        }
        setMode(modeAt(stripX(event)));
    };

    const reset = () => onRange(null);

    let overlayClass = "compare-brush-overlay";
    if (mode) {
        overlayClass += ` compare-brush-overlay--${mode}`;
    }

    return (
        <div className="compare-brush">
            <svg ref={svgRef} width={frame.total} height={PIN + curve + AXIS}>
                <g transform={`translate(${frame.left}, 0)`}>
                    <text className="compare-ridge-label" x={-8} y={PIN + curve / 2}
                          textAnchor="end" dominantBaseline="middle" fill={rootColor}>
                        {baseLabel}
                    </text>
                    {/* Root's row on a wash of its own grey, as the ridgeline's rows are on theirs */}
                    <rect className="compare-ridge-band" y={PIN} width={frame.width} height={curve} fill={rootColor}/>
                    <path d={paths.root} fill={rootColor} fillOpacity={0.35}/>
                    {["a", "b"].map((role) => paths[role] && (
                        <path key={role} d={paths[role]} fill="none" stroke={ROLE_COLORS[role]} strokeWidth={1.2}/>
                    ))}
                    {/* Pins over the spots the bubbles point at, so there is somewhere to aim the brush */}
                    {["a", "b"].map((role) => spots[role] != null && (
                        <path
                            key={`pin-${role}`}
                            d={`M${x(grid[spots[role]]) - 4},0 h8 l-4,${PIN} z`}
                            fill={ROLE_COLORS[role]}
                        />
                    ))}
                    <line className="compare-brush-floor" x1={0} x2={frame.width} y1={PIN + curve} y2={PIN + curve}/>
                    {x.ticks(5).map((tick) => (
                        <text key={tick} className="compare-brush-tick" x={x(tick)} y={PIN + curve + 12} textAnchor="middle">
                            {formatTick(tick)}
                        </text>
                    ))}
                    {box && (
                        <g transform={`translate(0, ${PIN})`}>
                            <rect
                                className="compare-brush-range"
                                x={box.x0}
                                width={Math.max(1, box.x1 - box.x0)}
                                height={curve}
                                fill={DRIFT_COLOR}
                                fillOpacity={0.12}
                                stroke={DRIFT_COLOR}
                                strokeOpacity={0.8}
                            />
                            <Grip x={box.x0} height={curve}/>
                            <Grip x={box.x1} height={curve}/>
                        </g>
                    )}
                    {/* Takes every press on the strip, over the range and its grips */}
                    <rect
                        className={overlayClass}
                        y={PIN}
                        width={frame.width}
                        height={curve}
                        onPointerDown={onPointerDown}
                        onPointerMove={onPointerMove}
                        onPointerUp={(event) => endDrag(event, false)}
                        onPointerCancel={(event) => endDrag(event, true)}
                        onPointerLeave={() => { if (!drag.current) setMode(null); }}
                    />
                </g>
            </svg>
            {range ? (
                <button type="button" className="compare-brush-reset" onClick={reset}>Full range</button>
            ) : (
                <span className="compare-brush-hint">Drag to zoom</span>
            )}
        </div>
    );
}
