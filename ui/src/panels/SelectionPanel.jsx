import React, { useEffect, useRef, useState } from "react";
import HeatMap from "../visualizations/HeatMap.jsx";
import HistogramBarChart from "../visualizations/HistogramBarChart.jsx";
import ScatterPlot from "../visualizations/ScatterPlot.jsx";
import "../styles/SelectionPanel.css";
import { updateBackendAttributes } from "../utils/serverCalls.jsx";
import { ERROR_TYPES, errorColors } from "../store/errorColors.js";
import { useTableName } from "../store/TableNameContext.jsx";
import { useSelection } from "../store/SelectionContext.jsx";
import { heatMapCache, histogramCache, scatterPlotCache } from "../store/visualizationCaches.jsx";

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
function SelectionPanel({ selectedAttributes, w, h, errorTypes, errorColors, onFocusChange, setContentHeight }) {
    const { tableName: table_name } = useTableName();
    const { highlightedRowIds, highlightedCols, selectionSource, highlightRevision, clearHighlight } = useSelection();
    const matrixPlotAreaRef = useRef(null);
    const [focusedCell, setFocusedCell] = useState(null); // { i, j } or null
    const [deferOffDiagonalPlots, setDeferOffDiagonalPlots] = useState(true);

    const columns = selectedAttributes || [];
    const columnsKey = columns.join("|");
    const columnCount = columns.length || 1;
    const view = {
        yPadding: 50,
        leftMargin: 70,
        rightMargin: 20,
        topMargin: 40,
        bottomMargin: 46,
    };

    // Horizontal gap bounds between columns: a minimum so left-axis tick
    // labels never overlap the previous column, and a maximum so columns don't
    // drift too far apart on wide screens.
    const minColGap = 70;
    const maxColGap = 130;
    const availW = Math.max(160, w - view.leftMargin - view.rightMargin);
    const availH = Math.max(160, h - view.topMargin - view.bottomMargin);

    // Cell size fits the height (so the whole matrix is visible without
    // scrolling), but is also capped by width on narrow screens.
    const sizeByHeight = (availH - (columnCount - 1) * view.yPadding) / columnCount;
    const sizeByWidth = (availW - (columnCount - 1) * minColGap) / columnCount;
    const plotSize = Math.max(80, Math.min(sizeByHeight, sizeByWidth, 280));

    // Keep a moderate gap between columns rather than stretching edge-to-edge,
    // then center the matrix so both sides keep healthy margins.
    const maxGapFit = columnCount > 1 ? (availW - columnCount * plotSize) / (columnCount - 1) : 0;
    const colGap = Math.min(maxColGap, Math.max(minColGap, maxGapFit));
    const matrixWidth = columnCount * plotSize + (columnCount - 1) * colGap;
    const xStart = view.leftMargin + Math.max(0, (availW - matrixWidth) / 2);

    const colX = (j) => xStart + j * (plotSize + colGap);
    const rowY = (i) => view.topMargin + i * (plotSize + view.yPadding);

    const matrixHeight =
        view.topMargin + columnCount * plotSize + (columnCount - 1) * view.yPadding + view.bottomMargin;

    const [prevAttributes, setPrevAttributes] = useState(columns);

    useEffect(() => {
        onFocusChange?.(focusedCell !== null);
    }, [focusedCell, onFocusChange]);

    useEffect(() => {
        setDeferOffDiagonalPlots(true);
        const timer = setTimeout(() => {
            setDeferOffDiagonalPlots(false);
        }, 900);
        return () => clearTimeout(timer);
    }, [table_name, columnsKey]);

    // Report the height the matrix needs so the container can scroll vertically
    // instead of hiding the bottom plots behind the table.
    useEffect(() => {
        if (focusedCell !== null) {
            setContentHeight?.(null);
        } else {
            setContentHeight?.(matrixHeight);
        }
    }, [focusedCell, matrixHeight, setContentHeight]);

    function clearFrontendPlotCaches(removedAttributes, activeAttributes) {
        // clear 1D hist cache
        removedAttributes.forEach((attr) => {
            histogramCache.delete(`${table_name}|${attr}`);
        });

        // clear active-nonactive cache for nonactive attributes, heatmap & scatterplot.
        removedAttributes.forEach((removedAttr) => {
            activeAttributes.forEach((activeAttr) => {
                heatMapCache.delete(`${table_name}|${removedAttr}|${activeAttr}`);
                heatMapCache.delete(`${table_name}|${activeAttr}|${removedAttr}`);
                scatterPlotCache.delete(`${table_name}|${removedAttr}|${activeAttr}`);
                scatterPlotCache.delete(`${table_name}|${activeAttr}|${removedAttr}`);
            });
        });

        // clear nonactive-nonactive cache if there are multiple attributes, heatmap & scatterplot.
        if (removedAttributes.length > 1) {
            for (let i = 0; i < removedAttributes.length; i++) {
                for (let j = i + 1; j < removedAttributes.length; j++) {
                    const first = removedAttributes[i];
                    const second = removedAttributes[j];
                    heatMapCache.delete(`${table_name}|${first}|${second}`);
                    heatMapCache.delete(`${table_name}|${second}|${first}`);
                    scatterPlotCache.delete(`${table_name}|${first}|${second}`);
                    scatterPlotCache.delete(`${table_name}|${second}|${first}`);
                }
            }
        }
    }

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

        // // Keep frontend cache consistent with backend.
        // // Remove cached nonactive viewport keys when deselected.
        clearFrontendPlotCaches(removed, columns);

        // send nonactive views to backend.
        updateBackendAttributes({ removed_keys: removedKeys });

        // Update prevAttributes for next run
        setPrevAttributes(columns);
    }, [selectedAttributes]);

    // Clear focus if columns change (e.g. user deselects an attribute)
    useEffect(() => {
        setFocusedCell(null);
    }, [table_name, selectedAttributes]);

    // ── Focused (expanded) view ───────────────────────────────────────────────
    useEffect(() => {
        if (!highlightedRowIds || highlightedRowIds.length === 0) return;
        if (!highlightedCols || highlightedCols.length === 0) return;

        let nextFocusedCell = null;
        if (selectionSource === "histogram" && highlightedCols.length === 1) {
            const idx = columns.indexOf(highlightedCols[0]);
            if (idx !== -1) {
                nextFocusedCell = { i: idx, j: idx };
            }
        }

        if ((selectionSource === "scatterplot" || selectionSource === "heatmap") && highlightedCols.length >= 2) {
            const j = columns.indexOf(highlightedCols[0]);
            const i = columns.indexOf(highlightedCols[1]);
            if (i !== -1 && j !== -1) {
                nextFocusedCell = { i, j };
            }
        }

        if (!nextFocusedCell) return;
        setFocusedCell(current => {
            if (current && current.i === nextFocusedCell.i && current.j === nextFocusedCell.j) {
                return current;
            }
            return nextFocusedCell;
        });
    }, [highlightRevision, highlightedRowIds, highlightedCols, selectionSource, columns]);

    if (focusedCell !== null) {
        const { i, j } = focusedCell;
        const xCol = columns[j];
        const yCol = columns[i];
        const cellID = `cell-${xCol}-${yCol}`;

        // Leave room for axis labels.
        // focusedXPos needs to accommodate D3 left-axis tick labels (up to ~80px for 10-char strings).
        // Bottom needs ~50px for D3 bottom-axis tick labels rendered below plot area.
        const focusedXPos = 86;
        const focusedYPos = 58;
        const focusedSize = Math.min(
            w - focusedXPos - 36,
            h - focusedYPos - 78
        );
        const clampedSize = Math.max(80, focusedSize);
        const selectedIds = Array.isArray(highlightedRowIds) ? highlightedRowIds : [];
        const selectedIdsLabel = selectedIds.length > 0
            ? `Selected IDs: ${selectedIds.slice(0, 10).join(", ")}${selectedIds.length > 10 ? `, +${selectedIds.length - 10} more` : ""}`
            : "No row selected";
        const legendEntries = Object.entries(ERROR_TYPES).filter(([key]) => key !== "total");
        const legendWidth = 176;
        const legendX = Math.max(focusedXPos + 8, focusedXPos + clampedSize - legendWidth - 8);
        const legendY = focusedYPos + 24;
        const legendHeight = 28 + legendEntries.length * 18;
        const legendColor = typeof errorColors === "function" ? errorColors : (() => "#6b7280");

        let plot;
        if (i === j) {
            plot = (
                <HistogramBarChart
                    cellID={cellID}
                    pos={{ x: focusedXPos, y: focusedYPos }}
                    size={{ w: clampedSize, h: clampedSize }}
                    attrX={xCol}
                    errorColors={errorColors}
                    detailMode="focused"
                />
            );
        } else if (i < j) {
            plot = (
                <ScatterPlot
                    cellID={cellID}
                    xPos={focusedXPos}
                    yPos={focusedYPos}
                    size={clampedSize}
                    attrX={xCol}
                    attrY={yCol}
                    errorColors={errorColors}
                    detailMode="focused"
                />
            );
        } else {
            plot = (
                <HeatMap
                    cellID={cellID}
                    xPos={focusedXPos}
                    yPos={focusedYPos}
                    size={clampedSize}
                    attrX={xCol}
                    attrY={yCol}
                    errorColors={errorColors}
                    detailMode="focused"
                />
            );
        }

        return (
            <g
                ref={matrixPlotAreaRef}
                id="matrix-plot-area"
                onDoubleClick={() => {
                    clearHighlight();
                    setFocusedCell(null);
                }}
            >
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
                {clampedSize >= 260 && (
                    <g className="focused-plot-legend" transform={`translate(${legendX}, ${legendY})`} pointerEvents="none">
                        <rect
                            width={legendWidth}
                            height={legendHeight}
                            rx={6}
                            fill="white"
                            fillOpacity={0.9}
                            stroke="#d1d5db"
                        />
                        <text x={10} y={17} fontSize={11} fontWeight="700" fill="#111827">
                            Error legend
                        </text>
                        {legendEntries.map(([key, label], idx) => {
                            const displayLabel = label.length > 23 ? `${label.slice(0, 22)}...` : label;
                            return (
                                <g key={key} transform={`translate(10, ${30 + idx * 18})`}>
                                    <rect width={10} height={10} rx={2} fill={legendColor(key)} stroke="#6b7280" strokeWidth={0.4} />
                                    <text x={16} y={9} fontSize={10} fill="#374151">
                                        {displayLabel}
                                    </text>
                                    <title>{label}</title>
                                </g>
                            );
                        })}
                    </g>
                )}
                <text
                    x={focusedXPos}
                    y={focusedYPos + clampedSize + 44}
                    fontSize={12}
                    fill={selectedIds.length > 0 ? "#111827" : "#6b7280"}
                    fontWeight={selectedIds.length > 0 ? "600" : "400"}
                >
                    {selectedIdsLabel}
                </text>
            </g>
        );
    }

    // ── Normal matrix view ────────────────────────────────────────────────────
    // TODO: Only update views in which attributes actually change.
    return (
        <g ref={matrixPlotAreaRef} id="matrix-plot-area">
            {/* Always-visible matrix labels for orientation. */}
            <g className="plot-matrix-labels" pointerEvents="none">
                {columns.map((col, i) => {
                    const label = col.length > 18 ? `${col.slice(0, 17)}...` : col;
                    return (
                        <text
                            key={`xlabel-${col}`}
                            x={colX(i) + plotSize / 2}
                            y={view.topMargin - 16}
                            textAnchor="middle"
                        >
                            {label}
                            <title>{col}</title>
                        </text>
                    );
                })}
                {columns.map((col, i) => {
                    const label = col.length > 18 ? `${col.slice(0, 17)}...` : col;
                    const x = Math.max(14, xStart - 80);
                    const y = rowY(i) + plotSize / 2;
                    return (
                        <text
                            key={`ylabel-${col}`}
                            x={x}
                            y={y}
                            transform={`rotate(-90, ${x}, ${y})`}
                            textAnchor="middle"
                        >
                            {label}
                            <title>{col}</title>
                        </text>
                    );
                })}
            </g>
            {/* Plot cells */}
            {columns.map((xCol, j) =>
                columns.map((yCol, i) => {

                    // CHANGE #1: cell identity based on columns
                    const cellID = `cell-${xCol}-${yCol}`;

                    const xPos = colX(j);
                    const yPos = rowY(i);
                    const iconX = xPos + plotSize - 16;
                    const iconY = yPos;

                    let plot;

                    if (i === j) {
                        plot = (
                            <HistogramBarChart
                                cellID={cellID}
                                pos={{ x: xPos, y: yPos }}
                                size={{ w: plotSize, h: plotSize }}

                                attrX={xCol}
                                errorColors={errorColors}
                                detailMode="compact"
                            />
                        );
                    } else if (deferOffDiagonalPlots) {
                        plot = (
                            <g transform={`translate(${xPos}, ${yPos})`}>
                                <rect
                                    width={plotSize}
                                    height={plotSize}
                                    rx={4}
                                    fill="#f8fafc"
                                    stroke="#dbe3ef"
                                />
                                <text
                                    x={plotSize / 2}
                                    y={plotSize / 2}
                                    textAnchor="middle"
                                    dominantBaseline="middle"
                                    fontSize={11}
                                    fill="#64748b"
                                >
                                    Loading plot...
                                </text>
                            </g>
                        );
                    } else if (i < j) {
                        plot = (
                            <ScatterPlot
                                cellID={cellID}
                                xPos={xPos}
                                yPos={yPos}
                                size={plotSize}

                                attrX={xCol}
                                attrY={yCol}
                                errorColors={errorColors}
                                detailMode="compact"
                            />
                        );
                    } else {
                        plot = (
                            <HeatMap
                                cellID={cellID}
                                xPos={xPos}
                                yPos={yPos}
                                size={plotSize}

                                attrX={xCol}
                                attrY={yCol}
                                errorColors={errorColors}
                                detailMode="compact"
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
export default function MatrixView({ selectedAttributes, onFocusChange }) {
    const svgRef = useRef(null);

    const [w, setW] = React.useState(800);
    const [h, setH] = React.useState(600);
    const [contentHeight, setContentHeight] = React.useState(null);

    // Measure the workspace container (not the SVG itself) so setting an
    // explicit SVG height for scrolling doesn't feed back into the measurement.
    useEffect(() => {
        const container = svgRef.current?.parentElement;
        if (!container) return;

        const measure = () => {
            const bbox = container.getBoundingClientRect();
            setW(bbox.width || 800);
            setH(bbox.height || 600);
        };

        const resizeObserver = new ResizeObserver(measure);
        resizeObserver.observe(container);
        measure();

        return () => resizeObserver.disconnect();
    }, []);

    const svgHeight = contentHeight == null ? "100%" : Math.max(contentHeight, h);

    return (
        <svg ref={svgRef} id="main-svg" width={"100%"} height={svgHeight} overflow="visible">
            <SelectionPanel
                selectedAttributes={selectedAttributes}
                w={w}
                h={h}
                errorColors={errorColors}
                onFocusChange={onFocusChange}
                setContentHeight={setContentHeight}
            />
        </svg>
    );
}
