class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container, this.model);
      this.selectedAttributes = data.columnNames().slice(1).sort().slice(0,3); // Store selected columns
      this.xCol = null;
      this.yCol = null;
      this.viewGroupsButton = false;                                           // True when the user has selected an attribute to group by and the legend will update to show group colors instead of error colors
      this.detectors = null;
      this.wranglers = null;

      this.setupEventListeners();
    }

    /**
     * Initialization of the controller runs error detectors and renders everything in the UI.
     * @param {*} detectors
     * @param {*} wranglers
     * @param errorData
     */
    async init(detectors, wranglers,errorData) {
        this.detectors = detectors;
        this.wranglers = wranglers;

        // await this.model.runDetectors(detectors);
        this.model.columnErrorMap = errorData;
        this.view.updateDirtyRowsTable(this.model.getFullFilteredData());

        this.view.populateDropdownFromTable(this.model.getFullData(), this);

        this.updateSelectedAttributes(this.model.getFullData().columnNames().slice(1).sort().slice(0,3));

        this.updateLegend(this.model.getGroupByAttribute());
      }

    /**
     * Update the 1-3 attributes the user selects to view.
     * @param {*} attributes 
     */
    updateSelectedAttributes(attributes) {
        this.selectedAttributes = ["ID", ...attributes];
        this.model.setFilteredData(this.model.getFullData().select(this.selectedAttributes)); 
        this.render(true, true);
    }

    /**
     * Update the user-selected attribute to group by.
     * @param {*} attribute 
     */
    updateGrouping(attribute) {
        console.log("User selected group by:", attribute);
        
        this.model.setGroupByAttribute(attribute); 

        const selectedColumns = new Set([...this.selectedAttributes]); 
        if (attribute && !selectedColumns.has(attribute)) {
            selectedColumns.add(attribute);  
        }

        this.model.setFilteredData(this.model.getFullData().select([...selectedColumns]));
        this.render(false, true);
    }

    /**
     * Pop up window for box plots and group selection.
     * @returns 
     */
    openGroupSelectionPopup() {
        const groupBy = this.model.getGroupByAttribute();
        if (!groupBy) return;

        const fullTable = this.model.getFullData();

        const overallStats = fullTable.rollup({ 
            overallAvg: aq.op.mean("ConvertedSalary"),
            stdDev: aq.op.stdev("ConvertedSalary"),
            median: aq.op.median("ConvertedSalary"),
        }).objects()[0];

        const overallAvg = overallStats.overallAvg;
        const overallMedian = overallStats.median;

        const absDeviationTable = fullTable.derive({
            absDeviation: aq.escape(d => Math.abs(d.ConvertedSalary - overallMedian))
        });
        
        const madStats = absDeviationTable.rollup({
            mad: aq.op.median("absDeviation")
        }).objects()[0];

        const overallMad = madStats.mad;

        const upperBound = overallMedian + 2 * overallMad;
        const lowerBound = overallMedian - 2 * overallMad;

        // Compute box plot statistics for each group
        const groupStatsTable = fullTable.groupby(groupBy).rollup({
            min: aq.op.min("ConvertedSalary"),
            q1: aq.op.quantile("ConvertedSalary", 0.25),
            median: aq.op.median("ConvertedSalary"),
            q3: aq.op.quantile("ConvertedSalary", 0.75),
            max: aq.op.max("ConvertedSalary"),
            mean: aq.op.mean("ConvertedSalary")
        });
        
        const groupStats = groupStatsTable.objects().map(d => ({
            group: d[groupBy],
            min: d.min,
            q1: d.q1,
            median: d.median,
            q3: d.q3,
            max: d.max,
            mean: d.mean
        }));

        console.log(groupStats);
        console.log(overallMedian);
        console.log("upper", upperBound);
        console.log("lower", lowerBound);

        const significantGroups = groupStats.filter(d => d.median > upperBound || d.median < lowerBound);

        const popup = document.getElementById("group-selection-popup");
        popup.innerHTML = `
            <h3>Group Salary Distributions</h3>
            <div id="boxplot-container"></div> 
            <button id="plot-groups">Plot Selected Groups</button>
            <button id="close-popup">Cancel</button>
        `;

        popup.style.display = "block";

        // Use the view to draw box plots
        this.view.drawBoxPlots(groupStats, () => this.handleGroupSelection(), overallMedian, this.model.getSelectedGroups(), significantGroups);

        document.getElementById("plot-groups").onclick = () => {
            const selected = Array.from(document.querySelectorAll("#boxplot-container input[type=checkbox]:checked"))
                                .map(cb => cb.value);

            this.model.setSelectedGroups(selected, this.selectedAttributes);
            this.render(false, true);
            popup.style.display = "none";
        };

        document.getElementById("close-popup").onclick = () => {
            popup.style.display = "none";
        };
      }
  
    /**
     * Calls the view to do plotMatrix.
     * @param {*} selectionEnabled 
     * @param {*} animate 
     */
    render(selectionEnabled, animate) {
        if(selectionEnabled)
        {
            this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, animate, this.handleBrush.bind(this), this.handleBarClick.bind(this), this.handleHeatmapClick.bind(this));
        }
        else{
            this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, animate);
        }
    }

    /**
     * Set the predicate points according to the user's predicates.
     * @param {*} column 
     * @param {*} operator 
     * @param {*} value 
     * @param {*} isNumeric 
     */
    predicateFilter(column, operator, value, isNumeric)
    {
        let predicatePoints = [];
        if(column){
            if (isNumeric){
                this.model.getData().objects().forEach(row => {
                    const cellValue = row[column];
            
                    let conditionMet = false;
                    switch (operator) {
                        case "<": conditionMet = cellValue < value; break;
                        case ">": conditionMet = cellValue > value; break;
                        case "=": conditionMet = cellValue === value; break;
                        case "!=": conditionMet = cellValue !== value; break;
                    }
            
                    if (!conditionMet) predicatePoints.push(row);
                });
            }
            else {
                this.model.getData().objects().forEach(row => {
                    const cellValue = row[column];
            
                    let conditionMet = false;
                    switch (operator) {
                        case "=": conditionMet = cellValue === value; break;
                        case "!=": conditionMet = cellValue !== value; break;
                    }
            
                    if (!conditionMet) predicatePoints.push(row);
                });
            }
        }
        
        this.view.setPredicatePoints(predicatePoints);

        const selectionEnabled = false;
        this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, this.handleBrush.bind(this), this.handleBarClick.bind(this), this.handleHeatmapClick.bind(this));
    }
  
    /**
     * Not currently used, but handles user selections on the scatterplots using brushing.
     * @param {*} event 
     * @param {*} xScale 
     * @param {*} yScale 
     * @param {*} categoricalXScale 
     * @param {*} categoricalYScale 
     * @param {*} xCol 
     * @param {*} yCol 
     * @returns 
     */
    handleBrush(event, xScale, yScale, categoricalXScale, categoricalYScale, xCol, yCol) {
        document.getElementById("impute-average-x").textContent = `Impute average for ${xCol}`;
        document.getElementById("impute-average-y").textContent = `Impute average for ${yCol}`;
        this.xCol = xCol;
        this.yCol = yCol;
        const selection = event.selection;

        if (!selection) return; 

        const [[x0, y0], [x1, y1]] = selection; 

        const selectedPoints = this.model.getData().objects().filter(d => {
            let xPos, yPos;

            if(categoricalXScale != null && categoricalYScale != null )
            {
                if (typeof d[xCol] === "number" && !isNaN(d[xCol]) && typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                    xPos = xScale(d[xCol]);
                    yPos = yScale(d[yCol]);
                } else if ((typeof d[xCol] !== "number" || isNaN(d[xCol])) && typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                    xPos = categoricalXScale(d[xCol]);
                    yPos = yScale(d[yCol]);
                } else if ((typeof d[xCol] === "number" && !isNaN(d[xCol])) && (typeof d[yCol] !== "number" || isNaN(d[yCol]))) {
                    xPos = xScale(d[xCol]);
                    yPos = categoricalYScale(d[yCol]);
                } else {
                    xPos = categoricalXScale(d[xCol]);
                    yPos = categoricalYScale(d[yCol]);
                }
            }
            else if(categoricalXScale != null)
            {
                if (typeof d[xCol] === "number" && !isNaN(d[xCol])) {
                    xPos = xScale(d[xCol]);
                }
                else {
                    xPos = categoricalXScale(d[xCol]);
                }

                yPos = yScale(d[yCol]);
            }
            else if(categoricalYScale != null)
            {
                if (typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                    yPos = yScale(d[yCol]);
                }
                else {
                    yPos = categoricalYScale(d[yCol]);
                }

                xPos = xScale(d[xCol]);
            }
            else
            {
                xPos = xScale(d[xCol]);
                yPos = yScale(d[yCol]);
            }
            

            return xPos >= x0 && xPos <= x1 && yPos >= y0 && yPos <= y1;
        });

        console.log("Scatter points:", selectedPoints);
               
        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.updatePreviews(selectedPoints, groupByAttribute, xCol, yCol);
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this), this.model.getGroupByAttribute());
    }
  
    /**
     * Handler for user clicks on histograms.
     * @param {*} event 
     * @param {*} barData 
     * @param {*} column 
     * @param {*} groupByAttribute 
     * @param {*} group 
     */
    handleBarClick(event, barData, column, groupByAttribute, group) {
        console.log("Bar data: ", barData);
        document.getElementById("impute-average-x").textContent = `Impute average for ${column}`;
        document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";

        this.xCol = column;
        let selectedPoints = [];

        if(groupByAttribute)
        {
            selectedPoints = this.model.getData().objects().filter(d => barData.data.groupIDs[group].includes(d.ID));     
        }
        else{
            selectedPoints = this.model.getData().objects().filter(d => barData.ids.includes(d.ID));
        }

        console.log("Selected bar points:", selectedPoints);
        //the selected points is the current user selection of points from interacting with the plots
        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.updatePreviews(selectedPoints, groupByAttribute, column);

        const selectionEnabled = true;
        this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, false, this.handleBrush.bind(this), this.handleBarClick.bind(this), this.handleHeatmapClick.bind(this));

        barX0 = barData.x0;
        barX1 = barData.x1;
        selectedBar = barData;
    }

    /**
     * Handler for user clicks on heatmaps.
     * @param {*} event 
     * @param {*} data 
     * @param {*} xCol 
     * @param {*} yCol 
     * @param {*} groupByAttribute 
     * @param {*} group 
     */
    handleHeatmapClick(event, data, xCol, yCol, groupByAttribute, group) {
        console.log("Heatmap data: ", data);
        document.getElementById("impute-average-x").textContent = `Impute average for ${xCol}`;
        document.getElementById("impute-average-y").textContent = `Impute for ${yCol}`;

        this.xCol = xCol;
        this.yCol = yCol;
        let selectedPoints = [];

        if(groupByAttribute)
        {
            selectedPoints = this.model.getData().objects().filter(d => data.ids[group].includes(d.ID));        
        }
        else{
            selectedPoints = this.model.getData().objects().filter(d => data.ids.includes(d.ID));
        }

        console.log("Selected heatmap points:", selectedPoints);

        //the selected points is the current user selection of points from interacting with the plots
        this.model.setSelectedPoints(selectedPoints);
        //current user selection of points from interacting with the plots
        this.view.setSelectedPoints(selectedPoints);

        this.updatePreviews(selectedPoints, groupByAttribute, xCol, yCol);

        const selectionEnabled = true;
        this.render(selectionEnabled, false);        
    }

    /**
     * Handler for user selection of groups through checkboxes in the boxplot pop up.
     */
    handleGroupSelection() {
        const selectedGroups = Array.from(document.querySelectorAll("#boxplot-container input[type=checkbox]:checked"))
                                    .map(cb => cb.value);
        console.log("Selected groups:", selectedGroups);
        this.model.setSelectedGroups(selectedGroups, this.selectedAttributes);
    }
  
    /**
     * Listens for user clicks switching between "View Errors" and "View Groups" in the Visual Encoding Options.
     */
    setupEventListeners() {
        d3.selectAll("input[name='legend-toggle']").on("change", () => {
            const selectedValue = d3.select("input[name='legend-toggle']:checked").node().value;
            this.updateLegendContent(selectedValue, this.model.getGroupByAttribute());
        });

        document.querySelectorAll(".tab-button").forEach(button => {
            button.addEventListener("click", function() {
                document.querySelectorAll(".tab-button").forEach(btn => btn.classList.remove("active"));
                this.classList.add("active");
    
                document.querySelectorAll(".tab-content").forEach(tab => {
                    tab.style.display = "none";
                });
    
                activeDataset = this.dataset.target === "tab2" ? "stackoverflow" : "practice";

                const targetTab = document.getElementById(this.getAttribute("data-target"));
                targetTab.style.display = "block";

                document.querySelector("input[name='options'][value='allData']").checked = true;
                document.getElementById("impute-average-x").textContent = "Impute selected data with average for X";
                document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";

                this.updateSelectedAttributes(this.selectedAttributes); // renders

                this.view.populateDropdownFromTable(this.model.getFullData(), this);

                attachButtonEventListeners(this);
            });
        });

        const selectGroupsBtn = document.getElementById("select-groups-btn");
        if (selectGroupsBtn) {
            selectGroupsBtn.addEventListener("click", this.openGroupSelectionPopup.bind(this));
        }
    }

    /**
     * Updates the preview plots of selected data by calling the view.
     * @param {*} selectedPoints 
     * @param {*} groupByAttribute 
     * @param {*} xCol 
     * @param {*} yCol 
     * @returns 
     */
    updatePreviews(selectedPoints, groupByAttribute, xCol, yCol){
        const currData = this.model.getData();

        if (selectedPoints.length === 0) {
            document.getElementById("preview-remove").style.display = "none";
            document.getElementById("preview-impute-average-x").style.display = "none";
            document.getElementById("preview-impute-average-y").style.display = "none";
            document.getElementById("preview-user-function").style.display = "none";
            return;
        }
    
        let isHistogram = false;
        if(!yCol)   isHistogram = true;
        const removedData = this.model.getPreviewData((row) => !selectedPoints.some((point) => point.ID === row.ID));
        console.log("removedData", removedData);
        this.view.drawPreviewPlot(removedData, currData, "preview-remove", isHistogram, groupByAttribute, xCol, yCol);
    
        const imputedXData = this.model.previewAverage(xCol);
        console.log("imputedXData", imputedXData);
        this.view.drawPreviewPlot(imputedXData, currData, "preview-impute-average-x", isHistogram, groupByAttribute, xCol, yCol);
    
        if(yCol){
            const imputedYData = this.model.previewAverage(yCol);
            console.log("imputedYData", imputedYData);
            this.view.drawPreviewPlot(imputedYData, currData, "preview-impute-average-y", isHistogram, groupByAttribute, xCol, yCol);
        }
        else{
            document.getElementById("preview-impute-average-y").style.display = "none";
        }

        /// Hard coded user repair function (removes all points with the average of xCol). This is not in wranglers.json ///

        const isNumeric = currData.array(xCol).some(v => typeof v === "number" && !isNaN(v));
        let xAvg = 0;

        /// Calculate numeric average ///
        if(isNumeric){
            const columnValues = currData.array(xCol).filter((v) => !isNaN(v) && v > 0);
            xAvg = columnValues.length > 0 
                ? parseFloat((columnValues.reduce((a, b) => a + b, 0) / columnValues.length).toFixed(1))
                : 0;           
        }
        /// Calculate categorical mode ///
        else{
            const frequencyMap = currData.array(xCol).reduce((acc, val) => {
                acc[val] = (acc[val] || 0) + 1;
                return acc;
            }, {});
    
            xAvg = Object.keys(frequencyMap).reduce((a, b) =>
                frequencyMap[a] > frequencyMap[b] ? a : b
            );   
        }

        const removedXAvg = currData.filter(aq.escape(d => d[xCol] !== xAvg));
        this.view.drawPreviewPlot(removedXAvg, currData, "preview-user-function", isHistogram, groupByAttribute, xCol, yCol);
    }

    updateLegend(groupByAttribute) {
        this.updateLegendContent("errors", groupByAttribute);
    }

    /**
     * Updates the Visual Encoding Options box. If new error detectors are added, they need to be added to the legend here.
     * @param {*} type 
     * @param {*} groupByAttribute 
     */
    updateLegendContent(type, groupByAttribute) {
        const legendContainer = d3.select("#legend-content");
        legendContainer.selectAll(".legend-item").remove();

        if (type === "errors") {
            const errorTypes = ["Missing Values", "Data Type Mismatch", "Average Anomalies (Outliers)", "Incomplete Data (< 3 points)", "Clean"];
            const errorColors = d3.scaleOrdinal()
                .domain(errorTypes)
                .range(["saddlebrown", "hotpink", "red", "gray", "steelblue"]);

            errorTypes.forEach(error => {
                const legendItem = legendContainer.append("div")
                    .attr("class", "legend-item");

                legendItem.append("span")
                    .attr("class", "legend-color")
                    .style("background-color", errorColors(error));

                legendItem.append("span")
                    .text(error);
            });

            if (this.viewGroupsButton) { 
                this.viewGroupsButton = false;
                this.view.setViewGroupsButton(false); 
                this.render(false, true);
            }

        } else if (type === "groups" && groupByAttribute) {
            console.log("Switching to group legend");
            const uniqueGroups = Array.from(new Set(this.model.getData().objects().map(d => d[groupByAttribute])));
            const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

            uniqueGroups.forEach(group => {
                const legendItem = legendContainer.append("div")
                    .attr("class", "legend-item");

                legendItem.append("span")
                    .attr("class", "legend-color")
                    .style("background-color", colorScale(group));

                legendItem.append("span")
                    .text(group);
            });

            if (!this.viewGroupsButton) { 
                this.viewGroupsButton = true;
                this.view.setViewGroupsButton(true);
                this.render(false, true);
            }
        }
    }

}

