import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import HeatMap from "../visualizations/HeatMap.jsx";
import HistogramBarChart from "../visualizations/HistogramBarChart.jsx";
import ScatterPlot from "../visualizations/ScatterPlot.jsx";
import "../styles/SelectionPanel.css";
import { updateBackendAttributes } from "../utils/serverCalls.jsx";
import { ERROR_TYPES, errorColors } from "../utils/errorColors.js";

// ── Icon: magnifier (zoom-in) ─────────────────────────────────────────────────
function MagnifierIcon({ x, y, onClick }) {
    const r = 4.5;
    const cx = x + r + 1;
    const cy = y + r + 1;
    return (
        <g
            className="plot-cell-icon"
            onClick={e => { e.stopPropagation(); onClick(); }}
        >
            <rect x={x - 1} y={y - 1} width={16} height={16} rx={3} fill="white" fillOpacity={0.85} />
            <circle cx={cx} cy={cy} r={r} fill="none" stroke="#444" strokeWidth={1.5} />
            <line
                x1={cx + r * 0.65} y1={cy + r * 0.65}
                x2={cx + r * 1.5}  y2={cy + r * 1.5}
                stroke="#444" strokeWidth={1.5} strokeLinecap="round"
            />
        </g>
    );
}

// ── Icon: minimize (compress arrows) ─────────────────────────────────────────
function MinimizeIcon({ x, y, onClick }) {
    const s = 16;
    const m = 3;
    const arm = 5;
    return (
        <g
            className="plot-minimize-icon"
            onClick={e => { e.stopPropagation(); onClick(); }}
        >
            <rect x={x - 1} y={y - 1} width={s + 2} height={s + 2} rx={3} fill="white" fillOpacity={0.85} />
            {/* top-left corner arrows pointing inward */}
            <polyline
                points={`${x + m},${y + m + arm} ${x + m},${y + m} ${x + m + arm},${y + m}`}
                fill="none" stroke="#444" strokeWidth={1.5} strokeLinejoin="round"
            />
            {/* bottom-right corner arrows pointing inward */}
            <polyline
                points={`${x + s - m},${y + s - m - arm} ${x + s - m},${y + s - m} ${x + s - m - arm},${y + s - m}`}
                fill="none" stroke="#444" strokeWidth={1.5} strokeLinejoin="round"
            />
        </g>
    );
}

