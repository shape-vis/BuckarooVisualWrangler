

visualizations = {};

(async () => {
  try {
    const visualizationsResponse = await fetch('visualizations/visualizations.json');
    let visualizationData = await visualizationsResponse.json();

    for (const visualization of visualizationData) {
      
      console.log("loading visualization", visualization.name, "from", visualization.code);
      visualization.module = await import(visualization.code);
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
        this.container = container;
        this.model = model;

        this.size = 180;                                                        // Size of each cell in matrix
        this.xPadding = 175;
        this.yPadding = 90;
        this.labelPadding = 60;

        this.leftMargin = 115;
        this.topMargin = 0;
        this.bottomMargin = 125; 
        this.rightMargin = 0; 

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
     * Set the user selected points.
     * @param {*} points 
     */
    setSelectedPoints(points) {
        this.selectedPoints = points;
      }

    /**
     * Set which points fit the user-defined predicate. (Outlined in red)
     * @param {*} points 
     */
    setPredicatePoints(points) {
        this.predicatePoints = points;
    }

    /**
     * This radio button should only be clickable if the user has selected a group by attribute.
     * @param {*} condition 
     */
    setViewGroupsButton(condition){
        this.viewGroupsButton = condition;
    }

    /**
     * Populates the list of columns in the "Select Attributes" dropdown menu. Also initially populates the Attribute Summaries box.
     * @param {*} table Data
     * @param {*} controller 
     */
    populateDropdownFromTable(table, controller) {
        const dropdownMenu = document.getElementById("dropdown-menu");
        const dropdownButton = document.getElementById("dropdown-button");
        const groupDropdown = document.getElementById("group-dropdown");
        const predicateDropdown = document.getElementById("predicate-dropdown");
    
        dropdownMenu.innerHTML = ""; 
        groupDropdown.innerHTML = '<option value="">None</option>'; 
        predicateDropdown.innerHTML = '<option value="">None</option>'; 

        let selectedAttributes = new Set();
    
        const attributes = table.columnNames().slice(1).sort();
    
        if (attributes.length >= 3) {
            selectedAttributes = new Set(attributes.slice(0, 3)); 
            controller.updateSelectedAttributes(Array.from(selectedAttributes)); 
        }
    
        let deselectAllButton = document.createElement("button");
        deselectAllButton.textContent = "Deselect All";
        deselectAllButton.classList.add("deselect-button");
        deselectAllButton.addEventListener("click", function (event) {
            event.preventDefault();
            selectedAttributes.clear();
            document.querySelectorAll("#dropdown-menu input[type='checkbox']").forEach(checkbox => {
                checkbox.checked = false;
            });
            controller.updateSelectedAttributes([]); 
            updateDropdownButton();
        });
    
        dropdownMenu.appendChild(deselectAllButton);

        // Populate list of columns legend (attribute-list)
        const columnListContainer = document.getElementById("attribute-list");
        if (columnListContainer) {
            const ul = document.getElementById("attribute-summary-list");
            ul.innerHTML = "";

            const columnErrors = this.model.getColumnErrorSummary(); 
            
            const sortedAttributes = attributes.sort((a, b) => {
                const errorsA = Object.values(columnErrors[a] || {}).reduce((sum, pct) => sum + pct, 0);
                const errorsB = Object.values(columnErrors[b] || {}).reduce((sum, pct) => sum + pct, 0);
                return errorsB - errorsA; // descending order
              });       

            sortedAttributes.forEach(attr => {
                const li = document.createElement("li");
                li.style.display = "flex";
                li.style.flexDirection = "column";
                li.style.gap = "4px";
                li.style.marginBottom = "16px";

                const topRow = document.createElement("div");
                topRow.style.display = "flex";
                topRow.style.alignItems = "center";
                topRow.style.gap = "6px";

                const label = document.createElement("span");
                label.textContent = attr;
                label.style.fontSize = "16px";
                label.style.fontWeight = "1000";
                label.style.marginRight = "10px";
                topRow.appendChild(label);
        
                const errorTypes = columnErrors[attr] || {};

                Object.entries(errorTypes).forEach(([type, pct]) => {
                    const box = document.createElement("span");
                    box.title = `${type}: ${(pct * 100).toFixed(1)}% of entries`;
                    box.classList.add("error-scent");
        
                    box.style.backgroundColor = {
                        "mismatch": "rgba(255, 105, 180, 0.7)",  // hotpink
                        "missing": "rgba(139, 69, 19, 0.7)",     // saddlebrown
                        "anomaly": "rgba(255, 0, 0, 0.7)",       // red
                        "incomplete": "rgba(128, 128, 128, 0.7)" // gray
                      }[type];
                
                    const percentText = document.createElement("span");
                    percentText.textContent = `${Math.round(pct * 100)}%`;
                    percentText.style.fontSize = "10px";
                    percentText.style.fontWeight = "bold";
                    percentText.style.color = "black";
                    percentText.style.position = "absolute";
                    percentText.style.top = "0";
                    percentText.style.right = "0";
                    percentText.style.transform = "translate(75%, 15%)";
                    box.appendChild(percentText);
        
                    topRow.appendChild(box);
                });

                li.appendChild(topRow);

                const columnData = table.array(attr).filter(d => d !== "" && d !== null && d !== undefined);
                const isNumeric = columnData.some(v => typeof v === "number" && !isNaN(v));

                const stats = document.createElement("div");
                stats.classList.add("column-stats");

                if (isNumeric) {
                    const mean = d3.mean(columnData);
                    const min = d3.min(columnData);
                    const max = d3.max(columnData);
                    stats.innerHTML = `<div>Mean: ${mean.toFixed(2)}</div>
                                        <div>Range: ${min} - ${max}</div>`;
                } else {
                    const mode = [...d3.rollup(columnData, v => v.length, d => d)]
                        .sort((a, b) => b[1] - a[1])[0][0];
                    const sortedVals = sortCategories(columnData.slice());
                    const min = sortedVals[0];
                    const max = sortedVals[sortedVals.length - 1];

                    stats.innerHTML = `<div>Mode: ${truncateText(mode, 50)}</div>
                                        <div>Range: ${truncateText(min, 50)} - ${truncateText(max, 50)}</div>`;
                }

                li.appendChild(stats);

                const totalRows = table.objects().length;
                const errorEntries = Object.entries(errorTypes);
                const errorSum = errorEntries.reduce((sum, [_, pct]) => sum + pct, 0);
                const cleanPct = Math.max(0, 1 - errorSum);

                const barContainer = document.createElement("div");
                barContainer.classList.add("error-bar-container");

                errorEntries.forEach(([type, pct]) => {
                    const segment = document.createElement("div");
                    segment.classList.add("bar-segment");
                    segment.style.width = `${pct * 100}%`;
                    segment.title = `${type}: ${(pct * 100).toFixed(1)}%`;

                    segment.style.backgroundColor = this.errorColors[type];
                    barContainer.appendChild(segment);
                });

                if (cleanPct > 0) {
                const cleanSegment = document.createElement("div");
                cleanSegment.classList.add("bar-segment");
                cleanSegment.style.backgroundColor = "steelblue";
                cleanSegment.style.width = `${cleanPct * 100}%`;
                cleanSegment.title = `Clean: ${(cleanPct * 100).toFixed(1)}%`;
                barContainer.appendChild(cleanSegment);
                }

                li.appendChild(barContainer);
        
                ul.appendChild(li);
            });
        
            columnListContainer.appendChild(ul);
        }
        
        attributes.forEach((attr, index) => {
            let label = document.createElement("label");
            let checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.value = attr;
    
            if (selectedAttributes.has(attr)) {
                checkbox.checked = true;
            }
    
            checkbox.addEventListener("change", function () {
                if (checkbox.checked) {
                    if (selectedAttributes.size < 3) {
                        selectedAttributes.add(attr);
                    } else {
                        checkbox.checked = false; 
                        alert("You can select up to 3 attributes only.");
                    }
                } else {
                    selectedAttributes.delete(attr);
                }
    
                controller.updateSelectedAttributes(Array.from(selectedAttributes)); 
                updateDropdownButton();
            });
    
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(attr));
            dropdownMenu.appendChild(label);

            let groupOption = document.createElement("option");
            groupOption.value = attr;
            groupOption.textContent = attr;
            groupDropdown.appendChild(groupOption);
            let predicateOption = document.createElement("option");
            predicateOption.value = attr;
            predicateOption.textContent = attr;
            predicateDropdown.appendChild(predicateOption);
        });
    
        function updateDropdownButton() {
            dropdownButton.textContent = `Select Attributes (${selectedAttributes.size}/3)`;
        }
    
        dropdownButton.onclick = function () {
            dropdownMenu.classList.toggle("show");
        };
    
        document.addEventListener("click", function (event) {
            if (!dropdownMenu.contains(event.target) && event.target !== dropdownButton) {
                dropdownMenu.classList.remove("show");
            }
        });

        groupDropdown.addEventListener("change", function () {
            controller.updateGrouping(this.value);
        });

        predicateDropdown.addEventListener("change", () => {
            this.handlePredicateChange(table, controller);
        });
              
        document.getElementById("sort-errors").addEventListener("change", () => {
            this.updateColumnErrorIndicators(table, controller);
          });

        updateDropdownButton();
    }

    /**
     * Updates the Attribute Summaries as data is wrangled and if the user changes which error type to sort on.
     * @param {*} table 
     * @param {*} controller 
     * @returns If the container does not exist, else should just update the UI.
     */
    updateColumnErrorIndicators(table, controller) {
        const columnErrors = controller.model.getColumnErrorSummary(); 
        const attributes = table.columnNames().slice(1);

        const sortBy = document.getElementById("sort-errors").value || "total";
        console.log("sortBy", sortBy);

        const container = document.getElementById("attribute-list");
        if (!container) return;

        const sortedAttributes = attributes.sort((a, b) => {
          const errorsA = columnErrors[a] || {};
          const errorsB = columnErrors[b] || {};

          // Primary: specific error type (or 0 if not present)
          const primaryA = sortBy === "total" ? 0 : (errorsA[sortBy] || 0);
          const primaryB = sortBy === "total" ? 0 : (errorsB[sortBy] || 0);

          // Secondary: total error percentage
          const totalA = Object.values(errorsA).reduce((sum, pct) => sum + pct, 0);
          const totalB = Object.values(errorsB).reduce((sum, pct) => sum + pct, 0);

          if (sortBy === "total") {
              // Sort by total error only
              return totalB - totalA;
          } else {
              // First by specific error type
              if (primaryB !== primaryA) {
              return primaryB - primaryA;
              }
              // Then by total error percentage
              return totalB - totalA;
          }
        });
      
        const ul = document.getElementById("attribute-summary-list");
        ul.innerHTML = "";
            
        sortedAttributes.forEach(attr => {
            const li = document.createElement("li");
            li.style.display = "flex";
            li.style.flexDirection = "column";
            li.style.gap = "4px";
            li.style.marginBottom = "16px";

            const topRow = document.createElement("div");
            topRow.style.display = "flex";
            topRow.style.alignItems = "center";
            topRow.style.gap = "6px";

            const label = document.createElement("span");
            label.textContent = attr;
            label.style.fontSize = "16px";
            label.style.fontWeight = "1000";
            label.style.marginRight = "10px";
            topRow.appendChild(label);
    
            const errorTypes = columnErrors[attr] || {};
    
            Object.entries(errorTypes).forEach(([type, pct]) => {
                const box = document.createElement("span");
                box.title = `${type}: ${(pct * 100).toFixed(1)}% of entries`;
                box.classList.add("error-scent");
    
                box.style.backgroundColor = {
                    "mismatch": "rgba(255, 105, 180, 0.7)",  // hotpink
                    "missing": "rgba(139, 69, 19, 0.7)",     // saddlebrown
                    "anomaly": "rgba(255, 0, 0, 0.7)",       // red
                    "incomplete": "rgba(128, 128, 128, 0.7)" // gray
                  }[type];
                  
                const percentText = document.createElement("span");
                percentText.textContent = `${Math.round(pct * 100)}%`;
                percentText.style.fontSize = "10px";
                percentText.style.fontWeight = "bold";
                percentText.style.color = "black";
                percentText.style.position = "absolute";
                percentText.style.top = "0";
                percentText.style.right = "0";
                percentText.style.transform = "translate(75%, 15%)";
                box.appendChild(percentText);
    
                topRow.appendChild(box);
            });

            li.appendChild(topRow);

            const columnData = table.array(attr).filter(d => d !== "" && d !== null && d !== undefined);
            const isNumeric = columnData.some(v => typeof v === "number" && !isNaN(v));

            const stats = document.createElement("div");
            stats.classList.add("column-stats");

            if (isNumeric) {
                const mean = d3.mean(columnData);
                const min = d3.min(columnData);
                const max = d3.max(columnData);
                stats.innerHTML = `<div>Mean: ${mean.toFixed(2)}</div>
                                    <div>Range: ${min} - ${max}</div>`;
            } else {
                const mode = [...d3.rollup(columnData, v => v.length, d => d)]
                    .sort((a, b) => b[1] - a[1])[0][0];
                const sortedVals = sortCategories(columnData.slice());
                const min = sortedVals[0];
                const max = sortedVals[sortedVals.length - 1];

                stats.innerHTML = `<div>Mode: ${truncateText(mode, 50)}</div>
                                    <div>Range: ${truncateText(min, 50)} - ${truncateText(max, 50)}</div>`;
            }

            li.appendChild(stats);

            const totalRows = table.objects().length;
            const errorEntries = Object.entries(errorTypes);
            const errorSum = errorEntries.reduce((sum, [_, pct]) => sum + pct, 0);
            const cleanPct = Math.max(0, 1 - errorSum);

            const barContainer = document.createElement("div");
            barContainer.classList.add("error-bar-container");

            errorEntries.forEach(([type, pct]) => {
            const segment = document.createElement("div");
            segment.classList.add("bar-segment");
            segment.style.width = `${pct * 100}%`;
            segment.title = `${type}: ${(pct * 100).toFixed(1)}%`;

            segment.style.backgroundColor = this.errorColors[type];

            barContainer.appendChild(segment);
            });

            if (cleanPct > 0) {
            const cleanSegment = document.createElement("div");
            cleanSegment.classList.add("bar-segment");
            cleanSegment.style.backgroundColor = "steelblue";
            cleanSegment.style.width = `${cleanPct * 100}%`;
            cleanSegment.title = `Clean: ${(cleanPct * 100).toFixed(1)}%`;
            barContainer.appendChild(cleanSegment);
            }

            li.appendChild(barContainer);
    
            ul.appendChild(li);
        });
    
        container.appendChild(ul);
    }

    /**
     * Populates the top 10 dirty rows table. Updates as the data is wrangled. Counts number of errors per row and displays in first column. Orders rows by most errors per row.
     * Highlights cells with the corresponding error color.
     * @param {*} data 
     * @returns 
     */
    updateDirtyRowsTable(data) {
        const columnErrors = this.model.getColumnErrors();
      
        // Count errors per row ID
        const rowErrorCounts = {};
        for (const col in columnErrors) {
          for (const id in columnErrors[col]) {
            if (!rowErrorCounts[id]) {
              rowErrorCounts[id] = { count: 0 };
            }
            rowErrorCounts[id].count += 1;          }
        }
      
        // Build full row objects with their error counts
        const fullData = data.objects().map(row => {
          const id = String(row.ID);
          return {
            ...row,
            __errorCount__: rowErrorCounts[id] ? rowErrorCounts[id].count : 0,
          };
        });
      
        // Sort by error count descending and take top 10
        const topRows = fullData
          .sort((a, b) => b.__errorCount__ - a.__errorCount__)
          .slice(0, 10);
      
        const wrapper = document.getElementById("dirty-rows-table-wrapper");
        wrapper.innerHTML = "";
      
        if (topRows.length === 0) {
          wrapper.innerHTML = "<p>No rows with errors found.</p>";
          return;
        }
      
        const table = document.createElement("table");
        table.id = "dirty-rows-table";
        table.style.borderCollapse = "collapse";
        table.style.width = "100%";
      
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
      
        const columns = ['Error Count', ...Object.keys(topRows[0]).filter(c => c !== '__errorCount__')];
      
        columns.forEach(col => {
          const th = document.createElement("th");
          th.textContent = col;
          th.style.border = "1px solid #ddd";
          th.style.padding = "6px";
          th.style.backgroundColor = "#f0f0f0";
          headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
      
        const tbody = document.createElement("tbody");
        topRows.forEach(row => {
          const tr = document.createElement("tr");
      
          columns.forEach(col => {
            const td = document.createElement("td");
      
            // Handle 'Error Count' column separately
            if (col === 'Error Count') {
              td.textContent = row.__errorCount__;
            } else {
              const cellValue = row[col];
              if (typeof cellValue === "string" && cellValue.length > 50) {
                  td.textContent = truncateText(cellValue, 50);
                  td.title = cellValue; // Show full value as tooltip
              } else {
                  td.textContent = cellValue;
              }
      
              // Color in cell if it has errors
              const errorList = columnErrors[col]?.[row.ID];
              if (errorList && errorList.length > 0) {
                const topErrorType = this.errorPriority.find(type => errorList.includes(type));
                td.style.backgroundColor = this.errorColors[topErrorType];
                td.style.color = "white";
              }
            }
      
            td.style.border = "1px solid #ddd";
            td.style.padding = "6px";
            tr.appendChild(td);
          });
      
          tbody.appendChild(tr);
        });
      
        table.appendChild(thead);
        table.appendChild(tbody);
        wrapper.appendChild(table);
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
     * @param {*} selectedGroups Selected groups to plot as chosen by the user in the box-and-whisker plots for the groups.
     * @param {*} selectionEnabled If true, the user can click on the plots to select points.
     * @param {*} animate If true, the plots will draw with transitions.
     * @param {*} handleBrush Handles user selected scatterplot points.
     * @param {*} handleBarClick Handles user selected bars. 
     * @param {*} handleHeatmapClick Passes to drawHeatMap to handle user selected bins.
     */
    plotMatrix(givenData, groupByAttribute, selectedGroups, selectionEnabled, animate, handleBrush, handleBarClick, handleHeatmapClick) {  
        const colorScale = d3.scaleOrdinal(d3.schemeCategory10);

        const columnErrors = this.model.getColumnErrors();

        let columns = givenData.columnNames().slice(1).filter(col => col !== groupByAttribute);
        let matrixWidth = columns.length * this.size + (columns.length - 1) * this.xPadding; // 3 * 175 + (2) * 25 = 575
        let matrixHeight = columns.length * this.size + (columns.length - 1) * this.yPadding; // 3 * 175 + (2) * 25 = 575

        let svgWidth = matrixWidth + this.labelPadding + this.leftMargin + this.rightMargin;
        let svgHeight = matrixHeight + this.labelPadding + this.topMargin + this.bottomMargin;

        this.topMargin = 100;

        const container = d3.select(this.container);
        container.selectAll("*").remove();
    
        const svg = container
            .append("svg")
            .attr("width", svgWidth) // 575 + 20 + 60 + 60 = 715
            .attr("height", svgHeight);
                
        columns.forEach((xCol, i) => {
            columns.forEach((yCol, j) => {
            const cellID = `cell-${i}-${j}`;
            const cellGroup = svg
                .append("g")
                .attr("id", cellID)
                .attr("transform", `translate(${this.leftMargin + j * (this.size + this.xPadding)}, ${this.topMargin + i * (this.size + this.yPadding)})`);

            if (i === j) {      // On the diagonal, so this should be a bar plot.
                let data = [];

                if (groupByAttribute){
                    data = givenData.select(["ID", xCol, groupByAttribute]).objects();
                }
                else{
                    data = givenData.select(["ID", xCol]).objects();
                }

                visualizations['barchart'].module.draw(this, data, groupByAttribute, cellGroup, columnErrors, svg, i, j, animate, selectionEnabled, handleBarClick, xCol );
                // drawBarchart(this, data, groupByAttribute, cellGroup, columnErrors, svg, i, j, animate, selectionEnabled, handleBarClick, xCol );

            
            } 
            // Plot off diagonal cells
            else {
                const heatMapViewButton = cellGroup.append("image")
                .attr("class", "heatmap-button active")
                .attr("x", -110)  
                .attr("y", -60)   
                .attr("width", 45) 
                .attr("height", 25)
                .attr("xlink:href", "images/icons/heatmap.png")
                .attr("cursor", "pointer")
                .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    
                const scatterViewButton = cellGroup.append("image")
                    .attr("class", "scatterplot-button")
                    .attr("x", -110)  
                    .attr("y", -35)   
                    .attr("width", 45) 
                    .attr("height", 25)
                    .attr("xlink:href", "images/icons/scatterplot.png")
                    .attr("cursor", "pointer")
                    .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

                const lineViewButton = cellGroup.append("image")
                    .attr("class", "linechart-button")
                    .attr("x", -110)  
                    .attr("y", -10)   
                    .attr("width", 45) 
                    .attr("height", 25)
                    .attr("xlink:href", "images/icons/linechart.png")
                    .attr("cursor", "pointer")
                    .on("click", () => visualizations['linechart'].module.draw(this.model, this, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
                    // .on("click", () => switchToLineChart(this.model, this, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

                visualizations['heatmap'].module.draw(this.model, this, cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);
                // drawHeatMap(this.model, this, cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);
            }
            });
        });
    }




    /**
     * Draw scatterplot when scatterplot icon is clicked.
     * @param {*} givenData Data to visualize.
     * @param {*} svg The overall matrix svg.
     * @param {*} xCol The x attribute/column.
     * @param {*} yCol The y attribute/column.
     * @param {*} cellID Which cell in the matrix we are in.
     * @param {*} groupByAttribute If active, the user-selected attribute to group by.
     * @param {*} selectionEnabled If true, the user can click on bins in the visualization to select.
     * @param {*} animate If true, the plots should have transitions.
     * @param {*} handleHeatmapClick Given to pass around. 
     */
    restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`); // Hardcoded for stackoverflow tab
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));
        visualizations['scatterplot'].module.draw(this.model, this, cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);  
        // drawScatterplot(this.model, this, cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);  

        d3.select(this.parentNode).selectAll(".linechart-button, .heatmap-button").classed("active", false);

        const heatMapViewButton = cellGroup.append("image")
            .attr("class", "heatmap-button")
            .attr("x", -110)  
            .attr("y", -60)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/heatmap.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const scatterViewButton = cellGroup.append("image")
            .attr("class", "scatterplot-button active")
            .attr("x", -110)  
            .attr("y", -35)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/scatterplot.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const lineViewButton = cellGroup.append("image")
            .attr("class", "linechart-button")
            .attr("x", -110)  
            .attr("y", -10)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/linechart.png")
            .attr("cursor", "pointer")
            .on("click", () => visualizations['linechart'].module.draw(this.model, this, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
            // .on("click", () => switchToLineChart(this.model, this, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    }

    /**
     * Draw heatmap when heatmap icon is clicked.
     * @param {*} givenData Data to visualize.
     * @param {*} svg The overall matrix svg.
     * @param {*} xCol The x attribute/column.
     * @param {*} yCol The y attribute/column.
     * @param {*} cellID Which cell in the matrix we are in.
     * @param {*} groupByAttribute If active, the user-selected attribute to group by.
     * @param {*} selectionEnabled If true, the user can click on bins in the visualization to select.
     * @param {*} animate If true, the plots should have transitions.
     * @param {*} handleHeatmapClick Given to pass around. 
     */
    restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`); // Hardcoded for stackoverflow tab
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));
        visualizations['heatmap'].module.draw(this.model, this, cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);  
        // drawHeatMap(this.model, this, cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);  

        d3.select(this.parentNode).selectAll(".linechart-button, .scatterplot-button").classed("active", false);


        const heatMapViewButton = cellGroup.append("image")
            .attr("class", "heatmap-button active")
            .attr("x", -110)  
            .attr("y", -60)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/heatmap.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const scatterViewButton = cellGroup.append("image")
            .attr("class", "scatterplot-button")
            .attr("x", -110)  
            .attr("y", -35)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/scatterplot.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const lineViewButton = cellGroup.append("image")
            .attr("class", "linechart-button")
            .attr("x", -110)  
            .attr("y", -10)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/linechart.png")
            .attr("cursor", "pointer")
            .on("click", () => visualizations['linechart'].module.draw(this.model, this, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
            // .on("click", () => switchToLineChart(this.model, this, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    }

    /**
     * Draws preview plots in the Data Repair Toolkit box. Can only draw histograms or heatmaps. Plotting code is copied from the plotMatrix and drawHeatMap functions.
     * @param {*} givenData Data to visualize.
     * @param {*} originalData Data before the preview.
     * @param {*} containerId 
     * @param {*} isHistogram If true, the plot the user clicked on was a histogram plot.
     * @param {*} groupByAttribute f active, the user-selected attribute to group by.
     * @param {*} xCol The x attribute/column.
     * @param {*} yCol The y attribute/column.
     * @returns 
     */
    drawPreviewPlot(givenData, originalData, containerId, isHistogram, groupByAttribute, xCol, yCol){
        const container = document.getElementById(containerId);
        container.innerHTML = ""; 

        if (givenData.length === 0) {
            container.style.display = "none"; 
            return;
        }

        container.style.display = "block"; 

        const margin = { top: 20, right: 40, bottom: 50, left: 60 };
        const width = 250 - margin.left - margin.right;
        const height = 250 - margin.top - margin.bottom;

        const svg = d3.select(`#${containerId}`)
            .append("svg")
            .attr("width", width + margin.left + margin.right)
            .attr("height", height + margin.top + margin.bottom)
            .append("g")
            .attr("transform", `translate(${margin.left}, ${margin.top})`);

        svg.append("text")
            .attr("x", width / 2)
            .attr("y", -10) 
            .attr("text-anchor", "middle")
            .attr("font-size", "12px")
            .attr("font-weight", "bold")
            .text(containerId === "preview-remove" ? "Preview of Removing Selected Data" :
                  containerId === "preview-impute-average-x" ? `Preview of Imputing by Avg ${truncateText(xCol, 12)}` :
                  containerId === "preview-impute-average-y" ? `Preview of Imputing by Avg ${truncateText(yCol, 12)}` :
                  "Preview of User Specified Repair");

        const columnErrors = this.model.getColumnErrors();

        if(isHistogram)     // The user selected points on a histogram.
        {
            if(containerId === "preview-impute-average-y")
            {
                return;
            }
            let data = [];
            let originalDataArr = [];

            if (groupByAttribute){
                data = givenData.select(["ID", xCol, groupByAttribute]).objects();
                originalDataArr = originalData.select(["ID", xCol, groupByAttribute]).objects();
            }
            else{
                data = givenData.select(["ID", xCol]).objects();
                originalDataArr = originalData.select(["ID", xCol]).objects();
            }

            const numericData = data.filter(d => 
                typeof d[xCol] === "number" && !isNaN(d[xCol])
            );
            const originalNumericData = originalDataArr.filter(d => 
                typeof d[xCol] === "number" && !isNaN(d[xCol])
            );
            
            const nonNumericData = data.filter(d => 
                typeof d[xCol] !== "number" || isNaN(d[xCol])
            ).map(d => ({
                ...d,
                [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
            }));
            const originalNonNumericData = originalDataArr.filter(d => 
                typeof d[xCol] !== "number" || isNaN(d[xCol])
            ).map(d => ({
                ...d,
                [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
            }));

            const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));
            const originalGroupedCategories = d3.group(originalNonNumericData, d => String(d[xCol]));

            let uniqueCategories;
            let originalUniqueCategories;
            
            if (numericData.length === data.length)
            {
                uniqueCategories = [];
            }else{
                uniqueCategories = ["NaN", ...[...originalGroupedCategories.keys()].filter(d => d !== "NaN").sort()]
            }

            if (originalNumericData.length === data.length)
            {
                originalUniqueCategories = [];
            }else{
                originalUniqueCategories = ["NaN", ...[...originalGroupedCategories.keys()].filter(d => d !== "NaN").sort()]
            }

            const categorySpace = uniqueCategories.length * 20; 
            const originalCategorySpace = originalUniqueCategories *20
            const numericSpace = width - categorySpace; 
            const originalNumericSpace = width - originalCategorySpace; 
            let categoricalScale = null;
            let originalCategoricalScale = null;
            
            if (numericData.length > 0)     // Histogram data is numeric
            {
                uniqueCategories = sortCategories(uniqueCategories);
                originalUniqueCategories = sortCategories(originalUniqueCategories);

                let xScale = d3.scaleLinear()
                    .domain([d3.min(originalNumericData, (d) => d[xCol]), d3.max(originalNumericData, (d) => d[xCol]) + 1])
                    .range([0, originalNumericSpace]);

                let yScale = null;
                
                const histogramGenerator = d3.histogram()
                    .domain(xScale.domain())
                    .thresholds(10);

                const bins = histogramGenerator(numericData.map(d => d[xCol]));

                const values = numericData.map(d => d[xCol]).filter(v => !isNaN(v));
                const mean = d3.mean(values);
                const stdDev = d3.deviation(values);

                if (groupByAttribute) {     // Group by is active
                    const groups = Array.from(new Set(numericData.map(d => d[groupByAttribute])));
                    const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(groups);
            
                    const stackedData = bins.map(bin => {
                        const binData = numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1);
                        let obj = {
                            x0: bin.x0,
                            x1: bin.x1,
                            total: binData.length,
                            ids: binData.map(d => d.ID),
                            groupIDs: {}  
                        };
                        groups.forEach(g => {
                            const groupData = binData.filter(d => d[groupByAttribute] === g);
                            obj[g] = groupData.length;  
                            obj.groupIDs[g] = groupData.map(d => d.ID);
                        });
                        return obj;
                    });
            
                    const binWidth = xScale(bins[0].x1) - xScale(bins[0].x0);

                    const categoricalStart = xScale.range()[1] + 10;

                    categoricalScale = d3.scaleOrdinal()
                        .domain(originalUniqueCategories)
                        .range([...Array(originalUniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

                    uniqueCategories.forEach(category => {
                        const catData = nonNumericData.filter(d => String(d[xCol]) === category);
                        let obj = {
                            x0: categoricalScale(category),
                            x1: categoricalScale(category) + binWidth,
                            group: null,
                            total: catData.length,
                            category: category,
                            ids: catData.map(d => d.ID),
                            groupIDs: {}   
                        };
                        groups.forEach(g => {
                            const groupData = catData.filter(d => d[groupByAttribute] === g);
                            obj[g] = groupData.length;  
                            obj.group = g;
                            obj.groupIDs[g] = groupData.map(d => d.ID);
                        });
                        stackedData.push(obj);
                    });
            
                    const yMax = d3.max(stackedData, d => d.total);
                    yScale = d3.scaleLinear()
                        .domain([0, yMax])
                        .range([height, 0]);
            
                    const stackGen = d3.stack().keys(groups);
                    const series = stackGen(stackedData);
            
                    svg.selectAll("g.series")
                        .data(series)
                        .join("g")
                        .attr("class", "series")
                        .attr("data-group", d => d.key)
                        .selectAll("rect")
                        .data(d => {
                            d.forEach(item => item.group = d.key);  
                            return d;
                        })                        
                        .join("rect")
                        .attr("fill", d => {
                            if (!this.viewGroupsButton){
                                return getFillColorNumeric(d, xCol, columnErrors, this.errorColors, this.selectedPoints); 
                            }
                            return d.data.category ? "gray" : colorScale(d.group);
                        })
                        .attr("stroke", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? "black" : (this.viewGroupsButton ? "none" : "white");
                        })
                        .attr("stroke-width", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? 2 : 0.5;
                        })
                        .attr("opacity", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? 1 : 0.7;
                        })
                        .attr("x", d => d.data.category ? categoricalScale(d.data.category) : xScale(d.data.x0))
                        .attr("y", d => yScale(d[1]))
                        .attr("width", binWidth)
                        .attr("height", d => yScale(d[0]) - yScale(d[1]));
                }
                else{        // No group by
                    const histData = histogramGenerator(numericData.map(d => d[xCol])).map(bin => {
                        return {
                            x0: bin.x0,
                            x1: bin.x1,
                            length: bin.length,
                            ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.ID)
                        };
                    });

                    xScale = d3.scaleLinear()
                        .domain([d3.min(histData, d => d.x0), d3.max(histData, d => d.x1)])
                        .range([0, this.size]);

                    const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
                    const categoricalStart = xScale.range()[1] + 10;

                    categoricalScale = d3.scaleOrdinal()
                        .domain(originalUniqueCategories)
                        .range([...Array(originalUniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

                    uniqueCategories.forEach(category => {
                        histData.push({
                            x0: categoricalScale(category),
                            x1: categoricalScale(category) + binWidth,
                            length: nonNumericData.filter(d => String(d[xCol]) === category).length,
                            ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.ID),
                            category: category 
                        });
                    });

                    yScale = d3.scaleLinear()
                        .domain([0, d3.max(histData, (d) => d.length)])
                        .range([this.size, 0]);
                    
                    svg.selectAll("rect")
                        .data(histData)
                        .join("rect")
                        .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.x0))
                        .attr("width", binWidth)
                        .attr("y", d => yScale(d.length))
                        .attr("height", d => height - yScale(d.length))
                        .attr("fill", d => getFillColorNoGroupbyNumeric(d, xCol, columnErrors, this.errorColors, this.selectedPoints))
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "none";
                        })
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0
                        })
                        .attr("opacity", 0.8);
                }
                
                svg
                    .append("g")
                    .attr("transform", `translate(0, ${this.size})`)
                    .call(d3.axisBottom(xScale).tickFormat(d3.format(".2s")))
                    .selectAll("text") 
                    .style("text-anchor", "end") 
                    .style("font-size", "8px")
                    .attr("dx", "-0.5em") 
                    .attr("dy", "0.5em")  
                    .attr("transform", "rotate(-45)")
                    .append("title")  
                    .text(d => d);

                if (uniqueCategories.length > 0) {
                    svg.append("g")
                        .attr("transform", `translate(10, ${this.size})`)
                        .call(d3.axisBottom(categoricalScale))
                        .selectAll("text")
                        .style("text-anchor", "end") 
                        .attr("transform", "rotate(-45)") 
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d);
                }
                svg.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

            }
            else{   // Histogram data is all categorical
                uniqueCategories = uniqueCategories.slice(1);
                uniqueCategories = sortCategories(uniqueCategories);

                originalUniqueCategories = originalUniqueCategories.slice(1);
                originalUniqueCategories = sortCategories(originalUniqueCategories);

                const xScale = d3.scaleBand()
                    .domain(originalUniqueCategories)
                    .range([0, width]);

                let yScale = null;

                if (groupByAttribute) {     // Group by is active
                    const groups = Array.from(new Set(nonNumericData.map(d => d[groupByAttribute])));
                    const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(groups);
                    
                    const stackedData = uniqueCategories.map(category => {
                        const obj = {
                            category: category,
                            x0: xScale(category),
                            x1: xScale(category) + xScale.bandwidth(),
                            group: null,
                            total: 0, 
                            ids: [],  
                            groupIDs: {}
                        };
                        groups.forEach(g => {
                            const groupData = nonNumericData.filter(d => 
                                String(d[xCol]) === category && d[groupByAttribute] === g
                            );
                            
                            obj[g] = groupData.length;  
                            obj.groupIDs[g] = groupData.map(d => d.ID);
                            obj.group = g; 
                            obj.total += groupData.length; 
                            obj.ids.push(...groupData.map(d => d.ID)); 
                        });
                        return obj;
                    });
                    
                    const yMax = d3.max(stackedData, d => groups.reduce((sum, g) => sum + d[g], 0));
                    yScale = d3.scaleLinear().domain([0, yMax]).range([height, 0]);
                    
                    const stackGen = d3.stack().keys(groups);
                    const series = stackGen(stackedData);
                    
                    svg.selectAll("g.series")
                        .data(series)
                        .join("g")
                        .attr("class", "series")
                        .attr("data-group", d => d.key)
                        .selectAll("rect")
                        .data(d => {
                            d.forEach(item => item.group = d.key);  
                            return d;
                        })                        
                        .join("rect")
                        .attr("fill", d => {
                            if (!this.viewGroupsButton){
                                return getFillColorCategorical(d, xCol, columnErrors, this.errorColors, this.selectedPoints); 
                            }
                            return colorScale(d.group);
                        })
                        .attr("stroke", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? "black" : (this.viewGroupsButton ? "none" : "white");
                        })
                        .attr("stroke-width", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? 2 : 0.5;
                        })
                        .attr("opacity", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? 1 : 0.7;
                        })
                        .attr("x", d => xScale(d.data.category))
                        .attr("y", d => yScale(d[1]))
                        .attr("width", xScale.bandwidth())
                        .attr("height", d => yScale(d[0]) - yScale(d[1]));
                }
                else{       // No group by
                    const histData = [];

                    uniqueCategories.forEach(category => {
                        histData.push({
                            x0: xScale(category),
                            x1: xScale(category) + xScale.bandwidth(),
                            length: nonNumericData.filter(d => String(d[xCol]) === category).length,
                            ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.ID),
                            category: category 
                        });
                    });
                    
                    yScale = d3.scaleLinear()
                        .domain([0, d3.max(histData, (d) => d.length)])
                        .range([height, 0]);
                    
                    svg.selectAll("rect")
                        .data(histData)
                        .join("rect")
                        .attr("x", d => xScale(d.category))
                        .attr("width", xScale.bandwidth())
                        .attr("y", d => yScale(d.length))
                        .attr("height", d => Math.max(0, height - yScale(d.length)))
                        .attr("fill", d => getFillColorNoGroupbyCategorical(d, xCol, columnErrors, this.errorColors, this.selectedPoints))
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "none";
                        })
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0
                        })
                        .attr("opacity", 0.8);
                }
                
                svg
                    .append("g")
                    .attr("transform", `translate(0, ${height})`)
                    .call(d3.axisBottom(xScale))
                    .selectAll("text") 
                    .style("text-anchor", "end") 
                    .style("font-size", "8px")
                    .attr("dx", "-0.5em") 
                    .attr("dy", "0.5em")  
                    .attr("transform", "rotate(-45)")
                    .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                    .append("title")  
                    .text(d => d);

                svg.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");
            }
        }
        /// User made selection on a heatmap ///
        else{
            const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

            const groupColorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

            const gradientID = `legend-gradient-preview`;
            let defs = svg.select("defs");
            if (defs.empty()) {
                defs = svg.append("defs");
            }
            svg.select(`#${gradientID}`).remove();

            let xScale = null;
            let yScale = null;

            let data = [];

            if(groupByAttribute)
            {
                data = givenData.select(["ID", xCol, yCol, groupByAttribute]).objects(); 
            }
            else{
                data = givenData.select(["ID", xCol, yCol]).objects();
            }

            let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace} = splitData(data, xCol, yCol);

            const numericXValues = nonNumericYData.map(d => d[xCol]).filter(v => !isNaN(v));
            const numericYValues = nonNumericXData.map(d => d[yCol]).filter(v => !isNaN(v));

            const meanX = d3.mean(numericXValues);
            const stdDevX = d3.deviation(numericXValues);
            const meanY = d3.mean(numericYValues);
            const stdDevY = d3.deviation(numericYValues);

            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = sortCategories(uniqueXCategories);
            uniqueYCategories = sortCategories(uniqueYCategories);

            const uniqueXStringBins = uniqueXCategories; 
            const uniqueYStringBins = uniqueYCategories; 

            let binXGenerator = d3.bin()
                .domain([d3.min(nonNumericYData, (d) => d[xCol]), d3.max(nonNumericYData, (d) => d[xCol])])  
                .thresholds(10);  

            let binYGenerator = d3.bin()
                .domain([d3.min(nonNumericXData, (d) => d[yCol]), d3.max(nonNumericXData, (d) => d[yCol])])  
                .thresholds(10);  

            let xBins = binXGenerator(numericData);
            let xBinLabels = xBins.map((d, i) => `${Math.round(d.x0)}-${Math.round(d.x1)}`);
            let yBins = binYGenerator(numericData);
            let yBinLabels = yBins.map((d, i) => `${Math.round(d.x0)}-${Math.round(d.x1)}`);

            let xCategories = [...xBinLabels, ...uniqueXStringBins].filter((v, i, self) => self.indexOf(v) === i); 
            let yCategories = [...yBinLabels, ...uniqueYStringBins].filter((v, i, self) => self.indexOf(v) === i); 

            /// All numeric plot ///
            if(xIsNumeric && yIsNumeric)
            {
                binXGenerator = d3.bin()
                    .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol])])  
                    .thresholds(10);  

                binYGenerator = d3.bin()
                    .domain([d3.min(numericData, (d) => d[yCol]), d3.max(numericData, (d) => d[yCol])])  
                    .thresholds(10);  

                xBins = binXGenerator(numericData);
                xBinLabels = xBins.map((d, i) => `${Math.round(d.x0)}-${Math.round(d.x1)}`);
                yBins = binYGenerator(numericData);
                yBinLabels = yBins.map((d, i) => `${Math.round(d.x0)}-${Math.round(d.x1)}`);

                data = data.map(d => ({
                        ...d,
                        binnedNumericalXCol: isNaN(d[xCol])
                            ? String(d[xCol])
                            : xBinLabels.find((label, i) => {
                                return d[xCol] >= xBins[i].x0 && d[xCol] < xBins[i].x1;
                            }) || xBinLabels[xBinLabels.length - 1],
                        binnedNumericalYCol: isNaN(d[yCol])
                            ? String(d[yCol])
                            : yBinLabels.find((label, i) => {
                                return d[yCol] >= yBins[i].x0 && d[yCol] < yBins[i].x1;
                            }) || yBinLabels[yBinLabels.length - 1] 
                }));

                if(groupByAttribute){       // Group by is active
                    const groupedData = d3.rollups(
                        data,
                        v => {
                            let groupCounts = {};
                            let groupIDs = {};  
                    
                            v.forEach(d => {
                                if (!groupCounts[d[groupByAttribute]]) {
                                    groupCounts[d[groupByAttribute]] = 0;
                                    groupIDs[d[groupByAttribute]] = []; 
                                }
                                groupCounts[d[groupByAttribute]] += 1;
                                groupIDs[d[groupByAttribute]].push(d.ID); 
                            });
                    
                            return { counts: groupCounts, ids: groupIDs };  
                        },
                        d => d.binnedNumericalXCol, 
                        d => d.binnedNumericalYCol  
                    );

                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            groups: groupData.counts, 
                            ids: groupData.ids
                        }))
                    );

                    xCategories = [...xBinLabels, ...uniqueXStringBins].filter((v, i, self) => self.indexOf(v) === i); 
                    yCategories = [...yBinLabels, ...uniqueYStringBins].filter((v, i, self) => self.indexOf(v) === i); 

                    xScale = d3.scaleBand().domain(xCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(yCategories).range([height, 0]).padding(0.05);
                    const self = this; 

                    svg.selectAll("g.cell-group")
                        .data(heatmapData)
                        .join("g")
                        .attr("class", "cell-group")
                        .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                        .each(function (d) {
                            const g = d3.select(this);
                            let yOffset = 0;
                            const total = d3.sum(Object.values(d.groups));

                            Object.entries(d.groups).forEach(([group, count]) => {
                                g.append("rect")
                                    .attr("x", 0)
                                    .attr("y", yOffset) 
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)  
                                    .attr("fill", d => {
                                        if (!self.viewGroupsButton){
                                            return getFillColorHeatmap(d, group, numericData, xCol, yCol, meanX, stdDevX, meanY, stdDevY, self.selectedPoints, groupColorScale); 
                                        }
                                        return groupColorScale(group);
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? "black" : (this.viewGroupsButton ? "none" : "white");
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? 2 : 0.5;
                                    })
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });   
                }
                else{       // No group by
                    const groupedData = d3.rollups(
                        data,
                        v => ({
                            count: v.length,  
                            ids: v.map(d => d.ID) 
                        }),  
                        d => d.binnedNumericalXCol,   
                        d => d.binnedNumericalYCol  
                    );
        
                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            value: groupData.count,  
                            ids: groupData.ids
                        }))
                    );
        
                    xScale = d3.scaleBand().domain(xCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(yCategories).range([height, 0]).padding(0.05);
                    const colorScale = d3.scaleSequential(d3.interpolateBlues)
                        .domain([0, d3.max(heatmapData, d => d.value)]);
                
                    svg.selectAll("rect")
                        .data(heatmapData)
                        .join("rect")
                        .attr("x", d => xScale(d.x))
                        .attr("y", d => yScale(d.y))
                        .attr("width", xScale.bandwidth())
                        .attr("height", yScale.bandwidth())
                        .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, this.errorColors, colorScale, this.selectedPoints))
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "gray";
                        })
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0.5
                        });
        
                    const legendHeight = height;
                    const legendWidth = 10;
                    const legendX = width + 5; 
                    const legendY = 0;
        
                    const legendScale = d3.scaleLinear()
                        .domain(colorScale.domain())
                        .range([legendHeight, 0]);
            
                    const linearGradient = defs.append("linearGradient")
                        .attr("id", gradientID)
                        .attr("x1", "0%").attr("x2", "0%")
                        .attr("y1", "100%").attr("y2", "0%");
        
                    const numGradientStops = 10;
                    d3.range(numGradientStops).forEach(d => {
                        linearGradient.append("stop")
                            .attr("offset", `${(d / (numGradientStops - 1)) * 100}%`)
                            .attr("stop-color", colorScale(legendScale.domain()[0] + (d / (numGradientStops - 1)) * (legendScale.domain()[1] - legendScale.domain()[0])));
                    });
        
                    svg.append("rect")
                        .attr("x", legendX)
                        .attr("y", legendY)
                        .attr("width", legendWidth)
                        .attr("height", legendHeight)
                        .style("fill", `url(#${gradientID})`)
                        .attr("stroke", "black");
        
                    svg.append("g")
                        .attr("transform", `translate(${legendX + legendWidth}, ${legendY})`)
                        .call(d3.axisRight(legendScale)
                            .ticks(5))
                        .selectAll("text")
                        .style("font-size", "8px");
                }
            }
            /// Non numeric X plot ///
            else if(!xIsNumeric && yIsNumeric) // xCol is cat. yCol is num.
            {
                data = data.map(d => ({
                    ...d,
                    binnedNumericalCol: isNaN(d[yCol])
                        ? String(d[yCol])
                        : yBinLabels.find((label, i) => d[yCol] >= yBins[i].x0 && d[yCol] < yBins[i].x1) || yBinLabels[yBinLabels.length - 1]
                }));

                if(groupByAttribute){       // Group by is active
                    const groupedData = d3.rollups(
                        data,
                        v => {
                            let groupCounts = {};
                            let groupIDs = {};  
                    
                            v.forEach(d => {
                                if (!groupCounts[d[groupByAttribute]]) {
                                    groupCounts[d[groupByAttribute]] = 0;
                                    groupIDs[d[groupByAttribute]] = []; 
                                }
                                groupCounts[d[groupByAttribute]] += 1;
                                groupIDs[d[groupByAttribute]].push(d.ID); 
                            });
                    
                            return { counts: groupCounts, ids: groupIDs };  
                        },
                        d => d[xCol], 
                        d => d.binnedNumericalCol  
                    );

                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            groups: groupData.counts, 
                            ids: groupData.ids
                        }))
                    );

                    xScale = d3.scaleBand().domain(uniqueXCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(yCategories).range([height, 0]).padding(0.05);
                    const self = this; 

                    svg.selectAll("g.cell-group")
                        .data(heatmapData)
                        .join("g")
                        .attr("class", "cell-group")
                        .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                        .each(function (d) {
                            const g = d3.select(this);
                            let yOffset = 0;
                            const total = d3.sum(Object.values(d.groups));

                            Object.entries(d.groups).forEach(([group, count]) => {
                                g.append("rect")
                                    .attr("x", 0)
                                    .attr("y", yOffset) 
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)  
                                    .attr("fill", d => {
                                        if (!self.viewGroupsButton){
                                            return getFillColorHeatmap(d, group, numericData, xCol, yCol, meanX, stdDevX, meanY, stdDevY, self.selectedPoints, groupColorScale); 
                                        }
                                        return groupColorScale(group);
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? "black" : (this.viewGroupsButton ? "none" : "white");
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? 2 : 0.5;
                                    })
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });                
                }
                else{       // No group by
                    const groupedData = d3.rollups(
                        data,
                        v => ({
                            count: v.length,  
                            ids: v.map(d => d.ID) 
                        }),
                        d => d[xCol],   
                        d => d.binnedNumericalCol  
                    );

                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            value: groupData.count,  
                            ids: groupData.ids 
                        }))
                    );

                    xScale = d3.scaleBand().domain(uniqueXCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(yCategories).range([height, 0]).padding(0.05);
                    const colorScale = d3.scaleSequential(d3.interpolateBlues)
                        .domain([0, d3.max(heatmapData, d => d.value)]);

                    svg.selectAll("rect")
                        .data(heatmapData)
                        .join("rect")
                        .attr("x", d => xScale(d.x))
                        .attr("y", d => yScale(d.y))
                        .attr("width", xScale.bandwidth())
                        .attr("height", yScale.bandwidth())
                        .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, this.errorColors, colorScale, this.selectedPoints))
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "gray";
                        })
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0.5
                        });

                    const legendHeight = height;
                    const legendWidth = 10;
                    const legendX = width + 5; 
                    const legendY = 0;

                    const legendScale = d3.scaleLinear()
                        .domain(colorScale.domain())
                        .range([legendHeight, 0]);

                    const linearGradient = defs.append("linearGradient")
                        .attr("id", gradientID)
                        .attr("x1", "0%").attr("x2", "0%")
                        .attr("y1", "100%").attr("y2", "0%");

                    const numGradientStops = 10;
                    d3.range(numGradientStops).forEach(d => {
                        linearGradient.append("stop")
                            .attr("offset", `${(d / (numGradientStops - 1)) * 100}%`)
                            .attr("stop-color", colorScale(legendScale.domain()[0] + (d / (numGradientStops - 1)) * (legendScale.domain()[1] - legendScale.domain()[0])));
                    });

                    svg.append("rect")
                        .attr("x", legendX)
                        .attr("y", legendY)
                        .attr("width", legendWidth)
                        .attr("height", legendHeight)
                        .style("fill", `url(#${gradientID})`)
                        .attr("stroke", "black");

                    svg.append("g")
                        .attr("transform", `translate(${legendX + legendWidth}, ${legendY})`)
                        .call(d3.axisRight(legendScale)
                            .ticks(5))
                        .selectAll("text")
                        .style("font-size", "8px");
                }

                svg.append("g")
                    .attr("transform", `translate(0, ${height})`)
                    .call(d3.axisBottom(xScale))
                    .selectAll("text")
                    .style("text-anchor", "end")
                    .style("font-size", "8px")
                    .attr("dx", "-0.5em")
                    .attr("dy", "0.5em")
                    .attr("transform", "rotate(-45)")
                    .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                    .append("title")  
                    .text(d => d);
        
                svg.append("g")
                    .call(d3.axisLeft(yScale).tickFormat(d => {
                        if (typeof d === "string" && d.includes("-")) {
                            const [min, max] = d.split("-").map(Number);
                            return `${d3.format(".3s")(min)}-${d3.format(".3s")(max)}`;
                        }
                        return d3.format(".3s")(d); 
                    }))
                    .selectAll("text")
                    .style("font-size", "8px");
            }

            /// Non numeric Y plot ///
            else if(xIsNumeric && !yIsNumeric) // xCol is num. yCol is cat.
            {
                data = data.map(d => ({
                        ...d,
                        binnedNumericalCol: isNaN(d[xCol])
                            ? String(d[xCol]) // Keep non-numeric values as separate bins
                            : xBinLabels.find((label, i) => {
                                return d[xCol] >= xBins[i].x0 && d[xCol] < xBins[i].x1;
                            }) || xBinLabels[xBinLabels.length - 1] // Default to last bin

                }));

                if(groupByAttribute){       // Group by is active
                    const groupedData = d3.rollups(
                        data,
                        v => {
                            let groupCounts = {};
                            let groupIDs = {};  
                    
                            v.forEach(d => {
                                if (!groupCounts[d[groupByAttribute]]) {
                                    groupCounts[d[groupByAttribute]] = 0;
                                    groupIDs[d[groupByAttribute]] = [];  
                                }
                                groupCounts[d[groupByAttribute]] += 1;
                                groupIDs[d[groupByAttribute]].push(d.ID); 
                            });
                    
                            return { counts: groupCounts, ids: groupIDs }; 
                        },
                        d => d.binnedNumericalCol, 
                        d => d[yCol] 
                    );

                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            groups: groupData.counts,  
                            ids: groupData.ids 
                        }))
                    );

                    xScale = d3.scaleBand().domain(xCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(uniqueYCategories).range([height, 0]).padding(0.05);
                    const self = this; 

                    svg.selectAll("g.cell-group")
                        .data(heatmapData)
                        .join("g")
                        .attr("class", "cell-group")
                        .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                        .each(function (d) {
                            const g = d3.select(this);
                            let yOffset = 0;
                            const total = d3.sum(Object.values(d.groups));

                            Object.entries(d.groups).forEach(([group, count]) => {
                                g.append("rect")
                                    .attr("x", 0)
                                    .attr("y", yOffset) 
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)  
                                    .attr("fill", d => {
                                        if (!self.viewGroupsButton){
                                            return getFillColorHeatmap(d, group, numericData, xCol, yCol, meanX, stdDevX, meanY, stdDevY, self.selectedPoints, groupColorScale); 
                                        }
                                        return groupColorScale(group);
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? "black" : (this.viewGroupsButton ? "none" : "white");
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? 2 : 0.5;
                                    })
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });         

                }
                else{       // No group by
                    const groupedData = d3.rollups(
                        data,
                        v => ({
                            count: v.length,  
                            ids: v.map(d => d.ID) 
                        }),   
                        d => d.binnedNumericalCol,   
                        d => d[yCol]  
                    );

                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            value: groupData.count,  
                            ids: groupData.ids 
                        }))
                    );

                    xScale = d3.scaleBand().domain(xCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(uniqueYCategories).range([height, 0]).padding(0.05);
                    const colorScale = d3.scaleSequential(d3.interpolateBlues)
                        .domain([0, d3.max(heatmapData, d => d.value)]);

                    svg.selectAll("rect")
                        .data(heatmapData)
                        .join("rect")
                        .attr("x", d => xScale(d.x))
                        .attr("y", d => yScale(d.y))
                        .attr("width", xScale.bandwidth())
                        .attr("height", yScale.bandwidth())
                        .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, this.errorColors, colorScale, this.selectedPoints))   
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "gray";
                        })
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0.5
                        });

                    const legendHeight = height;
                    const legendWidth = 10;
                    const legendX = width + 5; 
                    const legendY = 0;

                    const legendScale = d3.scaleLinear()
                        .domain(colorScale.domain())
                        .range([legendHeight, 0]);

                    const linearGradient = defs.append("linearGradient")
                        .attr("id", gradientID)
                        .attr("x1", "0%").attr("x2", "0%")
                        .attr("y1", "100%").attr("y2", "0%");

                    const numGradientStops = 10;
                    d3.range(numGradientStops).forEach(d => {
                        linearGradient.append("stop")
                            .attr("offset", `${(d / (numGradientStops - 1)) * 100}%`)
                            .attr("stop-color", colorScale(legendScale.domain()[0] + (d / (numGradientStops - 1)) * (legendScale.domain()[1] - legendScale.domain()[0])));
                    });

                    svg.append("rect")
                        .attr("x", legendX)
                        .attr("y", legendY)
                        .attr("width", legendWidth)
                        .attr("height", legendHeight)
                        .style("fill", `url(#${gradientID})`)
                        .attr("stroke", "black");

                    svg.append("g")
                        .attr("transform", `translate(${legendX + legendWidth}, ${legendY})`)
                        .call(d3.axisRight(legendScale)
                            .ticks(5))
                        .selectAll("text")
                        .style("font-size", "8px");
                }
                svg.append("g")
                    .attr("transform", `translate(0, ${height})`)
                    .call(d3.axisBottom(xScale).tickFormat(d => {
                        if (typeof d === "string" && d.includes("-")) {
                            const [min, max] = d.split("-").map(Number);
                            return `${d3.format(".3s")(min)}-${d3.format(".3s")(max)}`;
                        }
                        return d3.format(".3s")(d); 
                    }))                
                    .selectAll("text")
                    .style("text-anchor", "end")
                    .style("font-size", "8px")
                    .attr("dx", "-0.5em")
                    .attr("dy", "0.5em")
                    .attr("transform", "rotate(-45)");
        
                svg.append("g")
                    .call(d3.axisLeft(yScale))
                    .selectAll("text")
                    .style("font-size", "8px")
                    .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                    .append("title")  
                    .text(d => d);
            }

            /// All non numeric plot ///
            else{   
                if(groupByAttribute){       // Group by is active
                    const groupedData = d3.rollups(
                        data,
                        v => {
                            let groupCounts = {};
                            let groupIDs = {};  
                    
                            v.forEach(d => {
                                if (!groupCounts[d[groupByAttribute]]) {
                                    groupCounts[d[groupByAttribute]] = 0;
                                    groupIDs[d[groupByAttribute]] = [];  
                                }
                                groupCounts[d[groupByAttribute]] += 1;
                                groupIDs[d[groupByAttribute]].push(d.ID); 
                            });
                    
                            return { counts: groupCounts, ids: groupIDs }; 
                        },
                        d => d[xCol], 
                        d => d[yCol] 
                    );

                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            groups: groupData.counts, 
                            ids: groupData.ids 
                        }))
                    );

                    xScale = d3.scaleBand().domain(uniqueXCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(uniqueYCategories).range([height, 0]).padding(0.05);
                    const self = this; 

                    svg.selectAll("g.cell-group")
                        .data(heatmapData)
                        .join("g")
                        .attr("class", "cell-group")
                        .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                        .each(function (d) {
                            const g = d3.select(this);
                            let yOffset = 0;
                            const total = d3.sum(Object.values(d.groups));

                            Object.entries(d.groups).forEach(([group, count]) => {
                                g.append("rect")
                                    .attr("x", 0)
                                    .attr("y", yOffset) 
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)  
                                    .attr("fill", d => {
                                        if (!self.viewGroupsButton){
                                            return getFillColorHeatmap(d, group, numericData, xCol, yCol, meanX, stdDevX, meanY, stdDevY, self.selectedPoints, groupColorScale); 
                                        }
                                        return groupColorScale(group);
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? "black" : (this.viewGroupsButton ? "none" : "white");
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                        return isSelected ? 2 : 0.5;
                                    })
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });

                }
                else{       // No group by
                    const groupedData = d3.rollups(
                        data,
                        v => ({
                            count: v.length,  
                            ids: v.map(d => d.ID) 
                        }),  
                        d => d[xCol],
                        d => d[yCol]
                    );
        
                    const heatmapData = groupedData.flatMap(([xKey, yValues]) =>
                        yValues.map(([yKey, groupData]) => ({
                            x: xKey,
                            y: yKey,
                            value: groupData.count,  
                            ids: groupData.ids 
                        }))
                    );
        
                    xScale = d3.scaleBand().domain(uniqueXCategories).range([0, width]).padding(0.05);
                    yScale = d3.scaleBand().domain(uniqueYCategories).range([height, 0]).padding(0.05);
                    
                    const colorScale = d3.scaleSequential(d3.interpolateBlues)
                        .domain([0, d3.max(heatmapData, d => d.value)]);
                
                    svg.selectAll("rect")
                        .data(heatmapData)
                        .join("rect")
                        .attr("x", d => xScale(d.x))
                        .attr("y", d => yScale(d.y))
                        .attr("width", xScale.bandwidth())
                        .attr("height", yScale.bandwidth())
                        .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, this.errorColors, colorScale, this.selectedPoints))
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "gray";
                        })
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0.5
                        });
        
        
                    const legendHeight = height;
                    const legendWidth = 10;
                    const legendX = width + 5; 
                    const legendY = 0;
        
                    const legendScale = d3.scaleLinear()
                        .domain(colorScale.domain())
                        .range([legendHeight, 0]);
                
                    const linearGradient = defs.append("linearGradient")
                        .attr("id", gradientID)
                        .attr("x1", "0%").attr("x2", "0%")
                        .attr("y1", "100%").attr("y2", "0%");                
        
                    const numGradientStops = 10;
                    d3.range(numGradientStops).forEach(d => {
                        linearGradient.append("stop")
                            .attr("offset", `${(d / (numGradientStops - 1)) * 100}%`)
                            .attr("stop-color", colorScale(legendScale.domain()[0] + (d / (numGradientStops - 1)) * (legendScale.domain()[1] - legendScale.domain()[0])));
                    });
            
                    svg.append("rect")
                        .attr("x", legendX)
                        .attr("y", legendY)
                        .attr("width", legendWidth)
                        .attr("height", legendHeight)
                        .style("fill", `url(#${gradientID})`)
                        .attr("stroke", "black");
        
                    svg.append("g")
                        .attr("transform", `translate(${legendX + legendWidth}, ${legendY})`)
                        .call(d3.axisRight(legendScale)
                            .ticks(5))
                        .selectAll("text")
                        .style("font-size", "8px");
                }
                svg.append("g")
                    .attr("transform", `translate(0, ${height})`)
                    .call(d3.axisBottom(xScale))
                    .selectAll("text")
                    .style("text-anchor", "end")
                    .style("font-size", "8px")
                    .attr("dx", "-0.5em")
                    .attr("dy", "0.5em")
                    .attr("transform", "rotate(-45)")
                    .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                    .append("title")  
                    .text(d => d);
        
                svg.append("g")
                    .call(d3.axisLeft(yScale))
                    .selectAll("text")
                    .style("font-size", "8px")
                    .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                    .append("title")  
                    .text(d => d);
            }
        }
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
 * Preprocessing that splits data into
 *      All numeric,
 *      Non-numeric X,
 *      Non-numeric Y,
 *      and all non-numeric.
 * @param {*} data 
 * @param {*} xCol 
 * @param {*} yCol 
 * @returns Multiple splits on the dataset to be used in plotting.
 */