/**
     * The full pipeline test, view -> server -> db -> server -> view
     */
async function pipeline(){
    console.log("mon button pushed");
        const url = "/api/all"
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`Response status: ${response.status}`);
            }
                const jsonInfo = await response.json();
                let jsonText = JSON.stringify(jsonInfo);
                console.log(jsonInfo);
                console.log(jsonText);
                d3.select("#db-test-body").text(jsonText);
        } catch (error) {
                console.error(error.message);
            }
}


/**
 * Handler for user clicks in the Data Repair Toolkit. Calls logic for running data wranglers and re-plots the new dataset.
 * @param {*} controller 
 */
async function attachButtonEventListeners(controller){
    d3.select("#undo").on("click", null);
    d3.select("#redo").on("click", null);
    d3.select("#clear-selection").on("click", null);
    d3.select("#remove-selected-data").on("click", null);
    d3.select("#impute-average-x").on("click", null);
    d3.select("#impute-average-y").on("click", null);

    d3.select("#mon-button").on("click", async () => pipeline());

    d3.select("#undo").on("click", async () => {
        console.log("Controller undo: ", controller);
        controller.model.undoLastTransformation();
        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });


    d3.select("#redo").on("click", async () => {
        controller.model.redoLastTransformation();
        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#clear-selection").on("click", () => {
        document.getElementById("impute-average-x").textContent = "Impute selected data with average for X";
        document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        controller.view.setSelectedPoints([]);
        const selectionEnabled = true;
        const animate = false;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, animate, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#remove-selected-data").on("click", async () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        //get the selected points that the user clicked on the matrix, can be a single point or many
        const selectedPoints = controller.model.getSelectedPoints();
        //the remove data wrangler
        const module = await import("/static/wranglers/removeData.js");
        //the remove data wrangler returns a function which determines whether an id is in the selected one's
        const condition = module.default(selectedPoints);
        //gets the error map from the model
        const errorMap = controller.model.getColumnErrors();
        //initializes a map to keep track of any errors that are found in the selected points
        const selectedPointsErrors = {};
        //extracts just the id from the selected points, so they look like this: {1:1} - yeah doesn't make sense
        const selectedIDs = selectedPoints.map(d => d.ID);
        //loops through each of the points in the selectedIds map, checks to see
        selectedIDs.forEach(id => {
            const errors = [];

            // Check to see if the selected point is in the xCol
            if (errorMap[controller.xCol] && errorMap[controller.xCol][id]) {
            errors.push(...errorMap[controller.xCol][id]);
            }

            // Checks to see if the selected point is in the yCol
            if (errorMap[controller.yCol] && errorMap[controller.yCol][id]) {
            errors.push(...errorMap[controller.yCol][id]);
            }
            // the selected point should be added to the selectedPointsErrors dictionary based on the id as a key, and the error type as the value
            if (errors.length > 0) {
                selectedPointsErrors[id] = errors;
            }
        });

        controller.model.filterData(condition, {
            ids: selectedPoints.map(p => p.ID),
            xCol: controller.xCol,
            xVals: selectedPoints.map(p => p[controller.xCol]),
            yCol: controller.yCol,
            yVals: selectedPoints.map(p => p[controller.yCol]),
            imputedColumn: false,
            value: false,
            idErrors: selectedPointsErrors
          });

        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, true, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#impute-average-x").on("click", async () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        const selectedPoints = controller.model.getSelectedPoints();
        const module = await import("/static/wranglers/imputeAverage.js");
        const imputedValue = computeAverage(controller.xCol, controller.model.getData())
        const transformation = module.default(controller.xCol, controller.model.getData(), selectedPoints);
        const errorMap = controller.model.getColumnErrors();

        const selectedPointsErrors = {};
        const selectedIDs = selectedPoints.map(d => d.ID);

        selectedIDs.forEach(id => {
            const errors = [];

            // Check xCol
            if (errorMap[controller.xCol] && errorMap[controller.xCol][id]) {
            errors.push(...errorMap[controller.xCol][id]);
            }

            // Check yCol
            if (errorMap[controller.yCol] && errorMap[controller.yCol][id]) {
            errors.push(...errorMap[controller.yCol][id]);
            }

            if (errors.length > 0) {
                selectedPointsErrors[id] = errors;
            }
        });

        controller.model.transformData(controller.xCol, transformation, {
            ids: selectedPoints.map(p => p.ID),
            xCol: controller.xCol,
            xVals: selectedPoints.map(p => p[controller.xCol]),
            yCol: controller.yCol,
            yVals: selectedPoints.map(p => p[controller.yCol]),
            imputedColumn: controller.xCol,
            value: imputedValue,
            idErrors: selectedPointsErrors
          });
        controller.view.setSelectedPoints([]);
        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, true, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#impute-average-y").on("click", async () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        const selectedPoints = controller.model.getSelectedPoints();
        const module = await import("/static/wranglers/imputeAverage.js");
        const imputedValue = computeAverage(controller.yCol, controller.model.getData())
        const transformation = module.default(controller.yCol, controller.model.getData(), selectedPoints);
        const errorMap = controller.model.getColumnErrors();

        const selectedPointsErrors = {};
        const selectedIDs = selectedPoints.map(d => d.ID);

        selectedIDs.forEach(id => {
            const errors = [];

            // Check xCol
            if (errorMap[controller.xCol] && errorMap[controller.xCol][id]) {
            errors.push(...errorMap[controller.xCol][id]);
            }

            // Check yCol
            if (errorMap[controller.yCol] && errorMap[controller.yCol][id]) {
            errors.push(...errorMap[controller.yCol][id]);
            }

            if (errors.length > 0) {
                selectedPointsErrors[id] = errors;
            }
        });

        controller.model.transformData(controller.yCol, transformation, {
            ids: selectedPoints.map(p => p.ID),
            xCol: controller.xCol,
            xVals: selectedPoints.map(p => p[controller.xCol]),
            yCol: controller.yCol,
            yVals: selectedPoints.map(p => p[controller.yCol]),
            imputedColumn: controller.yCol,
            value: imputedValue,
            idErrors: selectedPointsErrors
          });
        controller.view.setSelectedPoints([]);
        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, true, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    const radioButtons = document.querySelectorAll("input[name='options']");

    radioButtons.forEach((radio) => {
        radio.addEventListener("change", (event) => {
            if (event.target.value === "selectData" && event.target.checked) {
                const selectionEnabled = true;
                controller.render(selectionEnabled, false);
            } else {
                const selectionEnabled = false;
                const animate = true;
                controller.render(selectionEnabled, animate);
            }
        });
    });
}     

/**
 * Computes numerical average or categorical mode for a column.
 * @param {*} column 
 * @param {*} table 
 * @returns The average or mode.
 */
function computeAverage(column, table){
    const isNumeric = table.array(column).some(v => typeof v === "number" && !isNaN(v));
  
    let imputedValue;
  
    /// Calculate numeric average ///
    if (isNumeric) {
      const columnValues = table.array(column).filter((v) => !isNaN(v) && v > 0);
      imputedValue = columnValues.length > 0
        ? parseFloat((columnValues.reduce((a, b) => a + b, 0) / columnValues.length).toFixed(1))
        : 0;
  
    }
    /// Calculate categorical mode ///
    else {
      const frequencyMap = table.array(column).reduce((acc, val) => {
        acc[val] = (acc[val] || 0) + 1;
        return acc;
      }, {});
  
      imputedValue = Object.keys(frequencyMap).reduce((a, b) =>
        frequencyMap[a] > frequencyMap[b] ? a : b
      );
    }
    return imputedValue;
}