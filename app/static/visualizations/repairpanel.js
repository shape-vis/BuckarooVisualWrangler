


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
                            "incomplete": "Rarity (Low-Frequency Values)", 
                            "none": "None"};

                this.errorColors = d3.scaleOrdinal()
                                .domain(Object.keys(this.errorTypes))
                                .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);
        // this.errorColors = null

        // Use event delegation on document to handle clicks
        document.addEventListener("click", (e) => {
            if (e.target.id === "repairButton" || e.target.closest("#repairButton")) {
                console.log("Repair button clicked!");
                this.plotRepairPanel();
            }
        });
        document.getElementById("zoomButton").addEventListener("click", () => {
            console.log("Zoom Selection clicked");
        });
        document.getElementById("undoButton").addEventListener("click", () => {
            console.log("Undo Selection clicked");
        });
        document.getElementById("redoButton").addEventListener("click", () => {
            console.log("Redo Selection clicked");
        });
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




    plotRepairPanel() {

        const size = 200;

        console.log("=== plotRepairPanel called ===");
        console.log("Current selection:", this.currentSelection);
        console.log("View type:", this.selectViewType);
        // const toolboxObject = document.getElementsByClassName("toolbox-wrapper")[0];
        // toolboxObject.style.display = "flex"; // Show the toolbox if it was hidden
        
        
        const preview_area = d3.select("#preview-area")

        preview_area.selectAll(".repair-method").remove(); // Clear previous content

        const repair_methods = [
            { name: "Remove Data"  },
            { name: "Impute Mean X" },
            { name: "Impute Mean Y" }
        ];
        
        // Create a new SVG element for the repair panel

        repair_methods.forEach(method => {
            const div = preview_area
                            .append("div")
                            .attr("class", "repair-method");

            div.append("strong").text(method.name);
            div.append("span")
                .text(" [ Apply ]")
                .style("cursor", "pointer")
                .style("color", "#4CAF50")
                .on("click", () => this.applyRepair(method.name));
            div.append("br");

            const plotSize = Math.min(size - this.leftMargin - this.rightMargin, size - this.topMargin - this.bottomMargin);
            const svg = div
                            .append("svg")
                            .attr("width", size)
                            .attr("height", size);

            const canvas = svg.append("g")
                                .attr("transform", `translate(${this.leftMargin}, ${this.topMargin})`);

            const view = {svg: svg, plotSize: plotSize, errorColors: this.errorColors};

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

    async applyRepair(methodName) {
        const table = localStorage.getItem("selectedSample")?.split('/').pop().replace('.csv', '');

        try {
            const cols = [this.viewParameters[4], this.viewParameters[5]];
            const isRemove = methodName === "Remove Data";
            const endpoint = isRemove ? "/api/wrangle/remove" : "/api/wrangle/impute";

            const payload = { currentSelection: this.currentSelection, cols: cols, table: table };
            if (!isRemove) {
                payload.col = methodName === "Impute Mean X" ? cols[0] : cols[1];
            }

            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                alert("Error: " + (data?.error || `Server error ${response.status}`));
                return;
            }

            window.location.reload();
        } catch (error) {
            console.error(error);
            alert("Error: " + error.message);
        }
    }
}



const selectionControlPanel = new SelectionControlPanel();

