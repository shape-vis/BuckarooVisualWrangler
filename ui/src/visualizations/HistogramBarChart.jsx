import React, {useEffect, useRef} from "react";
import * as d3 from "d3";
import { queryHistogram1d } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";

/**
 * HistogramBarChart renders a stacked histogram with optional brushing/selection.
 *
 * @param {Object} props
 * @param {string|number} props.cellID - Unique cell identifier for keyed rendering.
 * @param {{x: number, y: number}} props.pos - Top-left position for the chart group.
 * @param {{w: number, h: number}} props.size - Dimensions of the chart area.
 * @param {string} props.table_name - Backend table name for histogram query.
 * @param {string} props.attrX - Attribute/column name for histogramming.
 * @param {function} [props.errorColors] - Optional color lookup by error name.
 */
export default function HistogramBarChart({
    cellID,
    pos,
    size,
    table_name,
    attrX,
    errorColors,
}) {

    const drawingRef = useRef(null);
    const clearSelectionRef = useRef(() => {});

    const [histogramData, setHistogramData] = React.useState(null);

    useEffect(() => {

        // Fetch histogram data for the selected table/attribute.
        /**
         * Fetch histogram data for the selected table/attribute.
         * @returns {Promise<void>}
         */
        async function fetchData(){
            try {
                const response = await queryHistogram1d(table_name, attrX, 10 );

                if (!response || !response.Success) {
                    throw new Error(`API failed: ${response?.Error || "Unknown error"}`);
                }

                setHistogramData(response.histogram);

            } catch (err) {
                console.error("[HistogramBarChart] " + (err?.message || err));
            }
        }

        fetchData();

    }, [table_name, attrX]);


    useEffect(() => {

        // Build the chart once data arrives (scales, bars, brush, tooltips).
        if (!histogramData ) return;

        const canvas = d3.select(drawingRef.current);
        canvas.selectAll("*").remove();

        // Split histogram bins by numeric vs categorical.
        const numHistDataX = histogramData.scaleX.numeric || [];
        const catHistDataX = histogramData.scaleX.categorical || [];

        const numHistDataY = (numHistDataX.length === 0 || !numHistDataX[0]) ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
        const catHistDataY = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);


        // Build hybrid x-scale for numeric/categorical axes.
        const xScale = createHybridScales( size.w, numHistDataX, catHistDataX, numHistDataY, catHistDataY, "horizontal" );

        // y-scale for counts.
        const yScale = d3.scaleLinear()
            .domain([0, d3.max(histogramData.histograms, d => d.count.items)]).nice()
            .range([size.h, 0]);

        const colorScale =  errorColors || (k => "steelblue");




        // Flatten stacked data per bin for easier rendering.
        const myData = [];
        histogramData.histograms.forEach(d => {
            let items = d.count.items;

            Object.keys(d.count).filter(k => k !== "items").forEach(key => {
                myData.push({
                    bin: d.xBin,
                    type: d.xType,
                    value: d.count[key],
                    name: key,
                    top: items,
                    bottom: items - d.count[key],
                });
                items -= d.count[key];
            });

            if (items > 0) {
                myData.push({
                    bin: d.xBin,
                    type: d.xType,
                    value: items,
                    name: "none",
                    top: items,
                    bottom: 0,
                });
            }
        });

        console.log("[HistogramBarChart] Transformed histogram data for bars:", myData);

        let selected = [];
        const barColor = d => (selected.includes(d) ? "gold" : colorScale(d.name));

        // Brush layer for selection.
        const brushGroup = canvas.append("g")
            .attr("class", "histogram-brush");

        // Draw bars
        const bars = canvas.append("g")
            .selectAll("rect")
            .data(myData)
            .join("rect")
            .attr("x", d => xScale.apply(d.type === "numeric" ? numHistDataX[d.bin].x0 : d.bin, d.type))
            .attr("y", d => yScale(d.top))
            .attr("height", d => Math.max(0, yScale(d.bottom) - yScale(d.top)))
            .attr("width", d => d.type === "numeric" ? xScale.numericalBandwidth(numHistDataX[d.bin].x0, numHistDataX[d.bin].x1) : xScale.categoricalBandwidth())
            .attr("fill", barColor)
            .attr("stroke", "white")
            .attr("cursor", "pointer")
            .attr("stroke-width", 2);

        // console.log("[HistogramBarChart] Bars created:", bars.size());

        // Horizontal brush interaction.
        const brush = d3.brushX()
            .extent([[0, 0], [size.w, size.h]])
            .on("brush end", (event) => {
                if (!event.selection) {
                    selected = [];
                    bars.attr("fill", barColor);
                    return;
                }

                const [x0, x1] = event.selection;
                const brushedItems = myData.filter(d => {
                    if (d.type === "numeric") {
                        const bin = numHistDataX[d.bin];
                        if (!bin) return false;
                        const start = xScale.apply(bin.x0, "numeric");
                        const end = xScale.apply(bin.x1, "numeric");
                        return end >= x0 && start <= x1;
                    }

                    const start = xScale.apply(d.bin, "categorical");
                    const end = start + xScale.categoricalBandwidth();
                    return end >= x0 && start <= x1;
                });

                if (event.sourceEvent && event.sourceEvent.shiftKey) {
                    brushedItems.forEach(d => {
                        if (!selected.includes(d)) selected.push(d);
                    });
                } else {
                    selected = brushedItems;
                }

                bars.attr("fill", barColor);
            });

        brushGroup.call(brush);
        brushGroup.lower();

        // Expose a clear-selection action to parent handlers.
        clearSelectionRef.current = () => {
            selected = [];
            bars.attr("fill", barColor);
            brushGroup.call(brush.move, null);
        };


        // Draw xScale if it has a draw method (from original helper) otherwise skip
        if (xScale && typeof xScale.draw === "function") xScale.draw(canvas);

        // Draw axes
        canvas.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

        // Wire up tooltips and click selection.
        createTooltip(bars,
            d => {
                const bin = d.type === "numeric" ? `${Math.round(numHistDataX[d.bin].x0)}-${Math.round(numHistDataX[d.bin].x1)}` : d.bin;
                return `<strong>Bin: </strong>${bin}<br><strong>Items: </strong>${d.value}<br><strong>Errors: </strong>${d.name}`;
            },
            (d, event) => {
                // if (selectionControlPanel && typeof selectionControlPanel.clearSelection === "function") {
                //   selectionControlPanel.clearSelection(canvas);
                // }

                if (event.shiftKey) {
                    if (selected.includes(d)) selected = selected.filter(item => item !== d);
                    else selected.push(d);
                } else {
                    selected = [d];
                }

                bars.attr("fill", barColor);

                // if (selectionControlPanel && typeof selectionControlPanel.setSelection === "function") {
                //   selectionControlPanel.setSelection(svg, "barchart", [model, view, svg, givenData, xCol], {
                //     data: selected,
                //     scaleX: histogramData.scaleX,
                //     scaleY: histogramData.scaleY,
                //   }, () => {
                //     console.log("Selection cleared");
                //     selected = [];
                //     bars.attr("fill", barColor);
                //   });
                // }

            },
            (d) => {
                console.log("Right click on bar", d);
            },
            (d) => {
                console.log("Double click on bar", d);
            }
        );

        // Cleanup when dependencies change.
        return () => { canvas.selectAll("*").remove(); };


    }, [size, histogramData ]);



    /**
     * Clear any active brush selection and restore default colors.
     * @returns {void}
     */
    // Clear selection on background click.
    function clearSelection() {
        clearSelectionRef.current();
    }


    return (
        <g key={cellID} transform={`translate(${pos.x}, ${pos.y})`} className="barchart-canvas">
            <rect width={size.w} height={size.h} fill="#ffffff00" onClick={clearSelection}  />
            <g ref={drawingRef}></g>
        </g>
    );
}
