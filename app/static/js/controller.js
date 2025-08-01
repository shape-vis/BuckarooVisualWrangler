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
    updateGrouping(attributes, groupByAttribute) {
        console.log("User selected group by:", this.selectedAttributes, attributes);

        this.model.setGroupByAttribute(groupByAttribute);

        // const selectedColumns = new Set([...this.selectedAttributes]);
        // if (attribute && !selectedColumns.has(attribute)) {
        //     selectedColumns.add(attribute);
        // }

        this.selectedAttributes = ["ID", ...attributes];
        if (groupByAttribute) {
            this.selectedAttributes.push(groupByAttribute);
        }

        console.log("Selected columns after grouping:", this.selectedAttributes);

        // this.model.setFilteredData(this.model.getFullData().select([...attributes]));
        this.model.setFilteredData(this.model.getFullData().select(this.selectedAttributes));
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
            this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute());
        }
        else{
            this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute());
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
        this.view.plotMatrix(this.model.getData(), this.model.getGroupByAttribute());
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
        // d3.selectAll("input[name='legend-toggle']").on("change", () => {
        //     const selectedValue = d3.select("input[name='legend-toggle']:checked").node().value;
        //     this.updateLegendContent(selectedValue, this.model.getGroupByAttribute());
        // });

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



    updateLegend(groupByAttribute) {
        this.updateLegendContent("errors", groupByAttribute);
    }

    /**
     * Updates the Visual Encoding Options box. If new error detectors are added, they need to be added to the legend here.
     * @param {*} type 
     * @param {*} groupByAttribute 
     */
    updateLegendContent(type, groupByAttribute) {

    }

}

/**
 * Handler for user clicks in the Data Repair Toolkit. Calls logic for running data wranglers and re-plots the new dataset.
 * @param {*} controller 
 */
async function attachButtonEventListeners(controller){


    d3.select("#remove-selected-data").on("click", async () => {

        console.log("current selection: ", selectionControlPanel.currentSelection)

        console.log("current table: ", localStorage.getItem("table"))

        try{
            const payload = {
            currentSelection: selectionControlPanel.currentSelection,
            cols:  [selectionControlPanel.viewParameters[4], selectionControlPanel.viewParameters[5]],
            table:           localStorage.getItem("table"),
            // selected_sample: localStorage.getItem("selectedSample") // keep / drop as needed
            };

            const response = await fetch("/api/wrangle/remove", {
            method : "POST",
            headers: { "Content-Type": "application/json" },
            body   : JSON.stringify(payload),
            });

            const data = await response.json();
            console.log(data['new_table_name'])
            localStorage.setItem("table", data['new_table_name'])
            window.location.reload()
        }
        catch (error){
            console.error(error.message)
        }



        return

        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        //get the selected points that the user clicked on the matrix, can be a single point or many
        const selectedPoints = controller.model.getSelectedPoints();
        const loc = window.location.href;
        const dir = loc.substring(0, loc.lastIndexOf('/'));
        const module = await import(dir+"/static/wranglers/removeData.js");
        const condition = module.default(selectedPoints);
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
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute());
    });

    d3.select("#impute-average-x").on("click", async () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        const selectedPoints = controller.model.getSelectedPoints();
        const loc = window.location.href;
        const dir = loc.substring(0, loc.lastIndexOf('/'));
        const module = await import(dir+"/static/wranglers/imputeAverage.js");
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
        // controller.view.setSelectedPoints([]);
        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute() );
    });

    d3.select("#impute-average-y").on("click", async () => {
        document.getElementById("preview-remove").style.display = "none";
        document.getElementById("preview-impute-average-x").style.display = "none";
        document.getElementById("preview-impute-average-y").style.display = "none";
        document.getElementById("preview-user-function").style.display = "none";

        const selectedPoints = controller.model.getSelectedPoints();
        const loc = window.location.href;
        const dir = loc.substring(0, loc.lastIndexOf('/'));
        const module = await import(dir+"/static/wranglers/imputeAverage.js");
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
        // controller.view.setSelectedPoints([]);
        await controller.model.runDetectors(controller.detectors);
        controller.view.updateDirtyRowsTable(controller.model.getFullFilteredData());
        controller.view.updateColumnErrorIndicators(controller.model.getFullFilteredData(), controller);
        const selectionEnabled = true;
        controller.view.plotMatrix(controller.model.getData(), controller.model.getGroupByAttribute() );
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