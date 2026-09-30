// SankeyBrush.jsx
// The strip beside the drift Sankeys: the ridgeline's overview strip turned on its side. It lists every
// category the Sankeys lay out, top to bottom in their order, and carries a brush for choosing the ones
// they show. Categories are whole rows, so the brush settles onto them. Drawn by React rather than d3, since
// the brush is a React component and d3's redraws would clear it.

import {useMemo, useRef} from "react";
import * as d3 from "d3";
import {Brush} from "@visx/brush";

const WIDTH = 132;
// Where the moved bars start, after the category names; the pins sit in the strip's left edge
const NAME = 70;
const PIN = 6;
const BAR = 3;
const BAR_GAP = 2;
// A category's name is left out below this row height, where it would run into the next
const MIN_NAMED_ROW = 11;
// Drift is teal wherever it is drawn - never red
const BRUSH_COLOR = "#0f766e";
const HANDLE = 8;

const truncate = (label) => (label.length > 10 ? `${label.slice(0, 10)}…` : label);

/* A grip on the brush's top and bottom edges, so it reads as something that can be pulled. The brush hands a
   custom handle the stage's full height, which suits a sideways brush; this one keeps to the edge. */
function Grip({x, y, width, isBrushActive}) {
    if (!isBrushActive) return null;
    const middle = y + HANDLE / 2;
    const left = x + (width - 14) / 2;
    return (
        <g className="compare-brush-grip compare-brush-grip--rows">
            <rect className="compare-brush-grip-hit" x={x} y={y} width={width} height={HANDLE}/>
            <rect x={left} y={middle - 3.5} width={14} height={7} rx={2}/>
            <path d={`M${left + 4},${middle - 1} h6 M${left + 4},${middle + 1} h6`}/>
        </g>
    );
}

/**
 * The Sankeys' overview and window control.
 *
 * Props:
 *  - categories: every category the Sankeys lay out, in their order
 *  - series: one per Sankey, {id, color, shares} - for each category the share of its rows that Sankey moved
 *  - spots: {id, color, index} for each annotation bubble, naming the category it points from
 *  - frame: {top, height, total} - where the Sankeys' panels sit, so the two line up
 *  - range: [first, last) the category positions the Sankeys show, or null for all of them
 *  - onRange: called with the new range, or null
 */
