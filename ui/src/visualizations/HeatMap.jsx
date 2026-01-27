// Heatmap.jsx
import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import { queryHistogram2d } from "../utils/serverCalls.jsx";
import { createHybridScales, createTooltip } from "../utils/visCommon.jsx";

/**
 * Props:
 *  - model
 *  - view
 *  - givenData
 *  - xCol
 *  - yCol
 *  - createHybridScales (function)
 *  - createBackgroundBox (function)
 *  - createTooltip (function)
 *  - selectionControlPanel (object with setSelection / clearSelection)
 *  - generatePattern (function) => (svg, colorScale, keys) returns a pattern/paint for mixed keys
 */
export default function Heatmap({
  cellID,
  xPos,
  yPos,
  size,
  table_name,
  attrX,
  attrY,
  errorColors
}) {
  const drawingRef = useRef(null);
  const [histogramData, setHistogramData] = React.useState(null);

  useEffect(() => {

    async function fetchData(){
        try {

          const response = await queryHistogram2d(table_name, attrX, attrY, 0, 10000, 10 );
          console.log("[HEATMAP] Response:", response);

          if (!response || !response.Success) {
            console.error("[HEATMAP] API call failed:", response);
            throw new Error(`2D Histogram API failed: ${response?.Error || "Unknown error"}`);
          }

          setHistogramData(response.histogram);

        } catch (err) {
          console.error(err?.message || err);
        }
      }

      fetchData();

  }, [table_name, attrX, attrY]);

      
  useEffect(() => {

        if (!histogramData ) return;
  

          const numHistDataX = histogramData.scaleX.numeric || [];
          const catHistDataX = histogramData.scaleX.categorical || [];
          const numHistDataY = histogramData.scaleY.numeric || [];
          const catHistDataY = histogramData.scaleY.categorical || [];

          const numDomainX = (numHistDataX.length === 0 || !numHistDataX[0]) ? null : [d3.min(numHistDataX, d => d.x0), d3.max(numHistDataX, d => d.x1)];
          const catDomainX = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);

          const numDomainY = (numHistDataY.length === 0 || !numHistDataY[0]) ? null : [d3.min(numHistDataY, d => d.x0), d3.max(numHistDataY, d => d.x1)];
          const catDomainY = catHistDataY.length === 0 ? null : catHistDataY.map(d => d);     
          
          console.log("[HEATMAP] Domains:", { numDomainX, catDomainX, numDomainY, catDomainY });

          // create scales with your helper (horizontal/vertical flag preserved)
          const xScale = createHybridScales(size, numHistDataX, catHistDataX, numDomainX, catDomainX, "horizontal");
          const yScale = createHybridScales(size, numHistDataY, catHistDataY, numDomainY, catDomainY, "vertical");


          const drawingGroup = d3.select(drawingRef.current);
          drawingGroup.selectAll("*").remove();

          xScale.draw(drawingGroup);
          yScale.draw(drawingGroup);          

          // filter out empty bins
          const binsToRender = histogramData.histograms.filter(d => d.count.items > 0);


          const colorScale = errorColors || (() => "steelblue");

          // selection state local to this draw
          let selected = [];
          // determines fill for a tile; supports no errors, single error, or multiple (pattern)
          const tileFill = (d) => {
            if (selected.includes(d)) return "gold";
            const keys = Object.keys(d.count).filter(k => k !== "items");
            if (keys.length === 0) return colorScale("none");
            if (keys.length === 1) return colorScale(keys[0]);
            // generatePattern should return a paint id or CSS fill (e.g., pattern URL)
            // if (typeof generatePattern === "function") {
            //   return generatePattern(svg, colorScale, keys);
            // }
            // fallback: use first key color
            return colorScale(keys[0]);
          };          

          // draw rects
          const tiles = drawingGroup.append("g")
            .attr("class", "heatmap-tiles")
            .selectAll("rect")
            .data(binsToRender)
            .join("rect")
            .attr("x", d => {
              return xScale.apply(d.xType === "numeric" ? xScale.numHistData[d.xBin].x0 : d.xBin, d.xType);
            })
            .attr("y", d => {
              // yScale.apply expects the top coordinate for that bin; original used x1 for numeric
              return yScale.apply(d.yType === "numeric" ? yScale.numHistData[d.yBin].x1 : d.yBin, d.yType);
            })
            .attr("height", d => {
              return d.yType === "numeric"
                ? yScale.numericalBandwidth(yScale.numHistData[d.yBin].x1, yScale.numHistData[d.yBin].x0)
                : yScale.categoricalBandwidth();
            })
            .attr("width", d => {
              return d.xType === "numeric"
                ? xScale.numericalBandwidth(xScale.numHistData[d.xBin].x0, xScale.numHistData[d.xBin].x1)
                : xScale.categoricalBandwidth();
            })
            .attr("fill", tileFill)
            .attr("stroke", "white")
            .attr("cursor", "pointer")
            .attr("stroke-width", 1);     
  
          createTooltip(
            tiles,
            d => {
              const xBin = d.xType === "numeric"
                ? `${Math.round(numHistDataX[d.xBin].x0)}-${Math.round(numHistDataX[d.xBin].x1)}`
                : d.xBin;
              const yBin = d.yType === "numeric"
                ? `${Math.round(numHistDataY[d.yBin].x0)}-${Math.round(numHistDataY[d.yBin].x1)}`
                : d.yBin;
              let errorList = "";
              Object.keys(d.count).forEach(key => {
                if (key === "items") return;
                errorList += `<br> - ${key}: ${d.count[key]}`;
              });
              if (errorList !== "") errorList = "<br><strong>Errors: </strong> " + errorList;
              return `<strong>Bin:</strong> ${xBin} x ${yBin}<br><strong>Items: </strong>${d.count.items}${errorList}`;
            },
            (d, event) => {
              // left click handler
              // if (selectionControlPanel && typeof selectionControlPanel.clearSelection === "function") {
              //   selectionControlPanel.clearSelection(svg);
              // }

              console.log("Left click on heatmap bin", d, event);
              if (event.shiftKey) {
                if (selected.includes(d)) selected = selected.filter(item => item !== d);
                else selected.push(d);
              } else {
                selected = [d];
              } 
              tiles.attr("fill", tileFill);

              // if (selectionControlPanel && typeof selectionControlPanel.setSelection === "function") {
              //   selectionControlPanel.setSelection(canvas, "heatmap", [model, view, canvas, givenData, xCol, yCol], {
              //     data: selected,
              //     scaleX: histData.scaleX,
              //     scaleY: histData.scaleY,
              //   }, () => {
              //     selected = [];
              //     tiles.attr("fill", tileFill);
              //   });
              // }
            },
            (d) => {
              console.log("Right click on heatmap bin", d);
            },
            (d) => {
              console.log("Double click on heatmap bin", d);
            }
          );                        
          
    return () => { drawingGroup.selectAll("*").remove(); };
          

  }, [size, histogramData ]);

  function clearSelection() {
    console.log("Clicked on heatmap background", event);    
    selected = [];
    tiles.attr("fill", tileFill);
  }





  return (
    <g key={cellID} transform={`translate(${xPos}, ${yPos})`} className="heatmap-canvas">
        <rect width={size} height={size} fill="#ffffff00" onClick={ clearSelection}  />
        <g ref={drawingRef}></g>
    </g>
    );
}