
visualizations = {};

(async () => {
  try {
    const visualizationsResponse = await fetch('visualizations/visualizations.json');
    let visualizationData = await visualizationsResponse.json();

    for (const visualization of visualizationData) {
      
      const loc = window.location.href;
      const dir = loc.substring(0, loc.lastIndexOf('/'));
      console.log("loading visualization", loc, visualization.name, "from", visualization.code);
      visualization.module = await import(dir + visualization.code);
      visualizations[visualization.name] = visualization
    }
    console.log("visualizations", visualizations);
    // console.log("visualizations", visualizations);

  } catch (err) {
    console.error("Failed to load or run visualizations:", err);
  }
})();







class ScatterplotMatrixView{
    constructor(container, model) {

        this.matrixView = new MatrixView(container, model);
        this.tableView = new TableView(container, model);
        this.attributeSummaryView = new AttributeSummaryView(container, model);

        this.container = container;
        this.model = model;

        this.size = 180;                                                        // Size of each cell in matrix
        // this.xPadding = 175;
        // this.yPadding = 90;
        // this.labelPadding = 60;

        // this.leftMargin = 115;
        // this.topMargin = 0;
        // this.bottomMargin = 125; 
        // this.rightMargin = 0; 

        this.xScale = d3.scaleLinear().domain([0, 100]).range([0, this.size]);  // Default xScale to be changed within plotting code
        this.yScale = d3.scaleLinear().domain([0, 100]).range([this.size, 0]);  // Default yScale to be changed within plotting code

        this.selectedPoints = [];                                               // The current user selection of points from interacting with the plots
        this.predicatePoints = [];                                              // Predicate points do not meet the user's predicate condition and are outlined in red
        this.viewGroupsButton = false;                                          // True when the user has selected an attribute to group by and the legend will update to show group colors instead of error colors

        this.errorColors = {                                                    // To be updated as new error detectors are added
            "mismatch": "hotpink",
            "missing": "saddlebrown",
            "anomaly": "red",
            "incomplete": "gray"
        };

        this.errorPriority = ["anomaly", "mismatch", "missing", "incomplete"];  // Preference given to which errors are highlighted if both are present in a row
    }

    /**
     * Set which points fit the user-defined predicate. (Outlined in red)
     * @param {*} points 
     */
    setPredicatePoints(points) {
        this.predicatePoints = points;
    }


    /**
     * Populates the list of columns in the "Select Attributes" dropdown menu. Also initially populates the Attribute Summaries box.
     * @param {*} table Data
     * @param {*} controller 
     */
    populateDropdownFromTable(table, controller) {

        console.log("Populating dropdown from table:", table, controller);
        // const dropdownMenu = document.getElementById("dropdown-menu");
        // const dropdownButton = document.getElementById("dropdown-button");
        // const groupDropdown = document.getElementById("group-dropdown");
        const predicateDropdown = document.getElementById("predicate-dropdown");
    
        // dropdownMenu.innerHTML = ""; 
        // groupDropdown.innerHTML = '<option value="">None</option>'; 
        predicateDropdown.innerHTML = '<option value="">None</option>'; 

        // let selectedAttributes = new Set();
    
        const attributes = table.columnNames().slice(1).sort();
    

        /*****************************/
        /*****************************/
        /*****************************/
        /*****************************/
        this.attributeSummaryView.populateDropdownFromTable(table, controller);
        /*****************************/
        /*****************************/
        /*****************************/
        /*****************************/

        
        attributes.forEach((attr, index) => {

            let predicateOption = document.createElement("option");
            predicateOption.value = attr;
            predicateOption.textContent = attr;
            predicateDropdown.appendChild(predicateOption);
        });
    

        predicateDropdown.addEventListener("change", () => {
            this.handlePredicateChange(table, controller);
        });
              
    }

    /**
     * Updates the Attribute Summaries as data is wrangled and if the user changes which error type to sort on.
     * @param {*} table 
     * @param {*} controller 
     * @returns If the container does not exist, else should just update the UI.
     */
    updateColumnErrorIndicators(table, controller) {
        this.attributeSummaryView.updateColumnErrorIndicators(table, controller);
    }

    /**
     * Populates the top 10 dirty rows table. Updates as the data is wrangled. Counts number of errors per row and displays in first column. Orders rows by most errors per row.
     * Highlights cells with the corresponding error color.
     * @param {*} data 
     * @returns 
     */
    updateDirtyRowsTable(data) {
        this.tableView.updateDirtyRowsTable(data);
    }      