export default function SankeyBrush({categories, series, spots, frame, range, onRange}) {
    const brushRef = useRef(null);
    const count = categories.length;
    const row = frame.height / count;
    const barWidth = WIDTH - NAME - 4;
    // The bars sit as a stack in the middle of the row, in the panels' own order
    const bars = series.length * BAR + (series.length - 1) * BAR_GAP;

    const y = useMemo(() => d3.scaleLinear().domain([0, count]).range([0, frame.height]), [count, frame.height]);
    // The brush only runs up and down, but it still wants a horizontal scale
    const x = useMemo(() => d3.scaleLinear().domain([0, 1]).range([0, WIDTH]), []);

    /* The brush reports its box in category positions. The window runs between whole categories and holds at
       least one; a window holding all of them is no window. */
    const snap = (bounds) => {
        let first = Math.max(0, Math.round(bounds.y0));
        let last = Math.min(count, Math.round(bounds.y1));
        if (last - first < 1) {
            first = Math.min(Math.max(0, Math.floor((bounds.y0 + bounds.y1) / 2)), count - 1);
            last = first + 1;
        }
        return first === 0 && last === count ? null : [first, last];
    };

    // A fresh drag clears the box for a moment before drawing it, which is not worth redrawing every category for
    const changed = (bounds) => {
        if (bounds) onRange(snap(bounds));
        else if (!brushRef.current?.state.isBrushing) onRange(null);
    };

    // Once let go, the box settles onto the categories it shows
    const settled = (bounds) => {
        if (!bounds) {
            onRange(null);
            return;
        }
        const [first, last] = snap(bounds) ?? [0, count];
        // The brush calls this from inside its own state update, so the box moves once that is done
        setTimeout(() => brushRef.current?.updateBrush((previous) => ({
            ...previous,
            start: {x: 0, y: y(first)},
            end: {x: WIDTH, y: y(last)},
            extent: {x0: 0, x1: WIDTH, y0: y(first), y1: y(last)},
        })));
    };

    const reset = () => {
        brushRef.current?.reset();
        onRange(null);
    };

    // A window set before the strip was last drawn - under another plot kind, say - starts where it was left
    const initial = range ? {start: {x: 0, y: y(range[0])}, end: {x: WIDTH, y: y(range[1])}} : undefined;
    // Two pins on one category sit either side of its middle rather than on top of each other
    const pinAt = (spot) => {
        const shared = spots.filter((other) => other.index === spot.index);
        const offset = shared.length > 1 ? (shared.indexOf(spot) - (shared.length - 1) / 2) * 9 : 0;
        return y(spot.index) + row / 2 + offset;
    };

    return (
        <div className="compare-brush compare-brush--rows">
            <svg width={WIDTH} height={frame.total}>
                <text className="compare-brush-label" x={0} y={frame.top - 14}>overview</text>
                <text className="compare-brush-label" x={NAME} y={frame.top - 14}>
                    moved
                    <title>
                        The share of each category's rows the Sankeys moved - recoded or removed - one bar
                        each, in the order the Sankeys are drawn
                    </title>
                </text>
                <g transform={`translate(0, ${frame.top})`}>
                    {categories.map((label, i) => (
                        <g key={label} transform={`translate(0, ${y(i)})`}>
                            {i > 0 && <line className="compare-brush-floor" x1={0} x2={WIDTH} y1={0} y2={0}/>}
                            {row >= MIN_NAMED_ROW && (
                                <text className="compare-brush-name" x={PIN + 4} y={row / 2} dominantBaseline="middle">
                                    {truncate(label)}
                                </text>
                            )}
                            {series.map((one, j) => (
                                <g
                                    key={one.id}
                                    transform={`translate(${NAME}, ${row / 2 - bars / 2 + j * (BAR + BAR_GAP)})`}
                                >
                                    <rect className="compare-brush-track" width={barWidth} height={BAR}/>
                                    <rect width={one.shares[i] * barWidth} height={BAR} fill={one.color}/>
                                </g>
                            ))}
                        </g>
                    ))}
                    {/* Pins beside the categories the bubbles point from, so there is somewhere to aim the brush */}
                    {spots.map((spot) => (
                        <path
                            key={spot.id}
                            d={`M0,${pinAt(spot) - 4} l${PIN},4 l${-PIN},4 z`}
                            fill={spot.color}
                        />
                    ))}
                    <Brush
                        xScale={x}
                        yScale={y}
                        width={WIDTH}
                        height={frame.height}
                        margin={{left: 0, top: frame.top}}
                        brushDirection="vertical"
                        resizeTriggerAreas={["top", "bottom"]}
                        initialBrushPosition={initial}
                        innerRef={brushRef}
                        handleSize={HANDLE}
                        onChange={changed}
                        onBrushEnd={settled}
                        useWindowMoveEvents
                        selectedBoxStyle={{
                            fill: BRUSH_COLOR, fillOpacity: 0.12,
                            stroke: BRUSH_COLOR, strokeWidth: 1, strokeOpacity: 0.8,
                        }}
                        renderBrushHandle={(props) => <Grip {...props}/>}
                    />
                </g>
            </svg>
            {range ? (
                <button
                    type="button"
                    className="compare-brush-reset"
                    style={{top: frame.top + frame.height + 12}}
                    onClick={reset}
                >
                    Show all
                </button>
            ) : (
                <span className="compare-brush-hint" style={{top: frame.top + frame.height + 12}}>Drag to zoom</span>
            )}
        </div>
    );
}
