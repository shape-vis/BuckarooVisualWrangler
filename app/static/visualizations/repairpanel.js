


class SelectionControlPanel {
    
    constructor() {
        this.selectionView = null;                // The current selection view, if any
        this.currentSelection = null;                   // The current selection of points in the plots
        this.deselectionCallback = null;                // Callback to be called when the user deselects points in the plots
        this.selectViewType = null;                  // The type of the current selection view (e.g., "scatterplot", "barchart", etc.)
        this.viewParameters = null;            // Parameters for the current selection view

        this.size = 260; // Default size for the repair panel
        this.leftMargin = 60;
        this.topMargin = 5;
        this.rightMargin = 5;
        this.bottomMargin = 50;


        this.errorTypes = {"total": "Total Error %",
                            "missing": "Missing Values", 
                            "mismatch": "Data Type Mismatch", 
                            "anomaly": "Average Anomalies (Outliers)", 
                            "incomplete": "Incomplete Data (< 3 points)", 
                            "none": "None"};

                this.errorColors = d3.scaleOrdinal()
                                .domain(Object.keys(this.errorTypes))
                                .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);     
        // this.errorColors = null
    }


    clearSelection(view) {
        if( view !== this.selectionView && this.deselectionCallback ){
            this.deselectionCallback();
        }
        this.currentSelection = null;
        // document.getElementById("zoom-data").disabled = true;
        // document.getElementById("repair-data").disabled = true;
    }

    setSelection( view, viewType, viewParameters, selection, deselectionCallback ){
        this.selectionView = view;
        this.currentSelection = selection;
        this.deselectionCallback = deselectionCallback;
        this.selectViewType = viewType;
        this.viewParameters = viewParameters;
        // document.getElementById("zoom-data").disabled = false;
        // document.getElementById("repair-data").disabled = false;
    }

    drawControls(svg, x, y ){

        const repairGroup = svg.append("g")
            .attr("class", "svg-legend")
            .attr("transform", `translate(${x},${y})`);

        repairGroup.append("rect")
            .attr("width", 195)
            .attr("height", 145)
            .attr("stroke", "black")
            .attr("rx", 5)
            .attr("ry", 5)
            .attr("fill", "none")

        repairGroup.append("text")
            .attr("x", 5 + 195 / 2)
            .attr("y", 20)
            .attr("font-weight", "bold")
            .attr("font-size", "14px")
            .attr("text-anchor", "middle")
            .text("Repair Panel");    

        let repairSelection = repairGroup.append("g")
            .attr("transform", "translate(30, 30)")
            .on("click", function() {
                console.log("Repair Selection clicked");
                selectionControlPanel.plotRepairPanel();
            });

        repairSelection.append("rect")
            .attr("class", "svgButton")

        repairSelection.append("text")
            .attr("x", 70)
            .attr("y", 14)
            .attr("class", "svgButtonText")
            .text("⚒️ Repair Selection");

        let zoomGroup = repairGroup.append("g")
            .attr("transform", "translate(30, 70)")
            .on("click", function() {
                console.log("Zoom Selection clicked");
            });

        zoomGroup.append("rect")
            .attr("class", "svgButton");

        zoomGroup.append("text")
            .attr("x", 70)
            .attr("y", 14)
            .attr("class", "svgButtonText")
            .text("🔍 Zoom Selection");

        let undoGroup = repairGroup.append("g")
            .attr("transform", "translate(10, 110)");

        undoGroup.append("rect")
            .attr("class", "svgButton")
            .style("width", "80px")

        undoGroup.append("text")
            .attr("x", 40)
            .attr("y", 14)
            .attr("class", "svgButtonText")
            .text("↩️ Undo");
            
        let redoGroup = repairGroup.append("g")
            .attr("transform", "translate(105, 110)");   
        redoGroup.append("rect")
            .attr("class", "svgButton")
            .style("width", "80px")

        redoGroup.append("text")
            .attr("x", 40)
            .attr("y", 14)
            .attr("class", "svgButtonText")
            .text("🔁 Redo");
    }





    plotRepairPanel() {

        const size = 260;


        console.log("Plotting repair panel");
        const toolboxObject = document.getElementsByClassName("toolbox-wrapper")[0];
        toolboxObject.style.display = "flex"; // Show the toolbox if it was hidden
        
        
        const preview_area = d3.select("#preview-area")

        preview_area.selectAll("*").remove(); // Clear previous content

        const repair_methods = [
            { name: "Remove Data"  },
            { name: "Impute Mean X" },
            { name: "Impute Mean Y" }
        ];
        
        // Create a new SVG element for the repair panel

        repair_methods.forEach(method => {
            preview_area
                .append("div")
                .attr("class", "repair-method")
                .html(`<strong>${method.name}</strong> [ Apply ]`);

            const plotSize = Math.min(size - this.leftMargin - this.rightMargin, size - this.topMargin - this.bottomMargin);
            const svg = preview_area
                            .append("svg")
                            .attr("width", size)
                            .attr("height", size);

            const canvas = svg.append("g")
                                .attr("transform", `translate(${this.leftMargin}, ${this.topMargin})`);

            const view = {svg: svg, size: plotSize, errorColors: this.errorColors};

            if( this.selectViewType === "barchart" ){
                visualizations['barchart'].module.draw(this.viewParameters[0], view, canvas, ...this.viewParameters.slice(3),true);
            } 
            else if (this.selectViewType === "scatterplot") {  
                visualizations['scatterplot'].module.draw(this.viewParameters[0], view, canvas, ...this.viewParameters.slice(3));
            } else if (this.selectViewType === "heatmap") {
                visualizations['heatmap'].module.draw(this.viewParameters[0], view, canvas, ...this.viewParameters.slice(3));
            }
        });

    }
}



const selectionControlPanel = new SelectionControlPanel();

