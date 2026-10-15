import {ERROR_DIMENSIONS, DRIFT_COLOR, errorColors} from "../../store/errorColors.js";
import {ROLE_COLORS} from "../../utils/comparison.js";

/**
 * Each kind of supporting sub-node drawn as a tiny picture of itself: what its badge shows on the host while it
 * is hidden (SupportBadges), and what a compare sub-node shows until it is large enough for its plot. Abstract
 * rather than real data - a histogram is a few bars, a heatmap a shaded grid - except a sparkline's, whose
 * values ride along in its record, so its badge has the real shape.
 *
 * Every glyph draws in a 16 by 16 box and scales to whatever it is given. Each is a ({record}) component, as
 * the registry's Badge entries are.
 */

const VIEW_BOX = "0 0 16 16";
const INK = "var(--support-ink)";
const GREY = "#94a3b8";

function Glyph({children}) {
    return (
        <svg className="support-glyph" viewBox={VIEW_BOX} aria-hidden="true">
            {children}
        </svg>
    );
}

/* A few bars of a histogram - the tallest stacked with a sliver of error, as the plot stacks error types */
function histogramBars(color = INK) {
    const bars = [
        {x: 1.5, height: 6},
        {x: 5.5, height: 11},
        {x: 9.5, height: 8},
        {x: 13, height: 4, width: 2},
    ];
    return bars.map((bar) => (
        <rect key={bar.x} x={bar.x} y={15 - bar.height} width={bar.width ?? 3} height={bar.height} fill={color}/>
    ));
}

// A 3 by 3 grid of shaded tiles, darker where more rows fall
const HEAT = [
    [0.35, 0.7, 1],
    [0.2, 0.55, 0.8],
    [0.1, 0.3, 0.45],
];

function heatmapTiles(color = INK) {
    const tiles = [];
    for (let row = 0; row < HEAT.length; row++) {
        for (let column = 0; column < HEAT[row].length; column++) {
            tiles.push(
                <rect
                    key={`${row}-${column}`}
                    x={1 + column * 5}
                    y={1 + row * 5}
                    width={4.4}
                    height={4.4}
                    fill={color}
                    fillOpacity={HEAT[row][column]}
                />,
            );
        }
    }
    return tiles;
}

// Two overlapping humps: the reference's shape filled, the node's outlined over it, shifted - what drift draws
function driftHumps(reference = GREY, node = DRIFT_COLOR) {
    return (
        <>
            <path d="M1,14 C4,14 4,4 7,4 C10,4 10,14 13,14 Z" fill={reference} fillOpacity={0.55}/>
            <path d="M3,14 C6,14 7,6 10,6 C13,6 13,14 15,14" fill="none" stroke={node} strokeWidth={1.4}/>
        </>
    );
}

export function HistogramGlyph() {
    return <Glyph>{histogramBars()}</Glyph>;
}

export function HeatmapGlyph() {
    return <Glyph>{heatmapTiles()}</Glyph>;
}

/** An error plot's badge: its histogram's bars, or its heatmap's tiles. */
export function ErrorPlotGlyph({record}) {
    if (record.config?.plot === "heatmap") return <HeatmapGlyph/>;
    return <HistogramGlyph/>;
}

export function DriftGlyph() {
    return <Glyph>{driftHumps()}</Glyph>;
}

// A sparkline drawn from no values: a gentle line falling, as a branch's errors do when it is working
const GENERIC_SPARK = [0.75, 0.6, 0.65, 0.35, 0.3, 0.15];

/* The sparkline's points, through a 16 by 16 box with a pixel of room all round. Equal values draw flat across
   the middle. */
function sparkPoints(values) {
    const low = Math.min(...values);
    const high = Math.max(...values);
    const span = high - low;
    const step = 14 / Math.max(1, values.length - 1);

    const points = [];
    values.forEach((value, index) => {
        let share = 0.5;
        if (span > 0) {
            share = (value - low) / span;
        }
        const x = 1 + index * step;
        const y = 14 - share * 12;
        points.push(`${x.toFixed(2)},${y.toFixed(2)}`);
    });
    return points.join(" ");
}

/** A sparkline's badge: its own values' shape in its dimension's colour, once it has a branch. */
export function SparklineGlyph({record}) {
    const {dimension, values = []} = record?.config ?? {};
    const measured = values.length > 1 && values.every((value) => value != null);

    let points = sparkPoints(GENERIC_SPARK);
    if (measured) {
        points = sparkPoints(values);
    }

    let color = INK;
    if (dimension === "drift") {
        color = DRIFT_COLOR;
    } else if (dimension) {
        color = errorColors(dimension);
    }

    return (
        <Glyph>
            <polyline points={points} fill="none" stroke={color} strokeWidth={1.6}
                      strokeLinejoin="round" strokeLinecap="round"/>
        </Glyph>
    );
}

/** A wrangle diff's badge: the column before the wrangle in grey, and after it. */
export function WrangleDiffGlyph() {
    return (
        <Glyph>
            <rect x={1.5} y={4} width={4} height={11} fill={GREY}/>
            <path d="M7,9 h2.5 M8.5,7.5 l1.5,1.5 l-1.5,1.5" stroke={INK} strokeWidth={1} fill="none"/>
            <rect x={11} y={8} width={4} height={7} fill={INK}/>
        </Glyph>
    );
}

/** Quality metrics' badge: one bar split into the error types' shares. */
export function QualityMetricsGlyph() {
    const shares = [0.35, 0.2, 0.3, 0.15];
    const segments = [];
    let x = 1;
    ERROR_DIMENSIONS.forEach((dimension, index) => {
        const width = shares[index] * 14;
        segments.push(<rect key={dimension} x={x} y={6} width={width} height={5} fill={errorColors(dimension)}/>);
        x += width;
    });
    return <Glyph>{segments}</Glyph>;
}

/** A comparison's badge: a tiny plot of its kind in the two selections' colours. */
export function CompareGlyph({record}) {
    const kind = record?.config?.spec?.kind ?? "histogram";

    if (kind === "heatmap") {
        return (
            <Glyph>
                {heatmapTiles(ROLE_COLORS.a)}
                <path d="M1,15 L15,1 L15,15 Z" fill={ROLE_COLORS.b} fillOpacity={0.35}/>
            </Glyph>
        );
    }
    if (kind === "drift") {
        return <Glyph>{driftHumps(ROLE_COLORS.a, ROLE_COLORS.b)}</Glyph>;
    }

    const pairs = [
        {x: 1, a: 6, b: 8},
        {x: 6, a: 11, b: 9},
        {x: 11, a: 5, b: 7},
    ];
    return (
        <Glyph>
            {pairs.map((pair) => (
                <g key={pair.x}>
                    <rect x={pair.x} y={15 - pair.a} width={2} height={pair.a} fill={ROLE_COLORS.a}/>
                    <rect x={pair.x + 2} y={15 - pair.b} width={2} height={pair.b} fill={ROLE_COLORS.b}/>
                </g>
            ))}
        </Glyph>
    );
}
