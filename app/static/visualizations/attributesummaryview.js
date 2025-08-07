
class AttributeSummaryView {
    constructor(container, model) {

        this.container = container;
        this.selectedAttributes = ["ConvertedSalary"];                                         // The attributes currently selected by the user to be displayed in the matrix
        this.groupByAttribute = null;

        this.attributeElements = {}

        this.errorTypes = {"total": "Total Error %",
                            "missing": "Missing Values", 
                            "mismatch": "Data Type Mismatch", 
                            "anomaly": "Average Anomalies (Outliers)", 
                            "incomplete": "Incomplete Data (< 3 points)", 
                            "none": "None"};

        this.errorColors = d3.scaleOrdinal()
                                .domain(Object.keys(this.errorTypes))
                                .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);

        this.sortBy = "total";  // Default sort by total errors

        this.sortElements = {}
        
    }

    /**
     * Populates the list of columns in the "Select Attributes" dropdown menu. Also initially populates the Attribute Summaries box.
     * @param {*} table Data
     * @param {*} controller
     */
    async populateDropdownFromTable(table, controller) {
        this.createSortingLegend(table, controller);

        // const summaryData = query_attribute_summary(controller,table);
        // console.log("Summary Data:",summaryData)

        let minID = 0;
        let maxID = 400;
        let summaryData;
        try {
            const { queryAttributeSummaries } = await import("../js/serverCalls.js");
            let response = await queryAttributeSummaries(controller.model.getSampleIDRangeMin(), controller.model.getSampleIDRangeMax())
            summaryData = response["data"]
        } catch (error) {
            console.error(error.message)
        }
        console.log("attribute summaries from the server", summaryData)

        const sortedAttributes = this.sortAttributes(summaryData.attributes, summaryData.columnErrors);

        this.selectedAttributes = sortedAttributes.slice(0, 3);  // Default to first 3 attributes
        controller.updateGrouping(this.selectedAttributes, this.groupByAttribute)


        this.updateColumnErrorIndicators(table, controller, summaryData, sortedAttributes);


    }

    createSortingLegend(table, controller){

        // const legendContainer = d3.select("#attribute-sorting");
        const legendContainer = document.getElementById("attribute-sorting");
        legendContainer.innerHTML = "";
        // legendContainer.selectAll(".legend-item").remove();

        const legendTitle = document.createElement("div");
        legendTitle.textContent = "Sort Attributes By";
        legendTitle.classList.add("attribute-sorting-title");
        legendContainer.append(legendTitle);

        Object.keys(this.errorTypes).forEach((error, i) => {
            const legendItem = document.createElement("div")
            legendItem.classList.add("attribute-sorting-item");
            legendContainer.append(legendItem)

            const legendBox = document.createElement("span");
            legendBox.classList.add(( error === this.sortBy ) ? "attribute-sorting-item-color-selected" : "attribute-sorting-item-color" );
            legendBox.style.backgroundColor = this.errorColors(error);
            legendItem.append(legendBox);
            this.sortElements[error] = legendBox;

            const legendText = document.createElement("span");
            legendText.textContent = this.errorTypes[error];
            legendItem.append(legendText);

            legendItem.onclick = () => {
                if( this.sortBy === error ) return;  // No change

                this.sortElements[this.sortBy].classList.toggle("attribute-sorting-item-color-selected");
                this.sortElements[this.sortBy].classList.toggle("attribute-sorting-item-color");

                legendBox.classList.toggle("attribute-sorting-item-color-selected");
                legendBox.classList.toggle("attribute-sorting-item-color");

                this.sortBy = error;

                this.updateColumnErrorIndicators(table, controller)
            };
        });
    }

    createGroupByButton(attr, controller){
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

            controller.updateGrouping (this.selectedAttributes, this.groupByAttribute)
        };  

        this.attributeElements[attr].groupByButton = groupByButton;
        this.attributeElements[attr].groupByButtonText = groupByButtonText;

        return groupByButton
    }


    createSelectButton(attr, controller) {
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

            controller.updateGrouping (this.selectedAttributes, this.groupByAttribute)

        };  

        this.attributeElements[attr].selButton = selButton;
        this.attributeElements[attr].selButtonText = selButtonText;

        return selButton
    }

    sortAttributes(attributes, columnErrors) {
        // const sortBy = document.getElementById("sort-errors").value || "total";
        // console.log("sortBy", sortBy);

        return attributes.sort((a, b) => {
          const errorsA = columnErrors[a] || {};
          const errorsB = columnErrors[b] || {};

          // Primary: specific error type (or 0 if not present)
          const primaryA = this.sortBy === "total" ? 0 : (errorsA[this.sortBy] || 0);
          const primaryB = this.sortBy === "total" ? 0 : (errorsB[this.sortBy] || 0);

          // Secondary: total error percentage
          const totalA = Object.values(errorsA).reduce((sum, pct) => sum + pct, 0);
          const totalB = Object.values(errorsB).reduce((sum, pct) => sum + pct, 0);

          if (this.sortBy === "total") {
              // Sort by total error only
              return totalB - totalA;
          }
          else if (this.sortBy === "none") {
              // Sort by clean percentage (ascending)
              return totalA - totalB;
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
    async updateColumnErrorIndicators(table, controller, summaryData = null, sortedAttributes = null) {

        if (summaryData === null) {
            // summaryData = query_attribute_summary(controller,table);
            try {
                const {queryAttributeSummaries} = await import("../js/serverCalls.js");
                let response = await queryAttributeSummaries(controller.model.getSampleIDRangeMin(), controller.model.getSampleIDRangeMax())
                summaryData = response["data"]
            } catch (error) {
                console.error(error.message)
            }
        }
        // console.log("summaryData", summaryData);

        const columnErrors = summaryData.columnErrors;
        const attributes = summaryData.attributes;
        const attributeDistributions = summaryData.attributeDistributions;

        if (sortedAttributes === null) {
            sortedAttributes = this.sortAttributes(attributes, columnErrors);
        }

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

            li.appendChild(this.createSelectButton(attr, controller));
            li.appendChild(this.createGroupByButton(attr, controller));

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
                box.style.backgroundColor = this.errorColors(type);


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

            const stats = document.createElement("div");
            stats.classList.add("column-stats");

            const attrDist = attributeDistributions[attr] || {};

            let statsHTML = "";
            if ("numeric" in attrDist) {
                statsHTML += `<div>Numeric Mean: ${attrDist.numeric.mean.toFixed(2)}</div>
                              <div>Numeric Range: ${attrDist.numeric.min} - ${attrDist.numeric.max}</div>`;
            }
            if ("categorical" in attrDist) {
                statsHTML += `<div>Category Mode: ${truncateText(attrDist.categorical.mode, 50)}</div>
                              <div>Category Count: ${attrDist.categorical.categories}</div>`;
            }
            stats.innerHTML = statsHTML;

            div.appendChild(stats);

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

                segment.style.backgroundColor = this.errorColors(type);

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

