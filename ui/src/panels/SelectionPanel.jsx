import React, {useEffect, useRef} from "react";
import * as d3 from "d3";
import HeatMap from "../visualizations/HeatMap.jsx";
import HistogramBarChart from "../visualizations/HistogramBarChart.jsx";
import ScatterPlot from "../visualizations/ScatterPlot.jsx";



function SelectionPanel({ table_name, selectedAttributes, w, h, errorTypes, errorColors }) {
  const matrixPlotAreaRef = useRef(null);
  const [plotSize, setPlotSize] = React.useState(180);

  const view = {
    xPadding: 85, yPadding: 70,
    leftMargin: 30, rightMargin: 10,
    topMargin: 50, bottomMargin: 0,
  };

  const columns = selectedAttributes || [];

  useEffect(() => {
    // console.log("SelectionPanel dimensions:", w, h);

    // adjust plotSize based on available space and number of columns
    const n = columns.length;
    if (n > 0) {
      let newPlotSize = Math.min((w - view.leftMargin - view.rightMargin) / n - view.xPadding, (h - view.topMargin - view.bottomMargin) / n - view.yPadding);
      newPlotSize = Math.max(40, newPlotSize); // ensure non-negative and reasonable minimum
      setPlotSize(newPlotSize);
    }
  }, [table_name, selectedAttributes, w, h]);

  return (
    <g ref={matrixPlotAreaRef} id="matrix-plot-area">
      <g>
        {
          columns.map((col, i) => {
            return (
              <text 
                x={view.leftMargin + (i+1) * view.xPadding + i * (plotSize) + plotSize / 2}
                y={view.topMargin - 10}
                textAnchor="middle">{col}</text>
            )
          })
        }
        {
          columns.map((col, i) => {
            return (
              <text
                x={view.leftMargin - 10}
                y={view.topMargin + i * (plotSize + view.yPadding) + plotSize / 2}
                transform={`rotate(-90, ${view.leftMargin - 10}, ${view.topMargin + i * (plotSize + view.yPadding) + plotSize / 2})`}
                textAnchor="middle">{col}</text>
            )
          })
        }
      </g>
      {
        columns.map((xCol, j) => {
          return columns.map((yCol, i) => {
            const cellID = `cell-${i}-${j}`;
            const xPos = view.leftMargin + (j+1) * view.xPadding + j * plotSize;
            const yPos = view.topMargin + i * (plotSize + view.yPadding);

            if (i === j) {
              // diagonal: bar chart
              return (<HistogramBarChart cellID={cellID} xPos={xPos} yPos={yPos} size={plotSize} table_name={table_name} attrX={xCol} errorColors={errorColors} />);
            } else if (i < j) {
              // upper: scatterplot
              return (<ScatterPlot cellID={cellID} xPos={xPos} yPos={yPos} size={plotSize} table_name={table_name} attrX={xCol} attrY={yCol} errorColors={errorColors} />);
            } else {
              // lower: heatmap
              return (<HeatMap cellID={cellID} xPos={xPos} yPos={yPos} size={plotSize} table_name={table_name} attrX={xCol} attrY={yCol} errorColors={errorColors} />);
            }  
          });
        })
      }
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

  const errorTypes = { total: "Total Error %", missing: "Missing Values", mismatch: "Data Type Mismatch", anomaly: "Average Anomalies (Outliers)", incomplete: "Incomplete Data (< 3 points)", none: "None" };
  const errorColors = d3.scaleOrdinal().domain(["total", "missing", "mismatch", "anomaly", "incomplete", "none"]).range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);

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
  }, [table_name, selectedAttributes]);

  return (
    <svg ref={svgRef} id="main-svg" width={"100%"} height={"100%"} style={{display: "block"}}>
      <SelectionPanel table_name={table_name} selectedAttributes={selectedAttributes} w={w} h={h} errorColors={errorColors} />
    </svg>
  );
}
