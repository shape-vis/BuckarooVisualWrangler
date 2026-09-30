// RidgelineBrush.jsx
// Root's row under the drift ridgelines, which is also their zoom control. It always shows the whole column -
// root's shape, with each node's curve over it - and carries a brush for choosing the part the ridgelines
// above it show: focus and context, as in the visx brush demo. Root has no row of its own above, so this is
// where its shape reads. Drawn by React rather than d3, since the brush is a React component and d3's
// redraws would clear it.

import {useMemo, useRef} from "react";
import * as d3 from "d3";
import {Brush} from "@visx/brush";
import {ROLE_COLORS} from "../utils/comparison.js";

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
// Drift is teal wherever it is drawn - never red
const BRUSH_COLOR = "#0f766e";
const HANDLE = 8;
// The narrowest window, in grid steps. Past this a zoomed curve has too few points to be smooth.
const MIN_STEPS = 40;

const formatTick = d3.format(".3~s");

/* A grip on each edge of the brush, so it reads as something that can be pulled. The brush only listens
   where a custom handle draws, so the edge's full height is kept as an invisible hit area. */
function Grip({x, y, width, height, isBrushActive}) {
    if (!isBrushActive) return null;
    const middle = x + width / 2;
    const top = y + (height - 14) / 2;
    return (
        <g className="compare-brush-grip">
            <rect className="compare-brush-grip-hit" x={x} y={y} width={width} height={height}/>
            <rect x={middle - 3.5} y={top} width={7} height={14} rx={2}/>
            <path d={`M${middle - 1},${top + 4} v6 M${middle + 1},${top + 4} v6`}/>
        </g>
    );
}

/**
 * Root's row of the ridgeline, and its zoom control.
 *
 * Props:
 *  - density: the drift detail's density - its grid and root's curve
 *  - curves: {base, other}, each node's curve on the same grid, or null
 *  - spots: {base, other}, the grid index each node's annotation bubble points at, or null
 *  - frame: {left, width, total} - where the ridgeline's panel sits, so the two line up exactly
 *  - rootColor: root's colour in the ridgeline
 *  - curve: how tall the curves stand, so root's row can match the ridgeline's rows above it
 *  - range: [lo, hi] the ridgelines show, or null for the whole column
 *  - onRange: called with the new range, or null
 */
export default function RidgelineBrush({density, curves, spots, frame, rootColor, curve = DEFAULT_CURVE, range, onRange}) {
    const brushRef = useRef(null);
    const {grid, root} = density;
    const lo = grid[0];
    const hi = grid[grid.length - 1];

    const x = useMemo(() => d3.scaleLinear().domain([lo, hi]).range([0, frame.width]), [lo, hi, frame.width]);
    // The brush only runs sideways, but it still wants a vertical scale
    const y = useMemo(() => d3.scaleLinear().domain([0, 1]).range([curve, 0]), [curve]);

    const paths = useMemo(() => {
        const peak = d3.max([root, curves.base, curves.other].flatMap((values) => values ?? [])) || 1;
        const rise = (value) => PIN + curve - (value / peak) * curve * RIDGE_HEADROOM;
        const line = d3.line().x((_, i) => x(grid[i])).y(rise);
        return {
            root: d3.area().x((_, i) => x(grid[i])).y0(PIN + curve).y1(rise)(root),
            base: curves.base && line(curves.base),
            other: curves.other && line(curves.other),
        };
    }, [grid, root, curves, x, curve]);

    const minSpan = ((hi - lo) / (grid.length - 1)) * MIN_STEPS;

    /* The brush reports its box in the column's own units. A box narrower than the closest zoom is widened
       about its middle, and kept inside the column. */
    const changed = (bounds) => {
        if (!bounds) {
            onRange(null);
            return;
        }
        let [from, to] = [Math.max(lo, bounds.x0), Math.min(hi, bounds.x1)];
        if (to - from < minSpan) {
            const middle = (from + to) / 2;
            from = Math.min(Math.max(lo, middle - minSpan / 2), hi - minSpan);
            to = from + minSpan;
        }
        onRange([from, to]);
    };

    const reset = () => {
        brushRef.current?.reset();
        onRange(null);
    };

    // A zoom set before the strip was last drawn - under another plot kind, say - starts where it was left
    const initial = range ? {start: {x: x(range[0])}, end: {x: x(range[1])}} : undefined;

    return (
        <div className="compare-brush">
            <svg width={frame.total} height={PIN + curve + AXIS}>
                <g transform={`translate(${frame.left}, 0)`}>
                    <text className="compare-ridge-label" x={-8} y={PIN + curve / 2}
                          textAnchor="end" dominantBaseline="middle" fill={rootColor}>
                        root
                    </text>
                    {/* Root's row on a wash of its own grey, as the ridgeline's rows are on theirs */}
                    <rect className="compare-ridge-band" y={PIN} width={frame.width} height={curve} fill={rootColor}/>
                    <path d={paths.root} fill={rootColor} fillOpacity={0.35}/>
                    {["base", "other"].map((role) => paths[role] && (
                        <path key={role} d={paths[role]} fill="none" stroke={ROLE_COLORS[role]} strokeWidth={1.2}/>
                    ))}
                    {/* Pins over the spots the bubbles point at, so there is somewhere to aim the brush */}
                    {["base", "other"].map((role) => spots[role] != null && (
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
                    <g transform={`translate(0, ${PIN})`}>
                        <Brush
                            xScale={x}
                            yScale={y}
                            width={frame.width}
                            height={curve}
                            margin={{left: frame.left, top: PIN}}
                            brushDirection="horizontal"
                            initialBrushPosition={initial}
                            innerRef={brushRef}
                            handleSize={HANDLE}
                            onChange={changed}
                            useWindowMoveEvents
                            selectedBoxStyle={{
                                fill: BRUSH_COLOR, fillOpacity: 0.12,
                                stroke: BRUSH_COLOR, strokeWidth: 1, strokeOpacity: 0.8,
                            }}
                            renderBrushHandle={(props) => <Grip {...props}/>}
                        />
                    </g>
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
