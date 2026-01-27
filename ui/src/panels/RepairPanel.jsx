import React, { useEffect } from "react";
import * as d3 from "d3";
import CollapsiblePanel from "../elements/CollapsiblePanel.jsx";

import "./RepairPanel.css";

/**
 * React wrapper that reproduces the behavior of the original SelectionControlPanel class
 * from your uploaded file. It exposes a global `window.selectionControlPanel` object for
 * backward compatibility (so other non-React modules can call setSelection / clearSelection).
 *
 * Props (all optional):
 *  - visualizations: object mapping names to { module: { draw: fn } } (used to render previews)
 *  - initAttachToDocument: boolean (default true) - if true the component will attach click handlers to
 *    elements with ids repairButton, zoomButton, undoButton, redoButton just like the original.
 */
export default function RepairPanel({ visualizations = window.visualizations || {}, initAttachToDocument = true }) {
  // useEffect(() => {
  //   // Internal state stored in a plain object so other non-React code can use it via window.selectionControlPanel
  //   const state = {
  //     selectionView: null,
  //     currentSelection: null,
  //     deselectionCallback: null,
  //     selectViewType: null,
  //     viewParameters: null,

  //     size: 260,
  //     leftMargin: 60,
  //     topMargin: 5,
  //     rightMargin: 5,
  //     bottomMargin: 50,

  //     errorTypes: { total: "Total Error %", missing: "Missing Values", mismatch: "Data Type Mismatch", anomaly: "Average Anomalies (Outliers)", incomplete: "Incomplete Data (< 3 points)", none: "None" },
  //     errorColors: d3.scaleOrdinal().domain(["total", "missing", "mismatch", "anomaly", "incomplete", "none"]).range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]),
  //   };

  //   function clearSelection(view) {
  //     if (view !== state.selectionView && typeof state.deselectionCallback === "function") {
  //       state.deselectionCallback();
  //     }
  //     state.currentSelection = null;
  //   }

  //   function setSelection(view, viewType, viewParameters, selection, deselectionCallback) {
  //     state.selectionView = view;
  //     state.currentSelection = selection;
  //     state.deselectionCallback = deselectionCallback;
  //     state.selectViewType = viewType;
  //     state.viewParameters = viewParameters;
  //   }

  //   async function applyRepair(methodName) {
  //     const table = localStorage.getItem("selectedSample")?.split('/').pop().replace('.csv', '');

  //     try {
  //       const cols = [state.viewParameters[4], state.viewParameters[5]];
  //       const isRemove = methodName === "Remove Data";
  //       const endpoint = isRemove ? "/api/wrangle/remove" : "/api/wrangle/impute";

  //       const payload = { currentSelection: state.currentSelection, cols: cols, table: table };
  //       if (!isRemove) {
  //         payload.col = methodName === "Impute Mean X" ? cols[0] : cols[1];
  //       }

  //       const response = await fetch(endpoint, {
  //         method: "POST",
  //         headers: { "Content-Type": "application/json" },
  //         body: JSON.stringify(payload),
  //       });

  //       const data = await response.json();

  //       if (!response.ok || !data.success) {
  //         alert("Error: " + (data?.error || `Server error ${response.status}`));
  //         return;
  //       }

  //       window.location.reload();
  //     } catch (error) {
  //       console.error(error);
  //       alert("Error: " + error.message);
  //     }
  //   }

  //   function plotRepairPanel() {
  //     const size = 200;
  //     const preview_area = d3.select("#preview-area");
  //     if (preview_area.empty()) {
  //       // If there is no preview-area in the DOM, create a minimal one and append to body
  //       d3.select("body").append("div").attr("id", "preview-area").style("padding", "8px");
  //     }

  //     const area = d3.select("#preview-area");
  //     area.selectAll(".repair-method").remove();

  //     const repair_methods = [{ name: "Remove Data" }, { name: "Impute Mean X" }, { name: "Impute Mean Y" }];

  //     repair_methods.forEach(method => {
  //       const div = area.append("div").attr("class", "repair-method").style("margin-bottom", "8px");
  //       div.append("strong").text(method.name);
  //       div.append("span").text(" [ Apply ]").style("cursor", "pointer").style("color", "#4CAF50").on("click", () => applyRepair(method.name));
  //       div.append("br");

  //       const plotSize = Math.min(size - state.leftMargin - state.rightMargin, size - state.topMargin - state.bottomMargin);
  //       const svg = div.append("svg").attr("width", size).attr("height", size);
  //       const canvas = svg.append("g").attr("transform", `translate(${state.leftMargin}, ${state.topMargin})`);
  //       const view = { svg: svg, plotSize: plotSize, errorColors: state.errorColors };

  //       // Render a small preview of the current selection using the appropriate visualization
  //       if (state.selectViewType === "barchart" && visualizations['barchart']) {
  //         visualizations['barchart'].module.draw(state.viewParameters[0], view, canvas, ...state.viewParameters.slice(3), true);
  //       } else if (state.selectViewType === "scatterplot" && visualizations['scatterplot']) {
  //         visualizations['scatterplot'].module.draw(state.viewParameters[0], view, canvas, ...state.viewParameters.slice(3));
  //       } else if (state.selectViewType === "heatmap" && visualizations['heatmap']) {
  //         visualizations['heatmap'].module.draw(state.viewParameters[0], view, canvas, ...state.viewParameters.slice(3));
  //       } else {
  //         // If no matching visualization found, render a simple message
  //         canvas.append("text").attr("x", 10).attr("y", 20).text("No preview available");
  //       }
  //     });
  //   }

  //   // Expose a backward-compatible object on window for other scripts
  //   const exposed = {
  //     clearSelection,
  //     setSelection,
  //     plotRepairPanel,
  //     applyRepair,
  //     // also expose state for inspection
  //     _internalState: state,
  //   };

  //   window.selectionControlPanel = exposed;

  //   // Attach document listeners similar to the original file
  //   let repairListener = null;
  //   let zoomListener = null;
  //   let undoListener = null;
  //   let redoListener = null;

  //   if (initAttachToDocument) {
  //     repairListener = (e) => {
  //       if (e.target.id === "repairButton" || e.target.closest && e.target.closest("#repairButton")) {
  //         plotRepairPanel();
  //       }
  //     };
  //     document.addEventListener("click", repairListener);

  //     zoomListener = () => console.log("Zoom Selection clicked");
  //     undoListener = () => console.log("Undo Selection clicked");
  //     redoListener = () => console.log("Redo Selection clicked");

  //     const zoomButton = document.getElementById("zoomButton");
  //     const undoButton = document.getElementById("undoButton");
  //     const redoButton = document.getElementById("redoButton");

  //     if (zoomButton) zoomButton.addEventListener("click", zoomListener);
  //     if (undoButton) undoButton.addEventListener("click", undoListener);
  //     if (redoButton) redoButton.addEventListener("click", redoListener);
  //   }

  //   // Cleanup on unmount
  //   return () => {
  //     if (initAttachToDocument && repairListener) document.removeEventListener("click", repairListener);
  //     if (initAttachToDocument) {
  //       const zoomButton = document.getElementById("zoomButton");
  //       const undoButton = document.getElementById("undoButton");
  //       const redoButton = document.getElementById("redoButton");
  //       if (zoomButton && zoomListener) zoomButton.removeEventListener("click", zoomListener);
  //       if (undoButton && undoListener) undoButton.removeEventListener("click", undoListener);
  //       if (redoButton && redoListener) redoButton.removeEventListener("click", redoListener);
  //     }
  //     // remove global reference
  //     if (window.selectionControlPanel === exposed) delete window.selectionControlPanel;
  //   };
  // }, [visualizations, initAttachToDocument]);

  // // Render nothing (we operate on a global #preview-area div), but include a fallback preview-area
  // return (
  //   <div>
  //     <div id="preview-area" />
  //   </div>
  // );

  return (
    <CollapsiblePanel direction="right" collapsed={"Data Repair Panel"} defaultOpen={false} style={{ height: "100%", margin: "0px 0" }}>
      <div id="toolbox">
        <div style={{fontWeight: "bold", marginLeft: "auto", marginRight: "auto", marginTop: "10px", marginBottom: "10px"}}>Data Repair Panel</div>
          <div className="repair-tools">
            <div id="repairButton" className="regButton" style={{width:"130px"}}>⚒️ Repair Selection</div>
              <div id="zoomButton" className="regButton" style={{width:"130px", marginLeft: "25px", marginRight: "25px"}}>🔍 Zoom Selection</div>
              <div id="undoButton" className="regButton" style={{width:"65px"}}>↩️ Undo</div>
              <div id="redoButton" className="regButton" style={{width:"65px"}}>🔄 Redo</div>
          </div>
          <div id="preview-area" className="toolbox-preview-area">
        
          </div>
      </div>
    </CollapsiblePanel>
  );
}