function splitData (data, xCol, yCol){
    const isNumeric = col => data.some(d => typeof d[col] === "number" && !isNaN(d[col]));

    const xIsNumeric = isNumeric(xCol);
    const yIsNumeric = isNumeric(yCol);

    const numericData = data.filter(d => 
        typeof d[xCol] === "number" && !isNaN(d[xCol]) && typeof d[yCol] === "number" && !isNaN(d[yCol])
    );
    
    const nonNumericXData = data.filter(d => 
        (typeof d[xCol] !== "number" || isNaN(d[xCol])) && typeof d[yCol] === "number" && !isNaN(d[yCol])
    ).map(d => ({
        ...d,
        [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    }));
    
    const nonNumericYData = data.filter(d => 
        typeof d[xCol] === "number" && !isNaN(d[xCol]) && (typeof d[yCol] !== "number" || isNaN(d[yCol]))
    ).map(d => ({
        ...d,
        [yCol]: typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol] 
    }));
    
    const nonNumericData = data.filter(d => 
        (typeof d[xCol] !== "number" || isNaN(d[xCol])) && (typeof d[yCol] !== "number" || isNaN(d[yCol]))
    ).map(d => ({
        ...d,
        [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol],
        [yCol]: typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol]
    }));

    const combinedData = [
        ...numericData.map(d => ({ ...d, type: "numeric" })),
        ...nonNumericXData.map(d => ({ ...d, type: "nan-x" })),
        ...nonNumericYData.map(d => ({ ...d, type: "nan-y" })),
        ...nonNumericData.map(d => ({ ...d, type: "nan-xy" }))
    ];

    const numericXData = data.filter(d => typeof d[xCol] === "number" && !isNaN(d[xCol]));
    const numericYData = data.filter(d => typeof d[yCol] === "number" && !isNaN(d[yCol]));

    const allNonNumericX = [...nonNumericXData, ...nonNumericData].filter(d =>
        typeof d[xCol] !== "number" || isNaN(d[xCol])
    ).map(d => ({
        ...d,
        [xCol]: (typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol])
    }));

    const allNonNumericY = [...nonNumericYData, ...nonNumericData].filter(d =>
        typeof d[yCol] !== "number" || isNaN(d[yCol])
    ).map(d => ({
        ...d,
        [yCol]: (typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol])
    }));

    const xIsNumericMajority = numericXData.length >= allNonNumericX.length;
    const yIsNumericMajority = numericYData.length >= allNonNumericY.length;

    const groupedXCategories = d3.group(allNonNumericX, d => String(d[xCol]));
    const groupedYCategories = d3.group(allNonNumericY, d => String(d[yCol]));

    let uniqueXCategories, uniqueYCategories;

    if (numericData.length === data.length)
    {
        uniqueXCategories = [];
        uniqueYCategories = [];
    }else if(xIsNumericMajority && yIsNumericMajority){
        uniqueXCategories = ["NaN",...[...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
        uniqueYCategories = ["NaN",...[...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
    }else if(!xIsNumericMajority && yIsNumericMajority){
        const mismatchXNums = numericXData
            .filter(d => typeof d[xCol] === "number" && !isNaN(d[xCol]))
            .map(d => String(d[xCol]));
        uniqueXCategories = ["NaN",...[...mismatchXNums, ...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
        uniqueYCategories = ["NaN",...[...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
    }else if(xIsNumericMajority && !yIsNumericMajority){
        const mismatchYNums = numericYData
            .filter(d => typeof d[yCol] === "number" && !isNaN(d[yCol]))
            .map(d => String(d[yCol]));
        uniqueXCategories = ["NaN",...[...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
        uniqueYCategories = ["NaN",...[...mismatchYNums, ...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
    }else{
        const mismatchXNums = numericXData
            .filter(d => typeof d[xCol] === "number" && !isNaN(d[xCol]))
            .map(d => String(d[xCol]));

        const mismatchYNums = numericYData
            .filter(d => typeof d[yCol] === "number" && !isNaN(d[yCol]))
            .map(d => String(d[yCol]));
        uniqueXCategories = ["NaN",...[...mismatchXNums, ...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
        uniqueYCategories = ["NaN",...[...mismatchYNums, ...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
    }

    const categorySpace = 20 * Math.max(uniqueXCategories.length, uniqueYCategories.length);
    const numericSpace = this.size - categorySpace;

    return {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace, xIsNumericMajority, yIsNumericMajority};
}

/**
 * Returns the fill color for a histogram bar when the data is numeric and there is no group by.
 * @param {*} d 
 * @param {*} xCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} selectedPoints 
 * @returns The fill color.
 */
function getFillColorNoGroupbyNumeric(d, xCol, columnErrors, errorColors, selectedPoints) {
    const isSelected = d.ids.some(ID => selectedPoints.some(p => p.ID === ID));
    if (isSelected) return "gold";

    const allErrors = [];

    for (const id of d.ids) {
        const xErrors = columnErrors[xCol]?.[id] || [];
        allErrors.push(...xErrors);
    }

    if (allErrors.length === 0) {
        return "steelblue";
    }

    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; 
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return "steelblue"; 
}

/**
 * Returns the fill color for a histogram bar when the data is numeric and grouped.
 * @param {*} d 
 * @param {*} xCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} selectedPoints 
 * @returns The fill color.
 */
function getFillColorNumeric(d, xCol, columnErrors, errorColors, selectedPoints) {
    const isSelected = d.data.groupIDs[d.group].some(ID => selectedPoints.some(p => p.ID === ID));                            
    if (isSelected) return "gold";

    const allErrors = [];

    for (const id of d.data.groupIDs[d.group]) {
        const xErrors = columnErrors[xCol]?.[id] || [];
        allErrors.push(...xErrors);
    }

    if (allErrors.length === 0) {
        return "steelblue"; 
    }

    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; 
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return "steelblue"; 
}

/**
* Returns the fill color for a histogram bar when the data is categorical and no group by.
 * @param {*} d 
 * @param {*} xCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} selectedPoints 
 * @returns The fill color.
 */
function getFillColorNoGroupbyCategorical(d, xCol, columnErrors, errorColors, selectedPoints) {
    const isSelected = d.ids.some(ID => selectedPoints.some(p => p.ID === ID));
    if (isSelected) return "gold";

    const allErrors = [];

    for (const id of d.ids) {
        const xErrors = columnErrors[xCol]?.[id] || [];
        allErrors.push(...xErrors);
    }

    if (allErrors.length === 0) {
        return "steelblue";
    }

    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; 
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return "steelblue"; 
}

/**
 * Returns the fill color for a histogram bar when the data is categorical and grouped.
 * @param {*} d 
 * @param {*} xCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} selectedPoints 
 * @returns The fill color.
 */
function getFillColorCategorical(d, xCol, columnErrors, errorColors, selectedPoints) {
    const isSelected = d.data.groupIDs[d.group].some(ID => selectedPoints.some(p => p.ID === ID));
    if (isSelected) return "gold";

    const allErrors = [];

    for (const id of d.data.groupIDs[d.group]) {
        const xErrors = columnErrors[xCol]?.[id] || [];
        allErrors.push(...xErrors);
    }

    if (allErrors.length === 0) {
        return "steelblue"; 
    }

    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; 
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return "steelblue"; 
}

/**
 * Returns the fill color for a heatmap bin when there is no group by.
 * @param {*} d 
 * @param {*} xCol 
 * @param {*} yCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} colorScale 
 * @param {*} selectedPoints 
 * @returns The fill color
 */
function getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, errorColors, colorScale, selectedPoints) {
    const isSelected = d.ids.some(ID => selectedPoints.some(p => p.ID === ID));
    if (isSelected) return "gold";

    const allErrors = [];

    for (const id of d.ids) {
        const xErrors = columnErrors[xCol]?.[id] || [];
        const yErrors = columnErrors[yCol]?.[id] || [];
        allErrors.push(...xErrors, ...yErrors);
    }

    if (allErrors.length === 0) {
        return colorScale(d.value); // no errors means normal heatmap color
    }

    // Count frequency of each error type
    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; // skip unknown error types
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    // Find the most frequent known error type
    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return colorScale(d.value);
}

/**
 * Returns the fill color for a heatmap bin when grouped.
 * @param {*} d 
 * @param {*} group 
 * @param {*} xCol 
 * @param {*} yCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} selectedPoints 
 * @returns The fill color
 */
function getFillColorHeatmap(d, group, xCol, yCol, columnErrors, errorColors, selectedPoints) {
    const isSelected = d.ids[group].some(ID => selectedPoints.some(p => p.ID === ID));
    if (isSelected) return "gold";

    const allErrors = [];

    for (const id of d.ids[group]) {
        const xErrors = columnErrors[xCol]?.[id] || [];
        const yErrors = columnErrors[yCol]?.[id] || [];
        allErrors.push(...xErrors, ...yErrors);
    }

    if (allErrors.length === 0) {
        return "steelblue"; 
    }

    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; 
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return "steelblue"; 
}

/**
 * Returns the fill color for a point.
 * @param {*} d 
 * @param {*} xCol 
 * @param {*} yCol 
 * @param {*} columnErrors 
 * @param {*} errorColors 
 * @param {*} selectedPoints 
 * @param {*} colorScale 
 * @returns The fill color.
 */
function getFillColorScatter(d, xCol, yCol, columnErrors, errorColors, selectedPoints, colorScale) {
    const allErrors = [];
    
    const xErrors = columnErrors[xCol]?.[d.ID] || [];
    const yErrors = columnErrors[yCol]?.[d.ID] || [];
    allErrors.push(...xErrors, ...yErrors);

    if (allErrors.length === 0) {
        return "steelblue";
    }

    const errorCounts = {};
    for (const error of allErrors) {
        if (!errorColors[error]) continue; 
        errorCounts[error] = (errorCounts[error] || 0) + 1;
    }

    let mostFrequentError = null;
    let maxCount = -1;

    for (const [error, count] of Object.entries(errorCounts)) {
        if (count > maxCount) {
        mostFrequentError = error;
        maxCount = count;
        }
    }

    if (mostFrequentError) {
        return errorColors[mostFrequentError];
    }

    return "steelblue"; 
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

