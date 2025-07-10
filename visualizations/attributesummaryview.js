



class AttributeSummaryView {
    constructor(container, model) {

        this.matrixView = new MatrixView(container, model);
        this.tableView = new TableView(container, model);

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

        this.selectedAttributes = ["ConvertedSalary"];                                         // The attributes currently selected by the user to be displayed in the matrix
        this.groupByAttribute = null;

        this.attributeElements = {}
        
    }

    /**
     * Populates the list of columns in the "Select Attributes" dropdown menu. Also initially populates the Attribute Summaries box.
     * @param {*} table Data
     * @param {*} controller 
     */
    populateDropdownFromTable(table, controller) {
        this.updateColumnErrorIndicators(table, controller);
    }


    createGroupByButton(attr){
        const groupByButton = document.createElement("div")
        groupByButton.classList.add( "rotatedButton");
        if( this.groupByAttribute === attr ) groupByButton.classList.add( "rotatedButtonSelected")

        const groupByButtonText = document.createElement("span");
        groupByButtonText.textContent = "GroupBy";
        groupByButtonText.style.fontSize = "12px";
        groupByButtonText.classList.add( "rotatedButtonText" );
        if( this.groupByAttribute === attr ) groupByButtonText.classList.add( "rotatedButtonTextSelected" );
        
        groupByButton.appendChild( this.groupByAttribute === attr ? groupByButtonText : groupByButtonText);

        groupByButton.onclick = () => {
            const isSelected = groupByButton.classList.toggle('rotatedButtonSelected');
            groupByButtonText.classList.toggle('rotatedButtonTextSelected');
            if( this.groupByAttribute !== null && this.groupByAttribute !== attr) {
                this.attributeElements[this.groupByAttribute].groupByButton.classList.toggle('rotatedButtonSelected');
                this.attributeElements[this.groupByAttribute].groupByButtonText.classList.toggle('rotatedButtonTextSelected');
            }
            this.groupByAttribute = (isSelected) ? attr : null;  // Toggle the groupByAttribute based on selection
        };  

        this.attributeElements[attr].groupByButton = groupByButton;
        this.attributeElements[attr].groupByButtonText = groupByButtonText;

        return groupByButton
    }


    createSelectButton(attr) {
        const selButton = document.createElement("div")
        selButton.classList.add("rotatedButton") 
        if( this.selectedAttributes.includes(attr) ) selButton.classList.add("rotatedButtonSelected");

        const selButtonText = document.createElement("span");
        selButtonText.textContent = ( this.selectedAttributes.includes(attr) ) ? "Selected" : "Select";
        selButtonText.style.fontSize = "12px";
        selButtonText.classList.add("rotatedButtonText");
        if( this.selectedAttributes.includes(attr) ) selButtonText.classList.add("rotatedButtonTextSelected");

        selButton.appendChild(selButtonText);

        selButton.onclick = () => {
            const isSelected = selButton.classList.toggle('rotatedButtonSelected');
            selButtonText.classList.toggle('rotatedButtonTextSelected');
            selButtonText.textContent = isSelected ? 'Selected' : 'Select';

            if( isSelected ) {
                this.selectedAttributes.push(attr);
            }
            else{
                this.selectedAttributes = this.selectedAttributes.filter(selectedAttr => selectedAttr !== attr);
            }
            if( this.selectedAttributes.length > 3 ) {
                let removeAttr = this.selectedAttributes.shift();
                this.attributeElements[removeAttr].selButton.classList.toggle('rotatedButtonSelected');
                this.attributeElements[removeAttr].selButtonText.classList.toggle('rotatedButtonTextSelected');
                this.attributeElements[removeAttr].selButtonText.textContent = 'Select';
            }
        };  

        this.attributeElements[attr].selButton = selButton;
        this.attributeElements[attr].selButtonText = selButtonText;

        return selButton
    }

    sortAttributes(attributes, columnErrors) {
        const sortBy = document.getElementById("sort-errors").value || "total";
        console.log("sortBy", sortBy);

        return attributes.sort((a, b) => {
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

    }

    /**
     * Updates the Attribute Summaries as data is wrangled and if the user changes which error type to sort on.
     * @param {*} table 
     * @param {*} controller 
     * @returns If the container does not exist, else should just update the UI.
     */
    updateColumnErrorIndicators(table, controller) {

        let summaryData = query_attribute_summary(controller,table);
        console.log("summaryData", summaryData);

        const columnErrors = summaryData.columnErrors;
        const attributes = summaryData.attributes;
        const attributeDistributions = summaryData.attributeDistributions;

        const sortedAttributes = this.sortAttributes(attributes, columnErrors);

        const container = document.getElementById("attribute-list");
        if (!container) return;
        
        const ul = document.getElementById("attribute-summary-list");
        ul.innerHTML = "";
            
        sortedAttributes.forEach(attr => {
            this.attributeElements[attr] = {}

            // Create a list item for the attribute
            const li = document.createElement("li");
            li.style.display = "flex";
            li.style.flexDirection = "row";
            li.style.gap = "4px";
            li.style.marginBottom = "16px";

            li.appendChild(this.createSelectButton(attr));
            li.appendChild(this.createGroupByButton(attr));

            //
            //
            // Create the main content area for the attribute summary
            const div = document.createElement("div");
            div.style.display = "flex";
            div.style.flexDirection = "column";
            div.style.gap = "4px";
            div.style.flexGrow = "1";
            li.appendChild(div);


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

            div.appendChild(topRow);

            const columnData = table.array(attr).filter(d => d !== "" && d !== null && d !== undefined);
            const isNumeric = columnData.some(v => typeof v === "number" && !isNaN(v));

            const stats = document.createElement("div");
            stats.classList.add("column-stats");

            const attrDist = attributeDistributions[attr] || {};

            let statsHTML = "";
            if ("numeric" in attrDist) {
                statsHTML += `<div>Mean: ${attrDist.numeric.mean.toFixed(2)}</div>
                              <div>Range: ${attrDist.numeric.min} - ${attrDist.numeric.max}</div>`;
            }
            if ("categorical" in attrDist) {
                statsHTML += `<div>Mode Category: ${truncateText(attrDist.categorical.mode, 50)}</div>
                              <div>Category Count: ${attrDist.categorical.categories}</div>`;
            }
            stats.innerHTML = statsHTML;
            

            // if (isNumeric) {
            //     const mean = d3.mean(columnData);
            //     const min = d3.min(columnData);
            //     const max = d3.max(columnData);
            //     stats.innerHTML = `<div>Mean: ${mean.toFixed(2)}</div>
            //                         <div>Range: ${min} - ${max}</div>`;
            // } else {
            //     const mode = [...d3.rollup(columnData, v => v.length, d => d)]
            //         .sort((a, b) => b[1] - a[1])[0][0];
            //     const sortedVals = sortCategories(columnData.slice());
            //     const min = sortedVals[0];
            //     const max = sortedVals[sortedVals.length - 1];

            //     stats.innerHTML = `<div>Mode: ${truncateText(mode, 50)}</div>
            //                         <div>Range: ${truncateText(min, 50)} - ${truncateText(max, 50)}</div>`;
            // }

            div.appendChild(stats);

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

            div.appendChild(barContainer);
    
            ul.appendChild(li);
        });
    
        container.appendChild(ul);
    }
}

