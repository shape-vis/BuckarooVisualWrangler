class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container);
      this.selectedAttributes = []; // Store selected columns
      this.xCol = null;
      this.yCol = null;

      this.render();
      this.setupEventListeners();
    }

    // Update the 1-3 columns the user selects
    updateSelectedAttributes(attributes) {
        this.selectedAttributes = ["ID", ...attributes];
        this.model.setFilteredData(this.model.getFullData().select(this.selectedAttributes)); 
        this.render();
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
        this.render();
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
            this.render();
            popup.style.display = "none";
        };

        document.getElementById("close-popup").onclick = () => {
            popup.style.display = "none";
        };
      }
  
    render() {
        this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute(), this.model.getSelectedGroups());
    }
  
    handleBrush(event, xScale, yScale, categoricalXScale, categoricalYScale, xCol, yCol) {
        document.getElementById("impute-average-x").textContent = `Impute average for ${xCol}`;
        document.getElementById("impute-average-y").textContent = `Impute average for ${yCol}`;
        this.xCol = xCol;
        this.yCol = yCol
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
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this), this.model.getGroupByAttribute());
    }
  
    handleBarClick(event, barData, column, groupByAttribute) {
        console.log("Bar data: ", barData);
        document.getElementById("impute-average-x").textContent = `Impute average for ${column}`;
        document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";

        this.xCol = column;
        let selectedPoints = [];

        if(groupByAttribute)
        {
            const groupKey = barData.group;
            selectedPoints = this.model.getData().objects().filter(d => barData.data[`${groupKey}_ids`].includes(d.ID));        
        }
        else{
            selectedPoints = this.model.getData().objects().filter(d => barData.ids.includes(d.ID));
        }

        console.log("Selected bar points:", selectedPoints);

        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this), this.model.getGroupByAttribute());

        barX0 = barData.x0;
        barX1 = barData.x1;
        selectedBar = barData;
    }

    handleGroupSelection() {
        const selectedGroups = Array.from(document.querySelectorAll("#boxplot-container input[type=checkbox]:checked"))
                                    .map(cb => cb.value);
        console.log("Selected groups:", selectedGroups);
        this.model.setSelectedGroups(selectedGroups, this.selectedAttributes);
    }
  
    setupEventListeners() {
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
                activeController.render();

                activeController.view.populateDropdownFromTable(activeController.model.getFullData(), activeController);

                attachButtonEventListeners();
            });
        });

        const selectGroupsBtn = document.getElementById("select-groups-btn");
        if (selectGroupsBtn) {
            selectGroupsBtn.addEventListener("click", this.openGroupSelectionPopup.bind(this));
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
        controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
    });

    d3.select("#redo").on("click", () => {
        const controller = getActiveController();
        controller.model.redoLastTransformation();
        controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
    });

    d3.select("#clear-selection").on("click", () => {
        document.getElementById("impute-average-x").textContent = "Impute selected data with average for X";
        document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";
        const controller = getActiveController();
        controller.view.setSelectedPoints([]);
        controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
    });

    d3.select("#remove-selected-data").on("click", () => {
        const controller = getActiveController();
        const selectedPoints = controller.model.getSelectedPoints();
        controller.model.filterData((row) => !selectedPoints.some((point) => point.ID === row.ID));
        controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
    });

    d3.select("#impute-average-x").on("click", () => {
        const controller = getActiveController();
        controller.model.imputeAverage(controller.xCol);
        controller.view.setSelectedPoints([]);
        controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
    });

    d3.select("#impute-average-y").on("click", () => {
        const controller = getActiveController();
        controller.model.imputeAverage(controller.yCol);
        controller.view.setSelectedPoints([]);
        controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
    });

    const radioButtons = document.querySelectorAll("input[name='options']");

    radioButtons.forEach((radio) => {
        radio.addEventListener("change", (event) => {
            const controller = getActiveController();
            if (event.target.value === "selectData" && event.target.checked) {
                controller.view.enableBrushing(controller.model.getData(), controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller), controller.model.getGroupByAttribute());
            } else {
                controller.render();
            }
        });
    });
}

    
       