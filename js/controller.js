class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container);
      this.selectedAttributes = data.columnNames().slice(1).sort().slice(0,3); // Store selected columns
      this.xCol = null;
      this.yCol = null;
      this.viewGroupsButton = false;

    //   this.updateSelectedAttributes(this.selectedAttributes);
      this.setupEventListeners();
      this.updateLegend(this.model.getGroupByAttribute()); 
    }

    // Update the 1-3 columns the user selects
    updateSelectedAttributes(attributes) {
        this.selectedAttributes = ["ID", ...attributes];
        this.model.setFilteredData(this.model.getFullData().select(this.selectedAttributes)); 
        this.render(false, true);
    }

    // Update the 1 group by attribute the user selects
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

    // Pop up window for avg aggregations
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
        // const overallStdDev = overallStats.stdDev;
        const overallMedian = overallStats.median;

        const absDeviationTable = fullTable.derive({
            absDeviation: aq.escape(d => Math.abs(d.ConvertedSalary - overallMedian))
        });
        
        const madStats = absDeviationTable.rollup({
            mad: aq.op.median("absDeviation")
        }).objects()[0];

        const overallMad = madStats.mad;

        // const upperBound = overallAvg + 2 * overallStdDev;
        // const lowerBound = overallAvg - 2 * overallStdDev;

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
  
    render(selectionEnabled, animate, handleBrush, handleBarClick, handleHeatmapClick) {
        if(selectionEnabled)
        {
            this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, animate, this.handleBrush.bind(this), this.handleBarClick.bind(this), this.handleHeatmapClick.bind(this));
        }
        else{
            this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, animate);
        }
    }

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

        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.updatePreviews(selectedPoints, groupByAttribute, column);

        const selectionEnabled = true;
        this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups(), selectionEnabled, false, this.handleBrush.bind(this), this.handleBarClick.bind(this), this.handleHeatmapClick.bind(this));

        barX0 = barData.x0;
        barX1 = barData.x1;
        selectedBar = barData;
    }

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

        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.updatePreviews(selectedPoints, groupByAttribute, xCol, yCol);

        const selectionEnabled = true;
        this.render(selectionEnabled, false);        
        // this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this), this.model.getGroupByAttribute());
    }

    handleGroupSelection() {
        const selectedGroups = Array.from(document.querySelectorAll("#boxplot-container input[type=checkbox]:checked"))
                                    .map(cb => cb.value);
        console.log("Selected groups:", selectedGroups);
        this.model.setSelectedGroups(selectedGroups, this.selectedAttributes);
    }
  
    setupEventListeners() {
        d3.selectAll("input[name='legend-toggle']").on("change", () => {
            const selectedValue = d3.select("input[name='legend-toggle']:checked").node().value;
            this.updateLegendContent(selectedValue, this.model.getGroupByAttribute());
        });

        const getActiveController = () => {
            return activeDataset === "practice" ? practiceController : stackoverflowController;
        };

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

                const activeController = getActiveController();
                activeController.updateSelectedAttributes(controller.selectedAttributes); // renders

                activeController.view.populateDropdownFromTable(activeController.model.getFullData(), activeController);

                attachButtonEventListeners();
            });
        });

        const selectGroupsBtn = document.getElementById("select-groups-btn");
        if (selectGroupsBtn) {
            selectGroupsBtn.addEventListener("click", this.openGroupSelectionPopup.bind(this));
        }
    }

    updatePreviews(selectedPoints, groupByAttribute, xCol, yCol){
        const currData = this.model.getData();

        if (selectedPoints.length === 0) {
            document.getElementById("preview-remove").style.display = "none";
            document.getElementById("preview-impute-average-x").style.display = "none";
            document.getElementById("preview-impute-average-y").style.display = "none";
            return;
        }
    
        let isHistogram = false;
        if(!yCol)   isHistogram = true;
        const removedData = this.model.getPreviewData((row) => !selectedPoints.some((point) => point.ID === row.ID));
        console.log("removedData", removedData);
        this.view.drawPreviewPlot(removedData, "preview-remove", isHistogram, groupByAttribute, xCol, yCol);
    
        const imputedXData = this.model.previewAverage(xCol);
        console.log("imputedXData", imputedXData);
        this.view.drawPreviewPlot(imputedXData, "preview-impute-average-x", isHistogram, groupByAttribute, xCol, yCol);
    
        if(yCol){
            const imputedYData = this.model.previewAverage(yCol);
            console.log("imputedYData", imputedYData);
            this.view.drawPreviewPlot(imputedYData, "preview-impute-average-y", isHistogram, groupByAttribute, xCol, yCol);
        }
        else{
            document.getElementById("preview-impute-average-y").style.display = "none";
        }
    }

    updateLegend(groupByAttribute) {
        this.updateLegendContent("errors", groupByAttribute);
    }

    updateLegendContent(type, groupByAttribute) {
        const legendContainer = d3.select("#legend-content");
        legendContainer.selectAll(".legend-item").remove();

        if (type === "errors") {
            const errorTypes = ["Missing Values", "Type Errors", "Data Type Mismatch", "Average Anomalies (Outliers)"];
            const errorColors = d3.scaleOrdinal()
                .domain(errorTypes)
                .range(["gray", "pink", "orange", "red"]);

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

function attachButtonEventListeners(){
    d3.select("#undo").on("click", null);
    d3.select("#redo").on("click", null);
    d3.select("#clear-selection").on("click", null);
    d3.select("#remove-selected-data").on("click", null);
    d3.select("#impute-average-x").on("click", null);
    d3.select("#impute-average-y").on("click", null);

     const getActiveController = () => {
        return activeDataset === "practice" ? practiceController : stackoverflowController;
    };

    d3.select("#undo").on("click", () => {
        const controller = getActiveController();
        console.log("Controller undo: ", controller);
        controller.model.undoLastTransformation();
        // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#redo").on("click", () => {
        const controller = getActiveController();
        controller.model.redoLastTransformation();
        // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
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

        const controller = getActiveController();
        controller.view.setSelectedPoints([]);
        // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
        const selectionEnabled = true;
        const animate = false;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, animate, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#remove-selected-data").on("click", () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        const controller = getActiveController();
        const selectedPoints = controller.model.getSelectedPoints();
        controller.model.filterData((row) => !selectedPoints.some((point) => point.ID === row.ID));

        // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, true, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#impute-average-x").on("click", () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        const controller = getActiveController();
        controller.model.imputeAverage(controller.xCol);
        controller.view.setSelectedPoints([]);
        // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, true, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    d3.select("#impute-average-y").on("click", () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        const controller = getActiveController();
        controller.model.imputeAverage(controller.yCol);
        controller.view.setSelectedPoints([]);
        // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute(), controller.model.getSelectedGroups(), selectionEnabled, true, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.handleHeatmapClick.bind(controller));
    });

    const radioButtons = document.querySelectorAll("input[name='options']");

    radioButtons.forEach((radio) => {
        radio.addEventListener("change", (event) => {
            const controller = getActiveController();
            if (event.target.value === "selectData" && event.target.checked) {
                const selectionEnabled = true;
                controller.render(selectionEnabled, false);
                // controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
            } else {
                const selectionEnabled = false;
                const animate = true;
                controller.render(selectionEnabled, animate);
            }
        });
    });
}

    
       