// ── Main panel ────────────────────────────────────────────────────────────────
function SelectionPanel({ table_name, selectedAttributes, w, h, errorTypes, errorColors }) {
    const matrixPlotAreaRef = useRef(null);
    const [plotSize, setPlotSize] = useState(180);
    const [focusedCell, setFocusedCell] = useState(null); // { i, j } or null

    const view = {
        xPadding: 85, yPadding: 70,
        leftMargin: 30, rightMargin: 40,
        topMargin: 50, bottomMargin: 50,
    };

    const columns = selectedAttributes || [];
    const [prevAttributes, setPrevAttributes] = useState(columns);

    // Updates active active attributes to backend
    useEffect(() => {
        // Determine removed attributes
        const removed = prevAttributes.filter(attr => !columns.includes(attr));

        if (removed.length === 0) {
            setPrevAttributes(columns);
            return;
        }

        const removedKeys = [];

        // Add 1D hist keys for removed attributes
        removed.forEach(attr => {
            removedKeys.push({ type: "1d", column: attr });
        });

        // Add 2D hist keys between removed + active attributes
        removed.forEach(removedAttr => {
            columns.forEach(activeAttr => {
                removedKeys.push({ type: "2d", columns: [removedAttr, activeAttr] }); // upper
                removedKeys.push({ type: "2d", columns: [activeAttr, removedAttr] }); // lower
            });
        });

        // Add 2D keys between removed attributes themselves if more than one removed
        if (removed.length > 1) {
            for (let i = 0; i < removed.length; i++) {
                for (let j = i + 1; j < removed.length; j++) {
                    removedKeys.push({ type: "2d", columns: [removed[i], removed[j]] }); // upper
                    removedKeys.push({ type: "2d", columns: [removed[j], removed[i]] }); // lower
                }
            }
        }

        // send nonactive views to backend.
        updateBackendAttributes({ removed_keys: removedKeys });

        // Update prevAttributes for next run
        setPrevAttributes(columns);
    }, [selectedAttributes]);

    // Clear focus if columns change (e.g. user deselects an attribute)
    useEffect(() => {
        setFocusedCell(null);
    }, [table_name, selectedAttributes]);

    useEffect(() => {
        const n = columns.length;
        if (n > 0) {
            let newPlotSize = Math.min(
                (w - view.leftMargin - view.rightMargin) / n - view.xPadding,
                (h - view.topMargin - view.bottomMargin) / n - view.yPadding
            );
            newPlotSize = Math.max(40, newPlotSize);
            setPlotSize(newPlotSize);
        }
    }, [table_name, selectedAttributes, w, h]);

    // ── Focused (expanded) view ───────────────────────────────────────────────
    if (focusedCell !== null) {
        const { i, j } = focusedCell;
        const xCol = columns[j];
        const yCol = columns[i];
        const cellID = `cell-${xCol}-${yCol}`;

        // Leave room for axis labels.
        // focusedXPos needs to accommodate D3 left-axis tick labels (up to ~80px for 10-char strings).
        // Bottom needs ~50px for D3 bottom-axis tick labels rendered below plot area.
        const focusedXPos = 90;
        const focusedYPos = 70;
        const focusedSize = Math.min(
            w - focusedXPos - 40,
            h - focusedYPos - 100
        );
        const clampedSize = Math.max(80, focusedSize);

        let plot;
        if (i === j) {
            plot = (
                <HistogramBarChart
                    cellID={cellID}
                    pos={{ x: focusedXPos, y: focusedYPos }}
                    size={{ w: clampedSize, h: clampedSize }}
                    table_name={table_name}
                    attrX={xCol}
                    errorColors={errorColors}
                />
            );
        } else if (i < j) {
            plot = (
                <ScatterPlot
                    cellID={cellID}
                    xPos={focusedXPos}
                    yPos={focusedYPos}
                    size={clampedSize}
                    table_name={table_name}
                    attrX={xCol}
                    attrY={yCol}
                    errorColors={errorColors}
                />
            );
        } else {
            plot = (
                <HeatMap
                    cellID={cellID}
                    xPos={focusedXPos}
                    yPos={focusedYPos}
                    size={clampedSize}
                    table_name={table_name}
                    attrX={xCol}
                    attrY={yCol}
                    errorColors={errorColors}
                />
            );
        }

        return (
            <g ref={matrixPlotAreaRef} id="matrix-plot-area">
                {/* X axis label */}
                <text
                    x={focusedXPos + clampedSize / 2}
                    y={focusedYPos - 28}
                    textAnchor="middle"
                    fontSize={14}
                    fontWeight="500"
                >
                    {xCol}
                </text>
                {/* Y axis label (only for 2-D plots) */}
                {i !== j && (
                    <text
                        x={focusedXPos - 65}
                        y={focusedYPos + clampedSize / 2}
                        textAnchor="middle"
                        fontSize={13}
                        fontWeight="500"
                        transform={`rotate(-90, ${focusedXPos - 65}, ${focusedYPos + clampedSize / 2})`}
                    >
                        {yCol}
                    </text>
                )}
                {plot}
                {/* Minimize icon — top-right corner of the focused plot */}
                <MinimizeIcon
                    x={focusedXPos + clampedSize - 18}
                    y={focusedYPos + 2}
                    onClick={() => setFocusedCell(null)}
                />
            </g>
        );
    }

    // ── Normal matrix view ────────────────────────────────────────────────────
    // TODO: Only update views in which attributes actually change.
    return (
        <g ref={matrixPlotAreaRef} id="matrix-plot-area">
            {/* Column (x) labels */}
            <g>
                {columns.map((col, i) => (
                    <text
                        key={`xlabel-${i}`}
                        x={view.leftMargin + (i + 1) * view.xPadding + i * plotSize + plotSize / 2}
                        y={view.topMargin - 10}
                        textAnchor="middle"
                    >
                        {col}
                    </text>
                ))}
                {columns.map((col, i) => (
                    <text
                        key={`ylabel-${i}`}
                        x={view.leftMargin - 10}
                        y={view.topMargin + i * (plotSize + view.yPadding) + plotSize / 2}
                        transform={`rotate(-90, ${view.leftMargin - 10}, ${view.topMargin + i * (plotSize + view.yPadding) + plotSize / 2})`}
                        textAnchor="middle"
                    >
                        {col}
                    </text>
                ))}
            </g>

            {/* Plot cells */}
            {columns.map((xCol, j) =>
                columns.map((yCol, i) => {

                    // CHANGE #1: cell identity based on columns
                    const cellID = `cell-${xCol}-${yCol}`;

                    const xPos = view.leftMargin + (j + 1) * view.xPadding + j * plotSize;
                    const yPos = view.topMargin + i * (plotSize + view.yPadding);
                    const iconX = xPos + plotSize - 16;
                    const iconY = yPos;

                    let plot;

                    if (i === j) {
                        plot = (
                            <HistogramBarChart
                                cellID={cellID}
                                pos={{ x: xPos, y: yPos }}
                                size={{ w: plotSize, h: plotSize }}
                                table_name={table_name}
                                attrX={xCol}
                                errorColors={errorColors}
                            />
                        );
                    } else if (i < j) {
                        plot = (
                            <ScatterPlot
                                cellID={cellID}
                                xPos={xPos}
                                yPos={yPos}
                                size={plotSize}
                                table_name={table_name}
                                attrX={xCol}
                                attrY={yCol}
                                errorColors={errorColors}
                            />
                        );
                    } else {
                        plot = (
                            <HeatMap
                                cellID={cellID}
                                xPos={xPos}
                                yPos={yPos}
                                size={plotSize}
                                table_name={table_name}
                                attrX={xCol}
                                attrY={yCol}
                                errorColors={errorColors}
                            />
                        );
                    }

                    return (
                        <g
                            key={cellID} // CHANGE #2: stable key
                            className="plot-cell-wrapper"
                        >
                            {plot}
                            <MagnifierIcon
                                x={iconX}
                                y={iconY}
                                onClick={() => setFocusedCell({ i, j })}
                            />
                        </g>
                    );
                })
            )}
        </g>
    );
}



/**
 * MatrixView React component - converted from matrixview.js
 *
 * Props:
 * - model
 * - givenData (object with columnNames() )
 * - visualizations: mapping (e.g. window.visualizations) with modules that expose .module.draw(svgModel, view, canvas, ...args)
 * - width, height (optional) - if not provided component will size SVG to parent bounding box
 */
export default function MatrixView({ table_name, selectedAttributes }) {
    const svgRef = useRef(null);

    const [w, setW] = React.useState(800);
    const [h, setH] = React.useState(600);

    const errorTypes = ERROR_TYPES;

    useEffect(() => {
        const svg = d3.select(svgRef.current);

        const resizeObserver = new ResizeObserver(() => {
            const bbox = svg.node().getBoundingClientRect();
            setW(bbox.width || 800);
            setH(bbox.height || 600);
        });

        if (svgRef.current) {
            resizeObserver.observe(svgRef.current);
        }

        return () => resizeObserver.disconnect();
    }, [table_name, selectedAttributes]);

    return (
        <svg ref={svgRef} id="main-svg" width={"100%"} height={"100%"} overflow="visible">
            <SelectionPanel table_name={table_name} selectedAttributes={selectedAttributes} w={w} h={h} errorColors={errorColors} />
        </svg>
    );
}