    /**
     * Handles user input for adding predicates to a column. Predicated points are points that do not meet the condition provided by the user and are outlined in red. 
     * @param {*} table 
     * @param {*} controller 
     * @returns 
     */
    handlePredicateChange(table, controller) {
        const predicateDropdown = document.getElementById("predicate-dropdown");
        const conditionContainer = document.getElementById("condition-container"); 
        conditionContainer.innerHTML = ""; 

        const selectedColumn = predicateDropdown.value;
        if (!selectedColumn){
            controller.predicateFilter(selectedColumn);
            return;
        } 
   
        const columnData = table.column(selectedColumn);
        const isNumeric = columnData.every(value => !isNaN(value));
        const clearPredicateButton = document.createElement("button");
        clearPredicateButton.textContent = "Clear Predicate";
        clearPredicateButton.classList.add("clear-predicate-button"); 
        clearPredicateButton.addEventListener("click", () => {
            controller.predicateFilter(false); 
        });
    
        if (isNumeric) {
            const operatorDropdown = document.createElement("select");
            ["<", ">", "=", "!="].forEach(op => {
                let option = document.createElement("option");
                option.value = op;
                option.textContent = op;
                operatorDropdown.appendChild(option);
            });
    
            const valueInput = document.createElement("input");
            valueInput.type = "number";
    
            const applyButton = document.createElement("button");
            applyButton.textContent = "Apply";
            applyButton.classList.add("apply-filter-button"); 
            applyButton.addEventListener("click", () => {
                controller.predicateFilter(selectedColumn, operatorDropdown.value, valueInput.value, isNumeric);
            });

            conditionContainer.appendChild(operatorDropdown);
            conditionContainer.appendChild(valueInput);
            conditionContainer.appendChild(applyButton);
            conditionContainer.appendChild(clearPredicateButton);
            
        } else {
            const operatorDropdown = document.createElement("select");
            ["=", "!="].forEach(op => {
                let option = document.createElement("option");
                option.value = op;
                option.textContent = op;
                operatorDropdown.appendChild(option);
            });
    
            const valueDropdown = document.createElement("select");
            valueDropdown.classList.add("value-dropdown");
            const categories = sortCategories([...new Set(columnData)])
            categories.forEach(value => {
                let option = document.createElement("option");
                option.value = value;
                option.textContent = value;
                valueDropdown.appendChild(option);
            });
    
            conditionContainer.appendChild(operatorDropdown);
            conditionContainer.appendChild(valueDropdown);
            conditionContainer.appendChild(clearPredicateButton);
    
            valueDropdown.addEventListener("change", () => controller.predicateFilter(selectedColumn, operatorDropdown.value, valueDropdown.value, isNumeric));
            operatorDropdown.addEventListener("change", () => controller.predicateFilter(selectedColumn, operatorDropdown.value, valueDropdown.value, isNumeric));
        }
    }
    


    /**
     * Initial plotting code upon browser loading. Plots bar plots on diagonal and calls drawHeatMap to plot off-diagonal plots. Categorizes data for the bar plot as numeric or 
     * non-numeric and handles those cases separately. Within each case, plotting is handled separately when the group by function is active vs. when the data is not grouped. 
     * Each bar is colored by its error type, or is steelblue if no errors. Selected data is colored gold.
     * @param {*} givenData Data to visualize.
     * @param {*} groupByAttribute User selected group by attribute if active.
     */
    plotMatrix(givenData, groupByAttribute ) {  
        this.matrixView.plotMatrix(givenData, groupByAttribute);

    }


}

/**
 * Sorts categories for axis tick labels.
 * @param {*} categories 
 * @returns Sorted categories.
 */
function sortCategories(categories) {
    // Sorting logic for scale categories that are not alphabetical or numerical
    const scaleCategories = ['Low', 'Medium', 'High'];

    if (scaleCategories.every(cat => categories.includes(cat))) {
        return scaleCategories;  
    }

    // Sorting logic for alphabetical and numerical categories
    return categories
        .filter(d => d !== undefined && d !== null)  
        .sort((a, b) => {
            const numA = parseInt(a.match(/^\d+/)?.[0]);
            const numB = parseInt(b.match(/^\d+/)?.[0]);

            if (!isNaN(numA) && !isNaN(numB)) {
                return numA - numB;
            } else if (!isNaN(numA)) {
                return -1; 
            } else if (!isNaN(numB)) {
                return 1;
            } else {
                return a.localeCompare(b); 
            }
        });
}


/**
 * Truncates text to be used on axis labels, attribute summaries, and cells in the top 10 dirty data table.
 * @param {*} text 
 * @param {*} maxLength 
 * @returns The truncated text.
 */
function truncateText(text, maxLength = 17) {
    if (typeof text !== "string") return text;
    return text.length > maxLength ? text.slice(0, maxLength - 3) + "..." : text;
  }

