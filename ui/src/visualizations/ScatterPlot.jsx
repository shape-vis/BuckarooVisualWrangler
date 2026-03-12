import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { querySample2d } from "../utils/serverCalls.jsx";
import {SelectionContext} from "../utils/SelectionContext.jsx";

/**
 * Props expected:
 * - model
 * - view
 * - givenData
 * - xCol
 * - yCol
 * - createHybridScales
 * - createBackgroundBox
 * - createSelectionBox
 * - createTooltip
 * - selectionControlPanel
 * - generatePattern
 */
export default function ScatterPlot({
  cellID,
  xPos,
  yPos,
  size,
  table_name,
  attrX,
  attrY,
  errorColors,
  errorSampleCount = 300,
  totalSampleCount = 1000,
}) {
  const drawingRef = useRef(null);
  const [sampleData, setSampleData] = React.useState(null);

  useEffect(() => {

    async function fetchData(){
        try {


          const response = await querySample2d( table_name, attrX, attrY, errorSampleCount, totalSampleCount );          
          console.log("[SCATTERPLOT] Response:", response);

          if (!response || !response.Success) {
            console.error("[SCATTERPLOT] API call failed:", response);
            throw new Error(`2D ScatterPlot API failed: ${response?.Error || "Unknown error"}`);
          }

          const sampleData = response.scatterplot_data
          if (!sampleData) {
            console.error("[SCATTERPLOT] No scatter data in response:", response);
            throw new Error("No scatterplot data returned from server");
          }

          setSampleData(sampleData);

        } catch (err) {
          console.error(err?.message || err);
        }
      }

      fetchData();

  }, [table_name, attrX, attrY, errorSampleCount, totalSampleCount]);
  
  
      
  useEffect(() => {

        if (!sampleData) return;
  
        const canvas = d3.select(drawingRef.current);
        canvas.selectAll("*").remove();

        const colorScale = errorColors || (() => "steelblue");

        const numHistDataX = sampleData.scaleX.numeric || [];
        const catHistDataX = sampleData.scaleX.categorical || [];
        const numHistDataY = sampleData.scaleY.numeric || [];
        const catHistDataY = sampleData.scaleY.categorical || [];

        const xScale = createHybridScales(
              size,
              numHistDataX,
              catHistDataX,
              numHistDataX.length === 0 ? null : numHistDataX,
              catHistDataX.length === 0 ? null : catHistDataX.map(d => d),
              "horizontal"
            );

        const yScale = createHybridScales(
              size,
              numHistDataY,
              catHistDataY,
              numHistDataY.length === 0 ? null : numHistDataY,
              catHistDataY.length === 0 ? null : catHistDataY.map(d => d),
              "vertical"
            );       

        xScale.draw(canvas);
        yScale.draw(canvas);            

        // selection box helper
        // const selectionBox = createSelectionBox ? createSelectionBox(canvas) : null;

        let selectedData = [];

        const circleFill = d => {
          if (selectedData.includes(d)) return "gold";
          if (!d.errors || d.errors.length === 0) return colorScale("none");
          if (d.errors.length === 1) return colorScale(d.errors[0]);
          if (typeof generatePattern === "function") return generatePattern(view.svg, colorScale, d.errors);
          return colorScale(d.errors[0]);
        };

        const circles = canvas.selectAll("circle")
          .data(sampleData.data || [])
          .join("circle")
          .attr("cx", d => xScale ? xScale.apply(d.x, d.xType, true) : 0)
          .attr("cy", d => yScale ? yScale.apply(d.y, d.yType, true) : 0)
          .attr("r", 4)
          .attr("fill", circleFill);

  //       // background drag for selection
  //       if (backgroundBox && selectionBox) {
  //         backgroundBox.call(d3.drag()
  //           .on("start", function (event) {
  //             if (selectionControlPanel && typeof selectionControlPanel.clearSelection === "function") selectionControlPanel.clearSelection(canvas);
  //             selectionBox.start(event.x, event.y);
  //           })
  //           .on("drag", function (event) {
  //             selectionBox.update(event.x, event.y);
  //             selectedData = (sampleData.data || []).filter(d => selectionBox.inRange(xScale.apply(d.x, d.xType), yScale.apply(d.y, d.yType)));
  //             circles.attr("fill", circleFill);
  //           })
  //           .on("end", function (event) {
  //             selectionBox.end(event.x, event.y);
  //             if (selectionControlPanel && typeof selectionControlPanel.setSelection === "function") {
  //               selectionControlPanel.setSelection(canvas, "scatterplot", [model, view, canvas, givenData, xCol, yCol], {
  //                 data: selectedData,
  //                 scaleX: sampleData.scaleX,
  //                 scaleY: sampleData.scaleY,
  //               }, () => {
  //                 selectedData = [];
  //                 circles.attr("fill", circleFill);
  //               });
  //             }
  //           }));
  //       }

        // tooltip interactions
          createTooltip(circles,
            d => {
              const bin = String(d.x) + " x " + String(d.y);
              let errorList = "";
              if (d.errors && d.errors.length >= 1) errorList = "<br><strong>Errors: </strong>" + d.errors[0];
              if (d.errors && d.errors.length > 1) d.errors.slice(1).forEach(key => { errorList += `, ${key}`; });
              return `<strong>Data:</strong> ${bin}${errorList}`;
            },
            (d, event) => {
              console.log("Left click on point", d);
            },
            (d) => {
              console.log("Right click on point", d);
            },
            (d) => {
              console.log("Double click on point", d);
            }
          );

    return () => { canvas.selectAll("*").remove(); };

  }, [ size, sampleData ]);


  function clearSelection() {
    console.log("Clicked on heatmap background", event);    
    selected = [];
    tiles.attr("fill", tileFill);
  }





  return (
    <g key={cellID} transform={`translate(${xPos}, ${yPos})`} className="scatter-canvas">
        <rect width={size} height={size} fill="#ffffff00" onClick={ clearSelection}  />
        <g ref={drawingRef}></g>
    </g>
    );  
}
