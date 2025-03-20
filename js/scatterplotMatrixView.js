
let selectedBar = null;
let barX0 = 0;
let barX1 = 0;

class ScatterplotMatrixView{
    constructor(container) {
        this.container = container;

        this.size = 180; // Size of each cell in matrix
        this.xPadding = 175;
        this.yPadding = 90;
        this.labelPadding = 60;

        this.leftMargin = 115;
        this.topMargin = 0;
        this.bottomMargin = 125; 
        this.rightMargin = 0; 

        this.selection = null;

        this.xScale = d3.scaleLinear().domain([0, 100]).range([0, this.size]);
        this.yScale = d3.scaleLinear().domain([0, 100]).range([this.size, 0]);
        this.brushXCol = 0;
        this.brushYCol = 0;

        this.selectedPoints = [];
        this.predicatePoints = [];
    }

    setSelectedPoints(points) {
        this.selectedPoints = points;
      }

    setPredicatePoints(points) {
        this.predicatePoints = points;
    }

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
    
        updateDropdownButton();
    }

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
            controller.predicateFilter(false); // Reset predicatePoints to [] and re-plot
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

    updateLegend(groupByAttribute, givenData) {
        const legendContainer = d3.select("#legend");
        legendContainer.html("");
      
        if (!groupByAttribute) {
          legendContainer.style("display", "none");
          return;
        }
        legendContainer.style("display", "block");
      
        const uniqueGroups = Array.from(new Set(givenData.objects().map(d => d[groupByAttribute])));
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
    }
    
    drawBoxPlots(groupStats, onSelectGroups, overallMedian, selectedGroups, significantGroups) {
        console.log("significant groups", significantGroups);
        const container = d3.select("#boxplot-container");
        container.html(""); 
    
        const width = 1300; 
        const height = 500; 
        const margin = { top: 30, right: 120, bottom: 50, left: 100 };

        const salaryExtent = d3.extent(groupStats.flatMap(d => [d.min, d.max]));
    
        salaryExtent[0] = Math.min(salaryExtent[0], overallMedian);
        salaryExtent[1] = Math.max(salaryExtent[1], overallMedian);
    
        const xScale = d3.scaleBand()
                         .domain(groupStats.map(d => d.group))
                         .range([margin.left, width - margin.right])
                         .padding(0.2);
    
        const yScale = d3.scaleLinear()
                         .domain(salaryExtent)
                         .range([height - margin.bottom, margin.top]);
    
        const svg = container.append("svg")
                             .attr("width", width)
                             .attr("height", height);
    
        svg.append("g")
            .attr("transform", `translate(${margin.left}, 0)`)
            .call(d3.axisLeft(yScale).ticks(10));
    
        svg.append("g")
            .attr("transform", `translate(0, ${height - margin.bottom})`)
            .call(d3.axisBottom(xScale))
            .selectAll("text") 
            .style("font-size", "10px")
            .style("fill", d => significantGroups.some(group => group.group === d) ? "red" : "black")            
            .text(d => d.length > 10 ? d.substring(0, 12) + "…" : d)  
            .append("title")  
            .text(d => d);
    
        svg.append("line")
            .attr("x1", margin.left)
            .attr("x2", width - margin.right)
            .attr("y1", yScale(overallMedian))
            .attr("y2", yScale(overallMedian))
            .attr("stroke", "blue")
            .attr("stroke-dasharray", "5,5") 
            .attr("stroke-width", 2);
    
        svg.append("text")
            .attr("x", width - margin.right) 
            .attr("y", yScale(overallMedian) + 4) 
            .attr("fill", "blue")
            .attr("font-size", "10px")
            .attr("font-weight", "bold")
            .attr("text-anchor", "start") 
            .text(`Dataset Median: ${overallMedian.toFixed(2)}`);

        svg.append("text")
            .attr("x", 0) 
            .attr("y", 0) 
            .attr("transform", `translate(${margin.left - 60}, ${height / 2}) rotate(-90)`) 
            .attr("text-anchor", "middle") 
            .attr("font-size", "18px") 
            .text("Salary $");
    
        groupStats.forEach(d => {
            const groupX = xScale(d.group) + xScale.bandwidth() / 2; 
    
            svg.append("line")
                .attr("x1", groupX).attr("x2", groupX)
                .attr("y1", yScale(d.min)).attr("y2", yScale(d.max))
                .attr("stroke", "black");
    
            svg.append("rect")
                .attr("x", xScale(d.group))
                .attr("width", xScale.bandwidth())
                .attr("y", yScale(d.q3))
                .attr("height", yScale(d.q1) - yScale(d.q3)) 
                .attr("fill", "steelblue").attr("opacity", 0.6);
    
            svg.append("line")
                .attr("x1", xScale(d.group)).attr("x2", xScale(d.group) + xScale.bandwidth())
                .attr("y1", yScale(d.median)).attr("y2", yScale(d.median))
                .attr("stroke", "black").attr("stroke-width", 2);
        });
    
        const checkboxContainer = container.append("div")
            .attr("id", "checkbox-container")
            .style("position", "absolute")
            .style("top", `${height - margin.bottom + 80}px`) 
            .style("left", "0px") 
            .style("width", `${width}px`) 
            .style("display", "flex")
            .style("justify-content", "center") 
            .style("gap", "10px");

        groupStats.forEach((d, i) => {
            const whiskerX = xScale(d.group) + xScale.bandwidth() / 2 + 20; 

            const checkboxWrapper = checkboxContainer.append("div")
                .attr("class", "group-checkbox")
                .style("position", "absolute") 
                .style("left", `${whiskerX}px`) 
                .style("transform", "translateX(-50%)") 
                .style("text-align", "center");

            const checkbox = checkboxWrapper.append("input")
                .attr("type", "checkbox")
                .attr("value", d.group)
                .attr("id", `checkbox-${i}`);

            if (selectedGroups.includes(d.group)) {
                checkbox.property("checked", true);
            }

            checkbox.on("change", function () {
                onSelectGroups();
            });
        });

        const legend = svg.append("g")
            .attr("transform", `translate(${width - margin.right - 300}, ${margin.top - 30})`);

        legend.append("rect")
            .attr("width", 15)
            .attr("height", 15)
            .attr("fill", "red")
            .attr("stroke", "black")
            .attr("stroke-width", 1);

        legend.append("text")
            .attr("x", 20) 
            .attr("y", 12) 
            .attr("font-size", "12px")
            .attr("fill", "black")
            .text("Indicates groups > 2 Median Absolute Deviations (MAD) from dataset median");
    }

    plotMatrix(givenData, groupByAttribute, selectedGroups, selectionEnabled, animate, handleBrush, handleBarClick, handleHeatmapClick) {  
        console.log("matrix predicate points", this.predicatePoints);
        const colorScale = d3.scaleOrdinal(d3.schemeCategory10);

        let columns = givenData.columnNames().slice(1).filter(col => col !== groupByAttribute);
        let matrixWidth = columns.length * this.size + (columns.length - 1) * this.xPadding; // 3 * 175 + (2) * 25 = 575
        let matrixHeight = columns.length * this.size + (columns.length - 1) * this.yPadding; // 3 * 175 + (2) * 25 = 575

        let svgWidth = matrixWidth + this.labelPadding + this.leftMargin + this.rightMargin;
        let svgHeight = matrixHeight + this.labelPadding + this.topMargin + this.bottomMargin;

        let maxUqNonNum = 0;

        columns.forEach(yCol => {
            const yValues = givenData.select([yCol]).objects().map(d => d[yCol]);
            const uniqueNonNumericY = new Set(yValues.filter(val => isNaN(val) || typeof val !== "number"));
            maxUqNonNum = Math.max(maxUqNonNum, uniqueNonNumericY.size);
        });

        this.topMargin = 30 + maxUqNonNum * 10; 

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

            if (i === j) {
                let data = [];

                if (groupByAttribute){
                    data = givenData.select(["ID", xCol, groupByAttribute]).objects();
                }
                else{
                    data = givenData.select(["ID", xCol]).objects();
                }

                const numericData = data.filter(d => 
                    typeof d[xCol] === "number" && !isNaN(d[xCol])
                );
                
                const nonNumericData = data.filter(d => 
                    typeof d[xCol] !== "number" || isNaN(d[xCol])
                ).map(d => ({
                    ...d,
                    [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
                }));

                const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));

                let uniqueCategories;
                
                if (numericData.length === data.length)
                {
                    uniqueCategories = [];
                }else{
                    // uniqueCategories = ["NaN", ...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
                    uniqueCategories = [...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
                }

                const categorySpace = uniqueCategories.length * 20; 
                const numericSpace = this.size - categorySpace; 
                let categoricalScale = null;
                const tooltip = d3.select("#tooltip");
                let bars = null;
                let yScale = null;
                
                if (numericData.length > 0)
                {
                    uniqueCategories = sortCategories(uniqueCategories);
                    const xScale = d3.scaleLinear()
                        .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
                        .range([0, numericSpace]);
                    
                    const histogramGenerator = d3.histogram()
                        .domain(xScale.domain())
                        .thresholds(10);

                    const bins = histogramGenerator(numericData.map(d => d[xCol]));

                    if (groupByAttribute) {
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
                            .domain(uniqueCategories)
                            .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 
    
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
                            .range([this.size, 0]);
                
                        const stackGen = d3.stack().keys(groups);
                        const series = stackGen(stackedData);
                
                        bars = cellGroup.selectAll("g.series")
                            .data(series)
                            .join("g")
                            .attr("class", "series")
                            // .attr("fill", d => d.category ? "gray" : colorScale(d.key))
                            .attr("data-group", d => d.key)  
                            .selectAll("rect")
                            .data(d => {
                                d.forEach(item => item.group = d.key);  
                                return d;
                            })
                            .join("rect")
                            .attr("fill", d => d.category ? "gray" : colorScale(d.group))
                            .attr("opacity", (d) => {
                                const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));
                                if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                else {return 1;}
                            })
                            .attr("stroke", (d) => {
                                const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? "black" : "none";
                            })
                            .attr("stroke-width", (d) => {
                                const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? 2 : 0;
                            })
                            .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.data.x0))
                            .attr("width", binWidth);
                    }
                    else{
                        // No group by
                        const histData = histogramGenerator(numericData.map(d => d[xCol])).map(bin => {
                            return {
                                x0: bin.x0,
                                x1: bin.x1,
                                length: bin.length,
                                ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.ID)
                            };
                        });
    
                        const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
                        const categoricalStart = xScale.range()[1] + 10;
    
                        categoricalScale = d3.scaleOrdinal()
                            .domain(uniqueCategories)
                            .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 
    
                        uniqueCategories.forEach(category => {
                            histData.push({
                                x0: categoricalScale(category),
                                x1: categoricalScale(category) + binWidth,
                                length: nonNumericData.filter(d => String(d[xCol]) === category).length,
                                ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.ID),
                                category: category 
                            });
                        });
                        console.log("uniqueCat", uniqueCategories);
    
                        yScale = d3.scaleLinear()
                            .domain([0, d3.max(histData, (d) => d.length)])
                            .range([this.size, 0]);
                            
                        bars = cellGroup.selectAll("rect")
                            .data(histData)
                            .join("rect")
                            .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.x0))
                            .attr("width", binWidth)
                            // .attr("y", d => yScale(d.length))
                            // .attr("height", d => numericSpace - yScale(d.length))
                            .attr("fill", (d) => {
                                const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                                return isSelected ? "gold" : (d.category ? "gray" : "steelblue");
                            })
                            // .attr("stroke", d => d.category ? "red" : "none")
                            .attr("stroke", (d) => {
                                const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                                return isPredicated ? "red" : "none";
                            })
                            // .attr("stroke-width", d => d.category ? 1 : 0)
                            .attr("stroke-width", (d) => {
                                const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                                return isPredicated ? 1 : 0
                            })
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.ids.join(","));   
                    }
                    
                    cellGroup
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
                        cellGroup.append("g")
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

                    cellGroup.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2) 
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) 
                        .style("text-anchor", "middle")
                        .text(xCol);
        
                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2) - categorySpace; 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text("count");
                }
                else{   // Data is all categorical
                    // uniqueCategories = uniqueCategories.slice(1);
                    uniqueCategories = sortCategories(uniqueCategories);

                    const xScale = d3.scaleBand()
                        .domain(uniqueCategories)
                        .range([0, this.size]);

                    if (groupByAttribute) {
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
                        yScale = d3.scaleLinear().domain([0, yMax]).range([this.size, 0]);
                        
                        const stackGen = d3.stack().keys(groups);
                        const series = stackGen(stackedData);
                        
                        bars = cellGroup.selectAll("g.series")
                            .data(series)
                            .join("g")
                            .attr("class", "series")
                            // .attr("fill", d => colorScale(d.key))
                            .attr("data-group", d => d.key)  
                            .selectAll("rect")
                            .data(d => {
                                d.forEach(item => item.group = d.key);  
                                return d;
                            })
                            .join("rect")
                            .attr("fill", d => colorScale(d.group))
                            .attr("opacity", (d) => {
                                const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));
                                if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                else {return 1;}
                            })
                            .attr("stroke", (d) => {
                                const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? "black" : "none";
                            })
                            .attr("stroke-width", (d) => {
                                const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? 2 : 0;
                            })
                            .attr("x", d => xScale(d.data.category))
                            .attr("width", xScale.bandwidth());                          
                    }
                    else{
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
                            .range([this.size, 0]);
                        
                        bars = cellGroup.selectAll("rect")
                            .data(histData)
                            .join("rect")
                            .attr("x", d => xScale(d.category))
                            .attr("width", xScale.bandwidth())
                            .attr("fill", (d) => {
                                const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                                return isSelected ? "gold" : "steelblue";
                            })
                            .attr("stroke", (d) => {
                                const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                                return isPredicated ? "red" : "none";
                            })
                            .attr("stroke-width", (d) => {
                                const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                                return isPredicated ? 1 : 0
                            })
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.ids.join(","));
                    }
                    
                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${this.size})`)
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

                    cellGroup.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");
                        
                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2) 
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) 
                        .style("text-anchor", "middle")
                        .text(xCol);
        
                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text("count");
                }  
                
                // Animation, tooltip, and handle bar clicks behavior varies if group by is on or not
                if(groupByAttribute){
                    if(animate){
                        bars.attr("y", this.size)
                        .attr("height", 0)
                        .transition() 
                        .duration(800)
                        .ease(d3.easeCubicOut)
                        .attr("y", d => yScale(d[1])) 
                        .attr("height", d => yScale(d[0]) - yScale(d[1]));
                    } else{
                        bars.attr("y", d => yScale(d[1]))  
                            .attr("height", d => yScale(d[0]) - yScale(d[1]));
                    }
                    bars.on("mouseover", function(event, d) {
                        const group = d3.select(this.parentNode).datum().key;
                        const count = d[1] - d[0];
                        const totalCount = d.data.total;
                        d3.select(this).attr("opacity", 0.5);
                        tooltip.style("display", "block")
                            .html(`<strong>Bin Range:</strong> ${d.data.x0.toFixed(2)} - ${d.data.x1.toFixed(2)}<br><strong>${group} Count:</strong> ${count}<br><strong>Total Bin Count:</strong> ${totalCount}`)
                            .style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mousemove", function(event) {
                        tooltip.style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mouseout", function() {
                        const group = d3.select(this.parentNode).datum().key;
                        d3.select(this).attr("opacity", 0.8);
                        tooltip.style("display", "none");
                    })
                    .attr("data-ids", d => d.data.ids.join(","))
                    .on("click", function (event, d) {
                        if (!selectionEnabled) return;   
                        const group = d3.select(this.parentNode).datum().key;  
                        handleBarClick(event, d, xCol, groupByAttribute, group)
                    });
                }
                else{
                    if(animate){
                        bars.attr("y", this.size)
                            .attr("height", 0)
                            .transition() 
                            .duration(800)
                            .ease(d3.easeCubicOut)
                            .attr("y", d => yScale(d.length)) 
                            .attr("height", d => Math.max(0, this.size - yScale(d.length)));
                    } else{
                        bars.attr("y", d => yScale(d.length)) 
                            .attr("height", d => Math.max(0, this.size - yScale(d.length)));
                    }
                    bars.on("mouseover", function(event, d) {
                        d3.select(this).attr("opacity", 0.5);
                        tooltip.style("display", "block")
                            .html(`<strong>${d.category}</strong><br><strong>Count: </strong>${d.length}`)
                            .style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mousemove", function(event) {
                        tooltip.style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mouseout", function() {
                        d3.select(this).attr("opacity", 0.8);
                        tooltip.style("display", "none");
                    })
                    .attr("data-ids", d => d.ids.join(","))
                    .on("click", function (event, d) {
                        if (!selectionEnabled) return;
                        handleBarClick(event, d, xCol, groupByAttribute)
                    });
                }                
            } 
            else {
                const heatMapViewButton = cellGroup.append("image")
                .attr("class", "heatmap-button active")
                .attr("x", -110)  
                .attr("y", -60)   
                .attr("width", 45) 
                .attr("height", 25)
                .attr("xlink:href", "icons/heatmap.png")
                .attr("cursor", "pointer")
                .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    
                const scatterViewButton = cellGroup.append("image")
                    .attr("class", "scatterplot-button")
                    .attr("x", -110)  
                    .attr("y", -35)   
                    .attr("width", 45) 
                    .attr("height", 25)
                    .attr("xlink:href", "icons/scatterplot.png")
                    .attr("cursor", "pointer")
                    .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

                const lineViewButton = cellGroup.append("image")
                    .attr("class", "linechart-button")
                    .attr("x", -110)  
                    .attr("y", -10)   
                    .attr("width", 45) 
                    .attr("height", 25)
                    .attr("xlink:href", "icons/linechart.png")
                    .attr("cursor", "pointer")
                    .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

                this.drawHeatMap(cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);

            }
            });
        });

        this.updateLegend(groupByAttribute, givenData);

    }

    enableBrushing (givenData, handleBrush, handleBarClick, groupByAttribute){
        const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

        const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

        let columns = givenData.columnNames().slice(1).filter(col => col !== groupByAttribute);
        let matrixWidth = columns.length * this.size + (columns.length - 1) * this.xPadding; // 3 * 175 + (2) * 25 = 575
        let matrixHeight = columns.length * this.size + (columns.length - 1) * this.yPadding; // 3 * 175 + (2) * 25 = 575

        let svgWidth = matrixWidth + this.labelPadding + this.leftMargin + this.rightMargin;
        let svgHeight = matrixHeight + this.labelPadding + this.topMargin + this.bottomMargin;

        let maxUqNonNum = 0;

        columns.forEach(yCol => {
            const yValues = givenData.select([yCol]).objects().map(d => d[yCol]);
            const uniqueNonNumericY = new Set(yValues.filter(val => isNaN(val) || typeof val !== "number"));
            maxUqNonNum = Math.max(maxUqNonNum, uniqueNonNumericY.size);
        });

        this.topMargin = 30 + maxUqNonNum * 10; 

        this.barSelected = false;
        const container = d3.select(this.container);
        container.selectAll("*").remove();
    
        const svg = container
            .append("svg")
            .attr("width", svgWidth) // 575 + 20 + 60 + 60 = 715
            .attr("height", svgHeight);

        columns.forEach((xCol, i) => {
            columns.forEach((yCol, j) => {
            const cellGroup = svg
                .append("g")
                .attr("transform", `translate(${this.leftMargin + j * (this.size + this.xPadding)}, ${this.topMargin + i * (this.size + this.yPadding)})`);  

            if (i === j) {
                
                let data = [];
                
                if(groupByAttribute){
                    data = givenData.select(["ID", xCol, groupByAttribute]).objects();
                }
                else{
                    data = givenData.select(["ID", xCol]).objects();
                }

                const numericData = data.filter(d => 
                    typeof d[xCol] === "number" && !isNaN(d[xCol])
                );
                
                const nonNumericData = data.filter(d => 
                    typeof d[xCol] !== "number" || isNaN(d[xCol])
                ).map(d => ({
                    ...d,
                    [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
                }));

                const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));

                let uniqueCategories;
                
                if (numericData.length === data.length)
                {
                    uniqueCategories = [];
                }else{
                    uniqueCategories = ["NaN", ...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
                }

                const categorySpace = uniqueCategories.length * 20; 
                const numericSpace = this.size - categorySpace; 
                let categoricalScale = null;

                if (numericData.length > 0)
                {
                    uniqueCategories = sortCategories(uniqueCategories);
                    const xScale = d3.scaleLinear()
                        .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
                        .range([0, numericSpace]);

                    let yScale = null;
                    
                    const histogramGenerator = d3.histogram()
                        .domain(xScale.domain())
                        .thresholds(10);

                    const bins = histogramGenerator(numericData.map(d => d[xCol]));

                    if (groupByAttribute) {
                        const groups = Array.from(new Set(numericData.map(d => d[groupByAttribute])));
                        const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(groups);
                
                        const stackedData = bins.map(bin => {
                            const binData = numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1);
                            let obj = {
                                x0: bin.x0,
                                x1: bin.x1,
                                total: binData.length,  
                                ids: binData.map(d => d.ID)
                            };
                            groups.forEach(g => {
                                const groupData = binData.filter(d => d[groupByAttribute] === g);
                                obj[g] = groupData.length;
                                obj[`${g}_ids`] = groupData.map(d => d.ID);
                            });
                            return obj;
                        });
                
                        const binWidth = xScale(bins[0].x1) - xScale(bins[0].x0);

                        const categoricalStart = xScale.range()[1] + 10;
    
                        categoricalScale = d3.scaleOrdinal()
                            .domain(uniqueCategories)
                            .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 
    
                        uniqueCategories.forEach(category => {
                            const catData = nonNumericData.filter(d => String(d[xCol]) === category);
                            let obj = {
                                category: category, 
                                x0: categoricalScale(category),
                                x1: categoricalScale(category) + binWidth,
                                total: catData.length,
                                ids: catData.map(d => d.ID)
                            };
                            groups.forEach(g => {
                                const groupData = catData.filter(d => d[groupByAttribute] === g);
                                obj[g] = groupData.length;
                                obj[`${g}_ids`] = groupData.map(d => d.ID);
                            });
                            stackedData.push(obj);
                        });
                
                        const yMax = d3.max(stackedData, d => d.total);
                        yScale = d3.scaleLinear()
                            .domain([0, yMax])
                            .range([numericSpace, 0]);
                
                        const stackGen = d3.stack().keys(groups);
                        const series = stackGen(stackedData);

                        series.forEach(s => {
                            s.forEach(segment => {
                              segment.group = s.key;
                            });
                          });
                
                        const tooltip = d3.select("#tooltip");
                
                        cellGroup.selectAll("g.series")
                            .data(series)
                            .join("g")
                            .attr("class", "series")
                            .attr("fill", d => d.category ? "gray" : colorScale(d.key))
                            .selectAll("rect")
                            .data(d => d)
                            .join("rect")
                            .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.data.x0))
                            .attr("y", d => yScale(d[1]))
                            .attr("width", binWidth)
                            .attr("height", d => yScale(d[0]) - yScale(d[1]))
                            .attr("data-ids", d => d.data.ids.join(","))
                            .on("click", (event, d) => handleBarClick(event, d, xCol, groupByAttribute, group));
                    }
                    else{
                        // No group by
                        const histData = histogramGenerator(numericData.map(d => d[xCol])).map(bin => {
                            return {
                                x0: bin.x0,
                                x1: bin.x1,
                                length: bin.length,
                                ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.ID)
                            };
                        });
    
                        const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
                        const categoricalStart = xScale.range()[1] + 10;
    
                        categoricalScale = d3.scaleOrdinal()
                            .domain(uniqueCategories)
                            .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 
    
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
                            .range([numericSpace, 0]);
                        
                        const tooltip = d3.select("#tooltip");
    
                        cellGroup.selectAll("rect")
                            .data(histData)
                            .join("rect")
                            .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.x0))
                            .attr("width", binWidth)
                            .attr("y", d => yScale(d.length))
                            .attr("height", d => numericSpace - yScale(d.length))
                            .attr("fill", (d) => {
                                const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                                return isSelected ? "red" : (d.category ? "gray" : "steelblue");
                            })
                            .attr("stroke", d => d.category ? "red" : "none")
                            .attr("stroke-width", d => d.category ? 1 : 0)
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.ids.join(","))
                            .on("click", (event, d) => handleBarClick(event, d, xCol, groupByAttribute));
                    }

                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${numericSpace})`)
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

                    if (uniqueCategories.length > 0) {
                        cellGroup.append("g")
                            .attr("transform", `translate(10, ${numericSpace})`)
                            .call(d3.axisBottom(categoricalScale))
                            .selectAll("text")
                            .style("text-anchor", "end") 
                            .attr("transform", "rotate(-45)") 
                            .style("font-size", "8px")
                            .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                            .append("title") 
                            .text(d => d);
                    }
                    cellGroup.append("g")
                        .call(d3.axisLeft(yScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d); 

                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2) 
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - categorySpace - 25) 
                        .style("text-anchor", "middle")
                        .text(xCol);
        
                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2) - categorySpace; 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text("count");
                }
                else{   // Data is all categorical
                    uniqueCategories = uniqueCategories.slice(1);
                    uniqueCategories = sortCategories(uniqueCategories);

                    const xScale = d3.scaleBand()
                        .domain(uniqueCategories)
                        .range([0, this.size]);

                    let yScale = null;

                    if (groupByAttribute) {
                        const groups = Array.from(new Set(nonNumericData.map(d => d[groupByAttribute])));
                        const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(groups);
                        
                        // d[0].data.ids
                        const stackedData = uniqueCategories.map(category => {
                            const rows = nonNumericData.filter(d => String(d[xCol]) === category);
                            const obj = {
                              category: category,
                              x0: xScale(category),
                              x1: xScale(category) + xScale.bandwidth(),
                              ids: rows.map(d => d.ID)
                            };
                            groups.forEach(g => {
                              const groupData = rows.filter(d => d[groupByAttribute] === g);
                              obj[g] = groupData.length;
                              obj[`${g}_ids`] = groupData.map(d => d.ID);
                            });
                            return obj;
                          });
                        
                        const yMax = d3.max(stackedData, d => groups.reduce((sum, g) => sum + d[g], 0));
                        yScale = d3.scaleLinear().domain([0, yMax]).range([this.size, 0]);
                        const tooltip = d3.select("#tooltip");
                        
                        const stackGen = d3.stack().keys(groups);
                        const series = stackGen(stackedData);

                        series.forEach(s => {
                            s.forEach(d => {
                              d.group = s.key;
                            });
                          });
                        
                        cellGroup.selectAll("g.series")
                            .data(series)
                            .join("g")
                            .attr("class", "series")
                            .attr("data-key", d => d.key) 
                            .attr("fill", d => colorScale(d.key))
                            // .attr("stroke", function(d) {
                            //     const isSelected = d.some(segment => {
                            //       return groups.some(groupKey => {
                            //         const groupIDs = segment.data[`${groupKey}_ids`];
                            //         console.log("segment.data", segment.data);
                            //         console.log("groupIDs", groupIDs);
                            //         return groupIDs && groupIDs.some(ID => 
                            //           this.selectedPoints && this.selectedPoints.some(p => p.ID === ID)
                            //         );
                            //       });
                            //     });
                            //     return isSelected ? "black" : "none";
                            //   })
                            .selectAll("rect")
                            .data(d => d)
                            .join("rect")
                            .attr("x", d => xScale(d.data.category))
                            .attr("y", d => yScale(d[1]))
                            .attr("width", xScale.bandwidth())
                            .attr("height", d => yScale(d[0]) - yScale(d[1]))
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.data.ids.join(","))
                            .on("click", (event, d) => handleBarClick(event, d, xCol, groupByAttribute, group));
                    }
                    // No group by selected
                    else{
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
                            .range([this.size, 0]);
                        
                        const tooltip = d3.select("#tooltip");

                        cellGroup.selectAll("rect")
                            .data(histData)
                            .join("rect")
                            .attr("x", d => xScale(d.category))
                            .attr("width", xScale.bandwidth())
                            .attr("y", d => yScale(d.length))
                            .attr("height", d => Math.max(0, this.size - yScale(d.length)))
                            .attr("fill", (d) => {
                                const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                                return isSelected ? "red" : "steelblue";
                            })                       
                            .attr("stroke", (d) => {
                                const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                                return isSelected ? "black" : "none";
                            })                            
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.ids.join(","))
                            .on("click", (event, d) => handleBarClick(event, d, xCol, groupByAttribute));
                    }
                    
                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${this.size})`)
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

                    cellGroup.append("g")
                        .call(d3.axisLeft(yScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d);  

                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2) 
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) 
                        .style("text-anchor", "middle")
                        .text(xCol);
        
                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text("count");
                }
            } 
            /// Begin Scatterplot Code ///
            else {
                let data = [];

                if(groupByAttribute)
                {
                    data = givenData.select([xCol, yCol, groupByAttribute]).objects(); 
                }
                else{
                    data = givenData.select([xCol, yCol]).objects();
                }
                
                let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace} = splitData(data, xCol, yCol);

                /// All numeric plot ///
                if(xIsNumeric && yIsNumeric)
                {
                    const xScale = d3.scaleLinear()
                        .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
                        .range([0, numericSpace]);

                    const xTickValues = xScale.ticks(); 
                    const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

                    const categoricalXStart = xScale.range()[1] + 10;
                    const categoricalXScale = d3.scaleOrdinal()
                        .domain(uniqueXCategories)
                        .range(uniqueXCategories.length > 0 
                            ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                            : [0]); 

                    const yScale = d3.scaleLinear()
                        .domain([Math.min(0, d3.min(numericData, d => d[yCol])), d3.max(numericData, d => d[yCol]) + 1])
                        .range([numericSpace, 0]);

                    const categoricalYStart = yScale.range()[1] - 10;
                    const categoricalYScale = d3.scaleOrdinal()
                        .domain(uniqueYCategories)
                        .range(uniqueYCategories.length > 0 
                            ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                            : [0]); 
                        

                    const tooltip = d3.select("#tooltip"); 

                    const isSelected = (d) => this.selectedPoints.some(p => 
                        (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                        (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                        (p[yCol] === d[yCol] || isNaN(d[yCol]))
                    );
    
                    const brush = d3.brush()
                        .extent([[-60, -60], [this.size + 60, this.size + 60]]) 
                        .on("end", (event) => handleBrush(event, xScale, yScale, categoricalXScale, categoricalYScale, xCol, yCol));  

                    cellGroup.selectAll("circle")
                        .data(combinedData)
                        .join("circle")
                        .attr("cx", d => {
                            if (d.type === "numeric") return xScale(d[xCol]);
                            if (d.type === "nan-x" || d.type === "nan-xy") return categoricalXScale(d[xCol]);
                            return xScale(d[xCol]); 
                        })
                        .attr("cy", d => {
                            if (d.type === "numeric") return yScale(d[yCol]);
                            if (d.type === "nan-y" || d.type === "nan-xy") return categoricalYScale(d[yCol]);
                            return yScale(d[yCol]);
                        })
                        .attr("r", d => (d.type.includes("nan") ? 4 : 3))
                        // .attr("fill", d => isSelected(d) ? "red" : (d.type === "numeric" ? "steelblue" : "gray"))
                        .attr("fill", d => {
                            if (groupByAttribute) {
                                return colorScale(d[groupByAttribute]);
                            } else {
                                return d.type === "numeric" ? "steelblue" : "gray"; 
                            }
                        })
                        .attr("stroke", d => isSelected(d) ? "black" : "none") 
                        .attr("stroke-width", d => isSelected(d) ? 2 : 0)
                        .attr("opacity", d => isSelected(d) ? 0.8 : 0.6);

                    cellGroup.append("g")
                        .attr("class", "brush")  
                        .call(brush);

                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${numericSpace})`)
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

                    if (uniqueXCategories.length > 0) {
                    cellGroup.append("g")
                        .attr("transform", `translate(0, ${numericSpace})`)
                        .call(d3.axisBottom(categoricalXScale))
                        .selectAll("text")
                        .style("text-anchor", "end") 
                        .attr("transform", "rotate(-45)") 
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                        .append("title") 
                        .text(d => d); 
                    }

                    cellGroup.append("g")
                        .call(d3.axisLeft(yScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title") 
                        .text(d => d); 

                    if (uniqueYCategories.length > 0) {
                    cellGroup.append("g")
                        .attr("transform", `translate(0, 0)`)
                        .call(d3.axisLeft(categoricalYScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d); 
                    }
                    
                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - categorySpace  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                        .style("text-anchor", "middle")
                        .text(xCol);

                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2) - categorySpace; 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text(yCol);
                }

                /// Non numeric X plot ///
                else if(!xIsNumeric && yIsNumeric) // xCol is cat. yCol is num.
                {
                    uniqueXCategories = uniqueXCategories.slice(1);
                    uniqueYCategories = uniqueYCategories.slice(1);
                    uniqueXCategories = sortCategories(uniqueXCategories);
                    uniqueYCategories = sortCategories(uniqueYCategories);

                    const xScale = d3.scalePoint()
                        .domain(uniqueXCategories)
                        .range([0, this.size]);

                    const xTickValues = xScale.step(); 
                    const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

                    // const categoricalXStart = xScale.range()[1] + 10;
                    // const categoricalXScale = d3.scaleOrdinal()
                    //     .domain(uniqueXCategories)
                    //     .range([...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * (xTickSpacing + 5)))); 
                    
                    const yScale = d3.scaleLinear()
                        .domain([Math.min(0, d3.min(nonNumericXData, d => d[yCol])), d3.max(nonNumericXData, d => d[yCol]) + 1])
                        .range([this.size, 0]);

                    const categoricalYStart = yScale.range()[1] - 10;
                    const categoricalYScale = d3.scaleOrdinal()
                        .domain(uniqueYCategories)
                        .range(uniqueYCategories.length > 0 
                            ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                            : [0]); 
                        
                    const tooltip = d3.select("#tooltip"); 

                    const isSelected = (d) => this.selectedPoints.some(p => 
                        (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                        (p[xCol] === d[xCol]) &&
                        (p[yCol] === d[yCol] || isNaN(d[yCol]))
                    );
    
                    const brush = d3.brush()
                        .extent([[-60, -60], [this.size + 60, this.size + 60]]) 
                        .on("end", (event) => handleBrush(event, xScale, yScale, null, categoricalYScale, xCol, yCol));  

                    cellGroup.selectAll("circle")
                        .data(combinedData)
                        .join("circle")
                        .attr("cx", d => xScale(d[xCol]))
                        .attr("cy", d => {
                            if (d.type === "numeric") return yScale(d[yCol]);
                            if (d.type === "nan-y" || d.type === "nan-xy") return categoricalYScale(d[yCol]);
                            return yScale(d[yCol]);
                        })
                        .attr("r", d => (d.type === "nan-y" ? 4 : 3))
                        .attr("fill", d => {
                            if (groupByAttribute) {
                                return colorScale(d[groupByAttribute]);
                            } else {
                                return d.type === "nan-y" ? "gray" : "steelblue"; 
                            }
                        })
                        .attr("stroke", d => isSelected(d) ? "black" : "none") 
                        .attr("stroke-width", d => isSelected(d) ? 2 : 0)
                        .attr("opacity", d => isSelected(d) ? 0.8 : 0.6);

                    cellGroup.append("g")
                        .attr("class", "brush")  
                        .call(brush);

                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${this.size})`)
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

                    // if (uniqueXCategories.length > 0) {
                    // cellGroup.append("g")
                    //     .attr("transform", `translate(0, ${numericSpace})`)
                    //     .call(d3.axisBottom(categoricalXScale))
                    //     .selectAll("text")
                    //     .style("text-anchor", "end") 
                    //     .attr("transform", "rotate(-45)") 
                    //     .style("font-size", "10px"); 
                    // }

                    cellGroup.append("g")
                        .call(d3.axisLeft(yScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title") 
                        .text(d => d); 

                    if (uniqueYCategories.length > 0) {
                    cellGroup.append("g")
                        .attr("transform", `translate(0, 0)`)
                        .call(d3.axisLeft(categoricalYScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title") 
                        .text(d => d); 
                    }
                    
                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding)  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                        .style("text-anchor", "middle")
                        .text(xCol);

                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text(yCol);
                }

                /// Non numeric Y plot ///
                else if(xIsNumeric && !yIsNumeric) // xCol is num. yCol is cat.
                {
                    uniqueYCategories = uniqueYCategories.slice(1);
                    uniqueXCategories = uniqueXCategories.slice(1);
                    uniqueYCategories = sortCategories(uniqueYCategories);
                    uniqueXCategories = sortCategories(uniqueXCategories);

                    const xScale = d3.scaleLinear()
                        .domain([Math.min(0, d3.min(nonNumericYData, d => d[xCol])), d3.max(nonNumericYData, d => d[xCol]) + 1])
                        .range([0, this.size]);

                    const xTickValues = xScale.ticks(); 
                    const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

                    const categoricalXStart = xScale.range()[1] + 10;
                    const categoricalXScale = d3.scaleOrdinal()
                        .domain(uniqueXCategories)
                        .range(uniqueXCategories.length > 0 
                            ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                            : [0]); 
                    
                    const yScale = d3.scalePoint()
                        .domain(uniqueYCategories)
                        .range([this.size, 0]);

                    // const categoricalYStart = yScale.range()[1] - 10;
                    // const categoricalYScale = d3.scaleOrdinal()
                    //     .domain(uniqueYCategories)
                    //     .range([...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * (xTickSpacing + 5))));
                        

                    const tooltip = d3.select("#tooltip"); 

                    const isSelected = (d) => this.selectedPoints.some(p => 
                        (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                        (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                        (p[yCol] === d[yCol])
                    );
    
                    const brush = d3.brush()
                        .extent([[-60, -60], [this.size + 60, this.size + 60]]) 
                        .on("end", (event) => handleBrush(event, xScale, yScale, categoricalXScale, null, xCol, yCol));  

                    cellGroup.selectAll("circle")
                        .data(combinedData)
                        .join("circle")
                        .attr("cx", d => {
                            if (d.type === "numeric") return xScale(d[xCol]);
                            if (d.type === "nan-x" || d.type === "nan-xy") return categoricalXScale(d[xCol]);
                            return xScale(d[xCol]); 
                        })
                        .attr("cy", d => yScale(d[yCol]))
                        .attr("r", d => (d.type === "nan-x" ? 4 : 3))
                        .attr("fill", d => {
                            if (groupByAttribute) {
                                return colorScale(d[groupByAttribute]);
                            } else {
                                return d.type === "nan-x" ? "gray" : "steelblue"; 
                            }
                        })
                        .attr("stroke", d => isSelected(d) ? "black" : "none") 
                        .attr("stroke-width", d => isSelected(d) ? 2 : 0)
                        .attr("opacity", d => isSelected(d) ? 0.8 : 0.6);

                    cellGroup.append("g")
                        .attr("class", "brush")  
                        .call(brush);

                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${this.size})`)
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

                    if (uniqueXCategories.length > 0) {
                    cellGroup.append("g")
                        .attr("transform", `translate(0, ${numericSpace})`)
                        .call(d3.axisBottom(categoricalXScale))
                        .selectAll("text")
                        .style("text-anchor", "end") 
                        .attr("transform", "rotate(-45)") 
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d); 
                    }

                    cellGroup.append("g")
                        .call(d3.axisLeft(yScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d); 

                    // if (uniqueYCategories.length > 0) {
                    // cellGroup.append("g")
                    //     .attr("transform", `translate(0, 0)`)
                    //     .call(d3.axisLeft(categoricalYScale))
                    //     .selectAll("text")
                    //     .style("text-anchor", "end") 
                    //     .style("font-size", "10px"); 
                    // }
                    
                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                        .style("text-anchor", "middle")
                        .text(xCol);

                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text(yCol);
                }

                /// All non numeric plot ///
                else{   
                    uniqueXCategories = uniqueXCategories.slice(1);
                    uniqueYCategories = uniqueYCategories.slice(1);
                    uniqueXCategories = sortCategories(uniqueXCategories);
                    uniqueYCategories = sortCategories(uniqueYCategories);

                    const xScale = d3.scalePoint()
                        .domain(uniqueXCategories)
                        .range([0, this.size]);
                    
                    const yScale = d3.scalePoint()
                        .domain(uniqueYCategories)
                        .range([this.size, 0]);

                    const tooltip = d3.select("#tooltip"); 

                    const isSelected = (d) => this.selectedPoints.some(p => 
                        (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                        (p[xCol] === d[xCol]) &&
                        (p[yCol] === d[yCol])
                    );
    
                    const brush = d3.brush()
                        .extent([[-60, -60], [this.size + 60, this.size + 60]]) 
                        .on("end", (event) => handleBrush(event, xScale, yScale, null, null, xCol, yCol));  

                    cellGroup.selectAll("circle")
                        .data(combinedData)
                        .join("circle")
                        .attr("cx", d => xScale(d[xCol]))
                        .attr("cy", d => yScale(d[yCol]))
                        .attr("r", 3)
                        // .attr("fill", d => isSelected(d) ? "red" : "steelblue")
                        .attr("fill", d => {
                            if (groupByAttribute) {
                                return colorScale(d[groupByAttribute]);
                            } else {
                                return "steelblue"; 
                            }
                        })
                        .attr("stroke", d => isSelected(d) ? "black" : "none") 
                        .attr("stroke-width", d => isSelected(d) ? 2 : 0)
                        .attr("opacity", d => isSelected(d) ? 0.8 : 0.6);
                    
                    cellGroup.append("g")
                        .attr("class", "brush")  
                        .call(brush);

                    cellGroup
                        .append("g")
                        .attr("transform", `translate(0, ${this.size})`)
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

                    // if (uniqueXCategories.length > 0) {
                    // cellGroup.append("g")
                    //     .attr("transform", `translate(0, ${numericSpace})`)
                    //     .call(d3.axisBottom(categoricalXScale))
                    //     .selectAll("text")
                    //     .style("text-anchor", "end") 
                    //     .attr("transform", "rotate(-45)") 
                    //     .style("font-size", "10px"); 
                    // }

                    cellGroup.append("g")
                        .call(d3.axisLeft(yScale))
                        .selectAll("text")
                        .style("font-size", "8px")
                        .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                        .append("title")  
                        .text(d => d); 
                                            
                    // if (uniqueYCategories.length > 0) {
                    // cellGroup.append("g")
                    //     .attr("transform", `translate(0, 0)`)
                    //     .call(d3.axisLeft(categoricalYScale))
                    //     .selectAll("text")
                    //     .style("text-anchor", "end") 
                    //     .style("font-size", "10px"); 
                    // }
                    
                    svg
                        .append("text")
                        .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                        .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                        .style("text-anchor", "middle")
                        .text(xCol);

                    const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
                    const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
                    
                    svg
                        .append("text")
                        .attr("x", xPosition) 
                        .attr("y", yPosition - 20) 
                        .style("text-anchor", "middle")
                        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                        .text(yCol);
                }
            }
            });
        });
    }

    drawHeatMap (cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick){
        const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

        const groupColorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

        const gradientID = `legend-gradient-${i}-${j}`;
        let defs = svg.select("defs");
        if (defs.empty()) {
            defs = svg.append("defs");
        }
        svg.select(`#${gradientID}`).remove();

        let xScale = null;
        let yScale = null;
        let colorScale = null;

        let data = [];

        if(groupByAttribute)
        {
            data = givenData.select(["ID", xCol, yCol, groupByAttribute]).objects(); 
        }
        else{
            data = givenData.select(["ID", xCol, yCol]).objects();
        }

        let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace} = splitData(data, xCol, yCol);

        const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10;
        const yPosition = this.topMargin + i * (this.size + this.yPadding) + this.size / 2;

        uniqueXCategories = uniqueXCategories.slice(1);
        uniqueYCategories = uniqueYCategories.slice(1);
        uniqueXCategories = sortCategories(uniqueXCategories);
        uniqueYCategories = sortCategories(uniqueYCategories);

        const uniqueXStringBins = uniqueXCategories; 
        const uniqueYStringBins = uniqueYCategories; 
        console.log("uniqueXStringBins", uniqueXStringBins);

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

        let xCategories = [...xBinLabels.map(String), ...uniqueXStringBins].filter((v, i, self) => self.indexOf(v) === i); 
        let yCategories = [...yBinLabels.map(String), ...uniqueYStringBins].filter((v, i, self) => self.indexOf(v) === i); 

        const tooltip = d3.select("#tooltip");
        const self = this;
        let rect = null;

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

            if(groupByAttribute){
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

                xScale = d3.scaleBand().domain(xCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(yCategories).range([this.size, 0]).padding(0.05);

                cellGroup.selectAll("g.cell-group")
                    .data(heatmapData)
                    .join("g")
                    .attr("class", "cell-group")
                    .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                    .each(function (d) {
                        const g = d3.select(this);
                        let yOffset = 0;
                        const total = d3.sum(Object.values(d.groups));

                        Object.entries(d.groups).forEach(([group, count]) => {
                            rect = g.append("rect")
                                .attr("x", 0)
                                .attr("y", yOffset) 
                                .attr("fill", groupColorScale(group))
                                .attr("opacity", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                    else {return 1;}
                                })
                                .attr("stroke", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? "black" : "white";
                                })
                                .attr("stroke-width", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? 2 : 0;
                                })
                                .attr("data-group", group);
                            if(animate){
                                rect.attr("width", 0)
                                    .attr("height", 0) 
                                    .attr("opacity", 0)
                                    .transition()
                                    .duration(800)
                                    .ease(d3.easeCubicOut)
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            } else{
                                rect.attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            }
                            rect.on("mouseover", function (event) {
                                    d3.select(this).attr("stroke", "black").attr("stroke-width", 1);
                
                                    let tooltipContent = `<strong>${xCol}:</strong> ${d.x} <br>
                                                        <strong>${yCol}:</strong> ${d.y} <br>
                                                        <strong>Total Count:</strong> ${total} <br><hr>`;
                                    
                                    Object.entries(d.groups).forEach(([group, count]) => {
                                        tooltipContent += `<span style="color:${groupColorScale(group)}">&#9632;</span> 
                                                        <strong>${group}:</strong> ${count} <br>`;
                                    });
                
                                    tooltip.html(tooltipContent)
                                        .style("display", "block")
                                        .style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mousemove", function (event) {
                                    tooltip.style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mouseout", function () {
                                    d3.select(this).attr("stroke", "white").attr("stroke-width", 0.5);
                                    tooltip.style("display", "none");
                                })
                                .on("click", function (event, d) {
                                    if (!selectionEnabled) return; 
                                    const group = this.getAttribute("data-group");                                    
                                    handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                                });

                            yOffset += (yScale.bandwidth() * count) / total; 
                        });
                    });   
            }
            else{
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
    
                xScale = d3.scaleBand().domain(xCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(yCategories).range([this.size, 0]).padding(0.05);
                colorScale = d3.scaleSequential(d3.interpolateBlues)
                    .domain([0, d3.max(heatmapData, d => d.value)]);
        
                rect = cellGroup.selectAll("rect")
                    .data(heatmapData)
                    .join("rect")
                    .attr("x", d => xScale(d.x))
                    .attr("y", d => yScale(d.y))
                    .attr("opacity", 0.8)
                    .attr("fill", d => {
                        const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));

                        if (isSelected) {
                            return "gold"; 
                        }
                        if (d.y === "NaN") {
                            return "gray";
                        }
                        if (uniqueYStringBins.includes(d.y) || uniqueXStringBins.includes(d.x)) {
                            return "gray";
                        }
    
                        return colorScale(d.value); 
                    })
                    // .attr("stroke", "gray")
                    // .attr("stroke-width", 0.5)
                    .attr("stroke", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? "red" : "gray";
                    })
                    .attr("stroke-width", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? 1 : 0.5
                    });
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

            if(groupByAttribute){
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

                xScale = d3.scaleBand().domain(uniqueXCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(yCategories).range([this.size, 0]).padding(0.05);

                cellGroup.selectAll("g.cell-group")
                    .data(heatmapData)
                    .join("g")
                    .attr("class", "cell-group")
                    .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                    .each(function (d) {
                        const g = d3.select(this);
                        let yOffset = 0;
                        const total = d3.sum(Object.values(d.groups));

                        Object.entries(d.groups).forEach(([group, count]) => {
                            rect = g.append("rect")
                                .attr("x", 0)
                                .attr("y", yOffset)                                  
                                .attr("fill", groupColorScale(group))
                                .attr("opacity", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                    else {return 1;}
                                })
                                .attr("stroke", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? "black" : "white";
                                })
                                .attr("stroke-width", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? 2 : 0;
                                })
                                .attr("data-group", group);
                            if(animate){
                                rect.attr("width", 0)
                                    .attr("height", 0)
                                    .attr("opacity", 0)
                                    .transition()
                                    .duration(800)
                                    .ease(d3.easeCubicOut)
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            } else{
                                rect.attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            }
                            rect.on("mouseover", function (event) {
                                    d3.select(this).attr("stroke", "black").attr("stroke-width", 1);
                
                                    let tooltipContent = `<strong>${xCol}:</strong> ${d.x} <br>
                                                        <strong>${yCol}:</strong> ${d.y} <br>
                                                        <strong>Total Count:</strong> ${total} <br><hr>`;
                                    
                                    Object.entries(d.groups).forEach(([group, count]) => {
                                        tooltipContent += `<span style="color:${groupColorScale(group)}">&#9632;</span> 
                                                        <strong>${group}:</strong> ${count} <br>`;
                                    });
                
                                    tooltip.html(tooltipContent)
                                        .style("display", "block")
                                        .style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mousemove", function (event) {
                                    tooltip.style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mouseout", function () {
                                    d3.select(this).attr("stroke", "white").attr("stroke-width", 0.5);
                                    tooltip.style("display", "none");
                                })
                                .on("click", function (event, d) {
                                    if (!selectionEnabled) return; 
                                    const group = this.getAttribute("data-group");                                    
                                    handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                                });

                            yOffset += (yScale.bandwidth() * count) / total; 
                        });
                    });                
            }
            else{
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

                xScale = d3.scaleBand().domain(uniqueXCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(yCategories).range([this.size, 0]).padding(0.05);
                colorScale = d3.scaleSequential(d3.interpolateBlues)
                    .domain([0, d3.max(heatmapData, d => d.value)]);

                rect = cellGroup.selectAll("rect")
                    .data(heatmapData)
                    .join("rect")
                    .attr("x", d => xScale(d.x))
                    .attr("y", d => yScale(d.y))
                    .attr('opactiy', 0.8)
                    .attr("fill", d => {
                        const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));

                        if (isSelected) {
                            return "gold"; 
                        }
                        if (d.y === "NaN") {
                            return "gray";
                        }
                        if (uniqueYStringBins.includes(d.y)) {
                            return "gray";
                        }
    
                        return colorScale(d.value); 
                    })
                    // .attr("stroke", "gray")
                    // .attr("stroke-width", 0.5)
                    .attr("stroke", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? "red" : "gray";
                    })
                    .attr("stroke-width", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? 1 : 0.5
                    });
            }

            cellGroup.append("g")
                .attr("transform", `translate(0, ${this.size})`)
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
    
            cellGroup.append("g")
            .call(d3.axisLeft(yScale).tickFormat(d => {
                if (typeof d === "string") {
                    if (d.includes("-")) {
                        // Handle numeric bins formatted as strings (e.g., "10-20")
                        const [min, max] = d.split("-").map(Number);
                        return `${d3.format(".3s")(min)}-${d3.format(".3s")(max)}`;
                    } 
                    // If it's a categorical string, return it as is
                    return d;
                } 
                
                // If d is a pure number, format it
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

            if(groupByAttribute){
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

                xScale = d3.scaleBand().domain(xCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(uniqueYCategories).range([this.size, 0]).padding(0.05);

                cellGroup.selectAll("g.cell-group")
                    .data(heatmapData)
                    .join("g")
                    .attr("class", "cell-group")
                    .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                    .each(function (d) {
                        const g = d3.select(this);
                        let yOffset = 0;
                        const total = d3.sum(Object.values(d.groups));

                        Object.entries(d.groups).forEach(([group, count]) => {
                            rect = g.append("rect")
                                .attr("x", 0)
                                .attr("y", yOffset) 
                                .attr("fill", groupColorScale(group))
                                .attr("opacity", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                    else {return 1;}
                                })
                                .attr("stroke", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? "black" : "white";
                                })
                                .attr("stroke-width", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? 2 : 0;
                                })
                                .attr("data-group", group);
                            if(animate){
                                rect.attr("width", 0)
                                    .attr("height", 0)  
                                    .attr("opacity", 0)
                                    .transition()
                                    .duration(800)
                                    .ease(d3.easeCubicOut)
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            } else{
                                rect.attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            }
                            rect.on("mouseover", function (event) {
                                    d3.select(this).attr("stroke", "black").attr("stroke-width", 1);
                
                                    let tooltipContent = `<strong>${xCol}:</strong> ${d.x} <br>
                                                        <strong>${yCol}:</strong> ${d.y} <br>
                                                        <strong>Total Count:</strong> ${total} <br><hr>`;
                                    
                                    Object.entries(d.groups).forEach(([group, count]) => {
                                        tooltipContent += `<span style="color:${groupColorScale(group)}">&#9632;</span> 
                                                        <strong>${group}:</strong> ${count} <br>`;
                                    });
                
                                    tooltip.html(tooltipContent)
                                        .style("display", "block")
                                        .style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mousemove", function (event) {
                                    tooltip.style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mouseout", function () {
                                    d3.select(this).attr("stroke", "white").attr("stroke-width", 0.5);
                                    tooltip.style("display", "none");
                                })
                                .on("click", function (event, d) {
                                    if (!selectionEnabled) return; 
                                    const group = this.getAttribute("data-group");                                    
                                    handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                                });

                            yOffset += (yScale.bandwidth() * count) / total; 
                        });
                    });         

            }
            else{
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

                xScale = d3.scaleBand().domain(xCategories).range([0, this.size]).padding(0.05);
                console.log("xCategories", xCategories);
                yScale = d3.scaleBand().domain(uniqueYCategories).range([this.size, 0]).padding(0.05);
                colorScale = d3.scaleSequential(d3.interpolateBlues)
                    .domain([0, d3.max(heatmapData, d => d.value)]);

                rect = cellGroup.selectAll("rect")
                    .data(heatmapData)
                    .join("rect")
                    .attr("x", d => xScale(d.x))
                    .attr("y", d => yScale(d.y))
                    .attr("opacity", 0.8)
                    .attr("fill", d => {
                        const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));

                        if (isSelected) {
                            return "gold"; 
                        }
                        if (d.y === "NaN") {
                            return "gray";
                        }
                        if (uniqueXStringBins.includes(d.x)) {
                            return "gray";
                        }
                        return colorScale(d.value); 
                    })
                    // .attr("stroke", "gray")
                    // .attr("stroke-width", 0.5)    
                    .attr("stroke", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? "red" : "gray";
                    })
                    .attr("stroke-width", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? 1 : 0.5
                    });
            }
            cellGroup.append("g")
                .attr("transform", `translate(0, ${this.size})`)
                .call(d3.axisBottom(xScale).tickFormat(d => {
                    if (typeof d === "string") {
                        if (d.includes("-")) {
                            const [min, max] = d.split("-").map(Number);
                            return `${d3.format(".3s")(min)}-${d3.format(".3s")(max)}`;
                        } 
                        return d;
                    } 
                    return d3.format(".3s")(d);  
                }))                
                .selectAll("text")
                .style("text-anchor", "end")
                .style("font-size", "8px")
                .attr("dx", "-0.5em")
                .attr("dy", "0.5em")
                .attr("transform", "rotate(-45)");
    
            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);
        }

        /// All non numeric plot ///
        else{   
            if(groupByAttribute){
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

                xScale = d3.scaleBand().domain(uniqueXCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(uniqueYCategories).range([this.size, 0]).padding(0.05);

                cellGroup.selectAll("g.cell-group")
                    .data(heatmapData)
                    .join("g")
                    .attr("class", "cell-group")
                    .attr("transform", d => `translate(${xScale(d.x)}, ${yScale(d.y)})`)
                    .each(function (d) {
                        const g = d3.select(this);
                        let yOffset = 0;
                        const total = d3.sum(Object.values(d.groups));

                        Object.entries(d.groups).forEach(([group, count]) => {
                            rect = g.append("rect")
                                .attr("x", 0)
                                .attr("y", yOffset) 
                                // .attr("width", xScale.bandwidth())
                                // .attr("height", (yScale.bandwidth() * count) / total)  
                                .attr("fill", groupColorScale(group))
                                .attr("opacity", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                    else {return 1;}
                                })
                                .attr("stroke", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? "black" : "white";
                                })
                                .attr("stroke-width", (d) => {
                                    const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                    return isSelected ? 2 : 0;
                                })
                                .attr("data-group", group);
                            if(animate){
                                rect.attr("width", 0)
                                    .attr("height", 0)  
                                    .attr("opacity", 0)
                                    .transition()
                                    .duration(800)
                                    .ease(d3.easeCubicOut)
                                    .attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            } else{
                                rect.attr("width", xScale.bandwidth())
                                    .attr("height", (yScale.bandwidth() * count) / total)
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                        else {return 1;}
                                    });
                            }
                            rect.on("mouseover", function (event) {
                                    d3.select(this).attr("stroke", "black").attr("stroke-width", 1);
                
                                    let tooltipContent = `<strong>${xCol}:</strong> ${d.x} <br>
                                                        <strong>${yCol}:</strong> ${d.y} <br>
                                                        <strong>Total Count:</strong> ${total} <br><hr>`;
                                    
                                    Object.entries(d.groups).forEach(([group, count]) => {
                                        tooltipContent += `<span style="color:${groupColorScale(group)}">&#9632;</span> 
                                                        <strong>${group}:</strong> ${count} <br>`;
                                    });
                
                                    tooltip.html(tooltipContent)
                                        .style("display", "block")
                                        .style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mousemove", function (event) {
                                    tooltip.style("left", `${event.pageX + 10}px`)
                                        .style("top", `${event.pageY + 10}px`);
                                })
                                .on("mouseout", function () {
                                    d3.select(this).attr("stroke", "white").attr("stroke-width", 0.5);
                                    tooltip.style("display", "none");
                                })
                                .on("click", function (event, d) {
                                    if (!selectionEnabled) return; 
                                    const group = this.getAttribute("data-group");                                    
                                    handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                                });

                            yOffset += (yScale.bandwidth() * count) / total; 
                        });
                    });

            }
            else{
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
    
                xScale = d3.scaleBand().domain(uniqueXCategories).range([0, this.size]).padding(0.05);
                yScale = d3.scaleBand().domain(uniqueYCategories).range([this.size, 0]).padding(0.05);
                
                colorScale = d3.scaleSequential(d3.interpolateBlues)
                    .domain([0, d3.max(heatmapData, d => d.value)]);
        
                rect = cellGroup.selectAll("rect")
                    .data(heatmapData)
                    .join("rect")
                    .attr("x", d => xScale(d.x))
                    .attr("y", d => yScale(d.y))
                    .attr("opacity", 0.8)
                    .attr("fill", (d) => {
                        const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                        return isSelected ? "gold" : colorScale(d.value);
                    })
                    // .attr("stroke", "gray")
                    // .attr("stroke-width", 0.5)    
                    .attr("stroke", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? "red" : "gray";
                    })
                    .attr("stroke-width", (d) => {
                        const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                        return isPredicated ? 1 : 0.5
                    });             
            }
            
            cellGroup.append("g")
                .attr("transform", `translate(0, ${this.size})`)
                .call(d3.axisBottom(xScale).tickFormat(d => d))
                .selectAll("text")
                .style("text-anchor", "end")
                .style("font-size", "8px")
                .attr("dx", "-0.5em")
                .attr("dy", "0.5em")
                .attr("transform", "rotate(-45)")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);
    
            cellGroup.append("g")
                .call(d3.axisLeft(yScale).tickFormat(d => d))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);
        }

        // Animation, tooltip, user clicks, and legend behavior changes when there is no group by
        if(!groupByAttribute){
            if(animate){
                rect.attr("width", 0)
                    .attr("height", 0)
                    .attr("opacity", 0)
                    .transition()
                    .duration(800)
                    .ease(d3.easeCubicOut)
                    .attr("width", xScale.bandwidth())
                    .attr("height", yScale.bandwidth())
                    .attr("opacity", 0.8);
            } else{
                rect.attr("width", xScale.bandwidth())
                    .attr("height", yScale.bandwidth())
                    .attr("opacity", 0.8);
            }
            rect.on("mouseover", function (event, d) {
                    d3.select(this).attr("stroke", "black").attr("stroke-width", 1);
                    tooltip.style("display", "block")
                        .html(`<strong>${xCol}:</strong> ${d.x}<br><strong>${yCol}:</strong> ${d.y}<br><strong>Count:</strong> ${d.value}`)
                        .style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mousemove", function (event) {
                    tooltip.style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mouseout", function () {
                    d3.select(this).attr("stroke", "gray").attr("stroke-width", 0.5);
                    tooltip.style("display", "none");
                })
                .on("click", function (event, d) {
                    if (!selectionEnabled) return; 
                    handleHeatmapClick(event, d, xCol, yCol, groupByAttribute);
                });

            const legendHeight = this.size;
            const legendWidth = 10;
            const legendX = this.size + 5; 
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
    
            cellGroup.append("rect")
                .attr("x", legendX)
                .attr("y", legendY)
                .attr("width", legendWidth)
                .attr("height", legendHeight)
                .style("fill", `url(#${gradientID})`)
                .attr("stroke", "black");

            cellGroup.append("g")
                .attr("transform", `translate(${legendX + legendWidth}, ${legendY})`)
                .call(d3.axisRight(legendScale)
                    .ticks(5))
                .selectAll("text")
                .style("font-size", "8px");
        }

        svg.append("text")
            .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
            .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25)
            .style("text-anchor", "middle")
            .text(xCol);

        svg.append("text")
            .attr("x", xPosition)
            .attr("y", yPosition - 20)
            .style("text-anchor", "middle")
            .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`)
            .text(yCol);
    }

    drawScatterplot(cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick){
        const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

        const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

        let data = [];

        if(groupByAttribute)
        {
            data = givenData.select([xCol, yCol, groupByAttribute]).objects(); 
        }
        else{
            data = givenData.select([xCol, yCol]).objects();
        }

        let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace} = splitData(data, xCol, yCol);

        /// All numeric plot ///
        if(xIsNumeric && yIsNumeric)
        {
            const xScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
                .range([0, numericSpace]);

            const xTickValues = xScale.ticks(); 
            const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

            const categoricalXStart = xScale.range()[1] + 10;
            const categoricalXScale = d3.scaleOrdinal()
                .domain(uniqueXCategories)
                .range(uniqueXCategories.length > 0 
                    ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 

            const yScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(numericData, d => d[yCol])), d3.max(numericData, d => d[yCol]) + 1])
                .range([numericSpace, 0]);

            const categoricalYStart = yScale.range()[1] - 10;
            const categoricalYScale = d3.scaleOrdinal()
                .domain(uniqueYCategories)
                .range(uniqueYCategories.length > 0 
                    ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 
                
            const tooltip = d3.select("#tooltip"); 

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                (p[yCol] === d[yCol] || isNaN(d[yCol]))
            );

            const circles = cellGroup.selectAll("circle")
                .data(combinedData)
                .join("circle")
                .attr("cx", d => {
                    if (d.type === "numeric") return xScale(d[xCol]);
                    if (d.type === "nan-x" || d.type === "nan-xy") return categoricalXScale(d[xCol]);
                    return xScale(d[xCol]); 
                })
                .attr("cy", d => {
                    if (d.type === "numeric") return yScale(d[yCol]);
                    if (d.type === "nan-y" || d.type === "nan-xy") return categoricalYScale(d[yCol]);
                    return yScale(d[yCol]);
                })
                // .attr("fill", d => (d.type === "numeric" ? "steelblue" : "gray"))
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return d.type === "numeric" ? "steelblue" : "gray"; 
                    }
                })
                // .attr("stroke", d => (d.type.includes("nan") ? "red" : "none")) 
                // .attr("stroke-width", d => (d.type.includes("nan") ? 1 : 0))
                .attr("stroke", d => isPredicated(d) ? "red" : "none")
                .attr("stroke-width", d => isPredicated(d) ? 1 : 0);
                if(animate){
                    circles.attr("r", 0) 
                        .attr("opacity", 0)
                        .transition()
                        .duration(800)
                        .ease(d3.easeCubicOut)
                        .attr("r", d => (d.type.includes("nan") ? 4 : 3)) 
                        .attr("opacity", 0.6);
                } else{
                    circles.attr("r", d => (d.type.includes("nan") ? 4 : 3))
                        .attr("opacity", 0.6);
                }  
                circles.on("mouseover", function(event, d) {
                        d3.select(this).attr("fill", "gold");
                        let tooltipContent = `<strong>${xCol}:</strong> ${d[xCol]}<br><strong>${yCol}:</strong> ${d[yCol]}`;
                        if (groupByAttribute) {
                            tooltipContent += `<br><strong>${groupByAttribute}:</strong> ${d[groupByAttribute]}`;
                        }
                        tooltip.style("display", "block")
                            .html(tooltipContent)
                            .style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mousemove", function(event) {
                        tooltip.style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mouseout", function() {
                        d3.select(this).attr("fill", d => {
                            if (groupByAttribute) {
                                return colorScale(d[groupByAttribute]);
                            } else {
                                return d.type === "numeric" ? "steelblue" : "gray"; 
                            }
                        });
                        tooltip.style("display", "none");
                    });

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${numericSpace})`)
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

            if (uniqueXCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, ${numericSpace})`)
                .call(d3.axisBottom(categoricalXScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d); 
            }

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title") 
                .text(d => d); 

            if (uniqueYCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, 0)`)
                .call(d3.axisLeft(categoricalYScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title") 
                .text(d => d); 
            }
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - categorySpace  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2) - categorySpace; 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        /// Non numeric X plot ///
        else if(!xIsNumeric && yIsNumeric) // xCol is cat. yCol is num.
        {
            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = sortCategories(uniqueXCategories);
            uniqueYCategories = sortCategories(uniqueYCategories);

            const xScale = d3.scalePoint()
                .domain(uniqueXCategories)
                .range([0, this.size]);

            const xTickValues = xScale.step(); 
            const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

            // const categoricalXStart = xScale.range()[1] + 10;
            // const categoricalXScale = d3.scaleOrdinal()
            //     .domain(uniqueXCategories)
            //     .range([...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * (xTickSpacing + 5)))); 
            
            const yScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(nonNumericXData, d => d[yCol])), d3.max(nonNumericXData, d => d[yCol]) + 1])
                .range([this.size, 0]);

            const categoricalYStart = yScale.range()[1] - 10;
            const categoricalYScale = d3.scaleOrdinal()
                .domain(uniqueYCategories)
                .range(uniqueYCategories.length > 0 
                    ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 
                
            const tooltip = d3.select("#tooltip"); 

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol]) &&
                (p[yCol] === d[yCol] || isNaN(d[yCol]))
            );

            const circles = cellGroup.selectAll("circle")
                .data(combinedData)
                .join("circle")
                .attr("cx", d => xScale(d[xCol]))
                .attr("cy", d => {
                    if (d.type === "numeric") return yScale(d[yCol]);
                    if (d.type === "nan-y" || d.type === "nan-xy") return categoricalYScale(d[yCol]);
                    return yScale(d[yCol]);
                })
                // .attr("fill", d => (d.type === "nan-y" ? "gray" : "steelblue"))
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return d.type === "nan-y" ? "gray" : "steelblue"; 
                    }
                })
                // .attr("stroke", d => (d.type === "nan-y" ? "red" : "none")) 
                // .attr("stroke-width", d => (d.type === "nan-y" ? 1 : 0))
                .attr("stroke", d => isPredicated(d) ? "red" : "none")
                .attr("stroke-width", d => isPredicated(d) ? 1 : 0);
            if(animate){
                circles.attr("r", 0) 
                    .attr("opacity", 0)
                    .transition()
                    .duration(800)
                    .ease(d3.easeCubicOut)
                    .attr("r", d => (d.type === "nan-y" ? 4 : 3)) 
                    .attr("opacity", 0.6);
            } else{
                circles.attr("r", d => (d.type === "nan-y" ? 4 : 3))
                    .attr("opacity", 0.6);
            }  
            circles.on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "gold");
                    let tooltipContent = `<strong>${xCol}:</strong> ${d[xCol]}<br><strong>${yCol}:</strong> ${d[yCol]}`;
                    if (groupByAttribute) {
                        tooltipContent += `<br><strong>${groupByAttribute}:</strong> ${d[groupByAttribute]}`;
                    }
                    tooltip.style("display", "block")
                        .html(tooltipContent)
                        .style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mousemove", function(event) {
                    tooltip.style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mouseout", function() {
                    d3.select(this).attr("fill", d => {
                        if (groupByAttribute) {
                            return colorScale(d[groupByAttribute]);
                        } else {
                            return d.type === "nan-y" ? "gray" : "steelblue"; 
                        }
                    });
                    tooltip.style("display", "none");
                });

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${this.size})`)
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

            // if (uniqueXCategories.length > 0) {
            // cellGroup.append("g")
            //     .attr("transform", `translate(0, ${numericSpace})`)
            //     .call(d3.axisBottom(categoricalXScale))
            //     .selectAll("text")
            //     .style("text-anchor", "end") 
            //     .attr("transform", "rotate(-45)") 
            //     .style("font-size", "10px"); 
            // }

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title")  
                .text(d => d); 

            if (uniqueYCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, 0)`)
                .call(d3.axisLeft(categoricalYScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title")
                .text(d => d); 
            }
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding)  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        /// Non numeric Y plot ///
        else if(xIsNumeric && !yIsNumeric) // xCol is num. yCol is cat.
        {
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = sortCategories(uniqueYCategories);
            uniqueXCategories = sortCategories(uniqueXCategories);

            const xScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(nonNumericYData, d => d[xCol])), d3.max(nonNumericYData, d => d[xCol]) + 1])
                .range([0, this.size]);

            const xTickValues = xScale.ticks(); 
            const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

            const categoricalXStart = xScale.range()[1] + 10;
            const categoricalXScale = d3.scaleOrdinal()
                .domain(uniqueXCategories)
                .range(uniqueXCategories.length > 0 
                    ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 
            
            const yScale = d3.scalePoint()
                .domain(uniqueYCategories)
                .range([this.size, 0]);

            // const categoricalYStart = yScale.range()[1] - 10;
            // const categoricalYScale = d3.scaleOrdinal()
            //     .domain(uniqueYCategories)
            //     .range([...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * (xTickSpacing + 5))));
                

            const tooltip = d3.select("#tooltip"); 

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                (p[yCol] === d[yCol])
            );

            const circles = cellGroup.selectAll("circle")
                .data(combinedData)
                .join("circle")
                .attr("cx", d => {
                    if (d.type === "numeric") return xScale(d[xCol]);
                    if (d.type === "nan-x" || d.type === "nan-xy") return categoricalXScale(d[xCol]);
                    return xScale(d[xCol]); 
                })
                .attr("cy", d => yScale(d[yCol]))
                // .attr("fill", d => (d.type === "nan-x" ? "gray" : "steelblue"))
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return d.type === "nan-x" ? "gray" : "steelblue"; 
                    }
                })
                // .attr("stroke", d => (d.type === "nan-x" ? "red" : "none")) 
                // .attr("stroke-width", d => (d.type === "nan-x" ? 1 : 0))
                .attr("stroke", d => isPredicated(d) ? "red" : "none")
                .attr("stroke-width", d => isPredicated(d) ? 1 : 0);
            if(animate){
                circles.attr("r", 0) 
                    .attr("opacity", 0)
                    .transition()
                    .duration(800)
                    .ease(d3.easeCubicOut)
                    .attr("r", d => (d.type === "nan-x" ? 4 : 3)) 
                    .attr("opacity", 0.6);
            } else{
                circles.attr("r", d => (d.type === "nan-x" ? 4 : 3))
                    .attr("opacity", 0.6);
            }  
            circles.on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "gold");
                    let tooltipContent = `<strong>${xCol}:</strong> ${d[xCol]}<br><strong>${yCol}:</strong> ${d[yCol]}`;
                    if (groupByAttribute) {
                        tooltipContent += `<br><strong>${groupByAttribute}:</strong> ${d[groupByAttribute]}`;
                    }
                    tooltip.style("display", "block")
                        .html(tooltipContent)
                        .style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mousemove", function(event) {
                    tooltip.style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mouseout", function() {
                    d3.select(this).attr("fill", d => {
                        if (groupByAttribute) {
                            return colorScale(d[groupByAttribute]);
                        } else {
                            return d.type === "nan-x" ? "gray" : "steelblue"; 
                        }
                    });
                    tooltip.style("display", "none");
                });

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${this.size})`)
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

            if (uniqueXCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, ${numericSpace})`)
                .call(d3.axisBottom(categoricalXScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title") 
                .text(d => d); 
            }

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title") 
                .text(d => d); 

            // if (uniqueYCategories.length > 0) {
            // cellGroup.append("g")
            //     .attr("transform", `translate(0, 0)`)
            //     .call(d3.axisLeft(categoricalYScale))
            //     .selectAll("text")
            //     .style("text-anchor", "end") 
            //     .style("font-size", "10px"); 
            // }
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        /// All non numeric plot ///
        else{   
            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = sortCategories(uniqueXCategories);
            uniqueYCategories = sortCategories(uniqueYCategories);

            const xScale = d3.scalePoint()
                .domain(uniqueXCategories)
                .range([0, this.size]);
            
            const yScale = d3.scalePoint()
                .domain(uniqueYCategories)
                .range([this.size, 0]);

            const tooltip = d3.select("#tooltip"); 

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol]) &&
                (p[yCol] === d[yCol])
            );

            const circles = cellGroup.selectAll("circle")
                .data(combinedData)
                .join("circle")
                .attr("cx", d => xScale(d[xCol]))
                .attr("cy", d => yScale(d[yCol]))
                // .attr("fill", "steelblue")
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return "steelblue"; 
                    }
                })
                .attr("stroke", d => isPredicated(d) ? "red" : "none")
                .attr("stroke-width", d => isPredicated(d) ? 1 : 0);
            if(animate){
                circles.attr("r", 0) 
                    .attr("opacity", 0)
                    .transition()
                    .duration(800)
                    .ease(d3.easeCubicOut)
                    .attr("r", 3) 
                    .attr("opacity", 0.6);
            } else{
                circles.attr("r", 3)
                    .attr("opacity", 0.6);
            }                
            circles.on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "gold");
                    let tooltipContent = `<strong>${xCol}:</strong> ${d[xCol]}<br><strong>${yCol}:</strong> ${d[yCol]}`;
                    if (groupByAttribute) {
                        tooltipContent += `<br><strong>${groupByAttribute}:</strong> ${d[groupByAttribute]}`;
                    }
                    tooltip.style("display", "block")
                        .html(tooltipContent)
                        .style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mousemove", function(event) {
                    tooltip.style("left", `${event.pageX + 10}px`)
                        .style("top", `${event.pageY + 10}px`);
                })
                .on("mouseout", function() {
                    d3.select(this).attr("fill", d => {
                        if (groupByAttribute) {
                            return colorScale(d[groupByAttribute]);
                        } else {
                            return "steelblue"; 
                        }
                    });
                    tooltip.style("display", "none");
                });

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${this.size})`)
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

            // if (uniqueXCategories.length > 0) {
            // cellGroup.append("g")
            //     .attr("transform", `translate(0, ${numericSpace})`)
            //     .call(d3.axisBottom(categoricalXScale))
            //     .selectAll("text")
            //     .style("text-anchor", "end") 
            //     .attr("transform", "rotate(-45)") 
            //     .style("font-size", "10px"); 
            // }

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)
                .append("title")
                .text(d => d); 

            // if (uniqueYCategories.length > 0) {
            // cellGroup.append("g")
            //     .attr("transform", `translate(0, 0)`)
            //     .call(d3.axisLeft(categoricalYScale))
            //     .selectAll("text")
            //     .style("text-anchor", "end") 
            //     .style("font-size", "10px"); 
            // }
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }
        
    }

    switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`);  // Hardcoded for stackoverflow tab, need to make dynamic later
        const [, i, j] = cellID.split("-").map(d => parseInt(d));

        console.log("cellID", cellID);

        cellGroup.selectAll("*").remove();  

        const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

        const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

        let data = [];

        if(groupByAttribute)
        {
            data = givenData.select([xCol, yCol, groupByAttribute]).objects(); 
        }
        else{
            data = givenData.select([xCol, yCol]).objects();
        }

        let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace} = splitData(data, xCol, yCol);

        /// All numeric plot ///
        if(xIsNumeric && yIsNumeric)
        {
            const xScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
                .range([0, numericSpace]);

            const xTickValues = xScale.ticks(); 
            const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

            const categoricalXStart = xScale.range()[1] + 10;
            const categoricalXScale = d3.scaleOrdinal()
                .domain(uniqueXCategories)
                .range(uniqueXCategories.length > 0 
                    ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 

            const yScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(numericData, d => d[yCol])), d3.max(numericData, d => d[yCol]) + 1])
                .range([numericSpace, 0]);

            const categoricalYStart = yScale.range()[1] - 10;
            const categoricalYScale = d3.scaleOrdinal()
                .domain(uniqueYCategories)
                .range(uniqueYCategories.length > 0 
                    ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 
                
            combinedData.sort((a, b) => {
                const aIsNumeric = a.type === "numeric" || a.type === "nan-y";
                const bIsNumeric = b.type === "numeric" || a.type === "nan-y";
            
                if (aIsNumeric && bIsNumeric) {
                    return Number(a[xCol]) - Number(b[xCol]); 
                }
            
                const aIsCategorical = !aIsNumeric;
                const bIsCategorical = !bIsNumeric;
            
                if (aIsCategorical && bIsCategorical) {
                    return categoricalXScale.domain().indexOf(a[xCol]) - categoricalXScale.domain().indexOf(b[xCol]);
                }
            
                return aIsNumeric ? -1 : 1; 
            });

            const line = d3.line()
            .x(d => {
                if (typeof d[xCol] === "number" && !isNaN(d[xCol])) {
                    return xScale(d[xCol]); 
                } else {
                    return categoricalXScale(String(d[xCol])) || xScale(0); 
                }
            })
            .y(d => {
                if (typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                    return yScale(d[yCol]); 
                } else {
                    return categoricalYScale(String(d[yCol])) || yScale(0);
                }
            })
            .curve(d3.curveMonotoneX);

            let groupedData;

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                (p[yCol] === d[yCol] || isNaN(d[yCol]))
            );

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    const path = cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2)
                      .attr("stroke-dasharray", function() { return this.getTotalLength(); }) 
                      .attr("stroke-dashoffset", function() { return this.getTotalLength(); }) 

                    if (animate) {
                        path.transition()
                            .duration(800) 
                            .ease(d3.easeLinear)
                            .attr("stroke-dashoffset", 0); 
                    } else{
                        path.attr("stroke-dashoffset", 0); 
                    }
                  });
            }
            else{
                const path = cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    // .attr("stroke", "steelblue")
                    // .attr("stroke-width", 2)
                    .attr("stroke", d => isPredicated(d) ? "red" : "steelblue")
                    .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                    .attr("d", line)
                    .attr("stroke-dasharray", function() { return this.getTotalLength(); })
                    .attr("stroke-dashoffset", function() { return this.getTotalLength(); });

                if (animate) {
                    path.transition()
                        .duration(800)
                        .ease(d3.easeLinear)
                        .attr("stroke-dashoffset", 0);
                } else{
                    path.attr("stroke-dashoffset", 0);
                }
            }

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${numericSpace})`)
                .call(d3.axisBottom(xScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)
                .append("title") 
                .text(d => d); 

            if (uniqueXCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, ${numericSpace})`)
                .call(d3.axisBottom(categoricalXScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d); 
            }

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);

            if (uniqueYCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, 0)`)
                .call(d3.axisLeft(categoricalYScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title")  
                .text(d => d); 
            }
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding) - categorySpace  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2) - categorySpace; 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        /// Non numeric X plot ///
        else if(!xIsNumeric && yIsNumeric) // xCol is cat. yCol is num.
        {
            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = sortCategories(uniqueXCategories);
            uniqueYCategories = sortCategories(uniqueYCategories);

            const xScale = d3.scalePoint()
                .domain(uniqueXCategories)
                .range([0, this.size]);

            const xTickValues = xScale.step(); 
            const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

            const yScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(nonNumericXData, d => d[yCol])), d3.max(nonNumericXData, d => d[yCol]) + 1])
                .range([this.size, 0]);

            const categoricalYStart = yScale.range()[1] - 10;
            const categoricalYScale = d3.scaleOrdinal()
                .domain(uniqueYCategories)
                .range(uniqueYCategories.length > 0 
                    ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 
                
            combinedData.sort((a, b) => {
                return uniqueXCategories.indexOf(a[xCol]) - uniqueXCategories.indexOf(b[xCol]);
            });

            const line = d3.line()
                .x(d => {
                        return xScale(d[xCol]); 
                })
                .y(d => {
                    if (typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                        return yScale(d[yCol]); 
                    } else {
                        return categoricalYScale(String(d[yCol])) || yScale(0);
                    }
                })
                .curve(d3.curveMonotoneX);
            
            let groupedData;

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol]) &&
                (p[yCol] === d[yCol] || isNaN(d[yCol]))
            );

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    const path = cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2)
                      .attr("stroke-dasharray", function() { return this.getTotalLength(); }) 
                      .attr("stroke-dashoffset", function() { return this.getTotalLength(); }) 

                    if (animate) {
                        path.transition()
                            .duration(800) 
                            .ease(d3.easeLinear)
                            .attr("stroke-dashoffset", 0); 
                    } else{
                        path.attr("stroke-dashoffset", 0); 
                    }
                  });
            }
            else{
                const path = cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    // .attr("stroke", "steelblue")
                    // .attr("stroke-width", 2)
                    .attr("stroke", d => isPredicated(d) ? "red" : "steelblue")
                    .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                    .attr("d", line)
                    .attr("stroke-dasharray", function() { return this.getTotalLength(); })
                    .attr("stroke-dashoffset", function() { return this.getTotalLength(); });

                if (animate) {
                    path.transition()
                        .duration(800)
                        .ease(d3.easeLinear)
                        .attr("stroke-dashoffset", 0);
                } else{
                    path.attr("stroke-dashoffset", 0);
                }
            }

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${this.size})`)
                .call(d3.axisBottom(xScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)
                .append("title") 
                .text(d => d); 

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);

            if (uniqueYCategories.length > 0) {
            cellGroup.append("g")
                .attr("transform", `translate(0, 0)`)
                .call(d3.axisLeft(categoricalYScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d) 
                .append("title")  
                .text(d => d); 
            }
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding)  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        /// Non numeric Y plot ///
        else if(xIsNumeric && !yIsNumeric) // xCol is num. yCol is cat.
        {
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = sortCategories(uniqueYCategories);
            uniqueXCategories = sortCategories(uniqueXCategories);

            const xScale = d3.scaleLinear()
                .domain([Math.min(0, d3.min(nonNumericYData, d => d[xCol])), d3.max(nonNumericYData, d => d[xCol]) + 1])
                .range([0, this.size]);

            const xTickValues = xScale.ticks(); 
            const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

            const categoricalXStart = xScale.range()[1] + 10;
            const categoricalXScale = d3.scaleOrdinal()
                .domain(uniqueXCategories)
                .range(uniqueXCategories.length > 0 
                    ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                    : [0]); 
            
            const yScale = d3.scalePoint()
                .domain(uniqueYCategories)
                .range([this.size, 0]);

            combinedData.sort((a, b) => {
                return Number(a[xCol]) - Number(b[xCol]); 
            });

            const line = d3.line()
                .x(d => {
                    if (typeof d[xCol] === "number" && !isNaN(d[xCol])) {
                        return xScale(d[xCol]); 
                    } else {
                        return categoricalXScale(String(d[xCol])) || xScale(0); 
                    }
                })
                .y(d => {
                        return yScale(d[yCol]); 
                })
                .curve(d3.curveMonotoneX);

            let groupedData;

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                (p[yCol] === d[yCol])
            );

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    const path = cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2)
                      .attr("stroke-dasharray", function() { return this.getTotalLength(); }) 
                      .attr("stroke-dashoffset", function() { return this.getTotalLength(); }) 

                    if (animate) {
                        path.transition()
                            .duration(800) 
                            .ease(d3.easeLinear)
                            .attr("stroke-dashoffset", 0); 
                    } else{
                        path.attr("stroke-dashoffset", 0); 
                    }
                  });
            }
            else{
                const path = cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    // .attr("stroke", "steelblue")
                    // .attr("stroke-width", 2)
                    .attr("stroke", d => isPredicated(d) ? "red" : "steelblue")
                    .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                    .attr("d", line)
                    .attr("stroke-dasharray", function() { return this.getTotalLength(); })
                    .attr("stroke-dashoffset", function() { return this.getTotalLength(); });

                if (animate) {
                    path.transition()
                        .duration(800)
                        .ease(d3.easeLinear)
                        .attr("stroke-dashoffset", 0);
                } else{
                    path.attr("stroke-dashoffset", 0);
                }
            }

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${this.size})`)
                .call(d3.axisBottom(xScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)
                .append("title") 
                .text(d => d); 

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);

            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding)  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        /// All non numeric plot ///
        else{   
            uniqueXCategories = uniqueXCategories.slice(1);
            uniqueYCategories = uniqueYCategories.slice(1);
            uniqueXCategories = sortCategories(uniqueXCategories);
            uniqueYCategories = sortCategories(uniqueYCategories);

            console.log("uniqueXCategories", uniqueXCategories);
            console.log("uniqueYCategories", uniqueYCategories);

            const xScale = d3.scalePoint()
                .domain(uniqueXCategories)
                .range([0, this.size]);
            
            const yScale = d3.scalePoint()
                .domain(uniqueYCategories)
                .range([this.size, 0]);

            combinedData.sort((a, b) => {
                return uniqueXCategories.indexOf(a[xCol]) - uniqueXCategories.indexOf(b[xCol]);
            });

            console.log("sorted data", combinedData);

            const line = d3.line()
                            .x(d => {
                                    return xScale(d[xCol]);
                            })
                            .y(d => {
                                    return yScale(d[yCol]); 
                            })
                            .curve(d3.curveMonotoneX);

            let groupedData;

            const isPredicated = (d) => this.predicatePoints.some(p => 
                (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                (p[xCol] === d[xCol]) &&
                (p[yCol] === d[yCol])
            );

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    const path = cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2)
                      .attr("stroke-dasharray", function() { return this.getTotalLength(); }) 
                      .attr("stroke-dashoffset", function() { return this.getTotalLength(); }) 

                    if (animate) {
                        path.transition()
                            .duration(800) 
                            .ease(d3.easeLinear)
                            .attr("stroke-dashoffset", 0); 
                    } else{
                        path.attr("stroke-dashoffset", 0); 
                    }
                  });
            }
            else{
                const path = cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    // .attr("stroke", "steelblue")
                    // .attr("stroke-width", 2)
                    .attr("stroke", d => {
                        let result = isPredicated(d);
                        console.log(`isPredicated(${d}):`, result);
                        return result ? "red" : "steelblue";
                    })
                    .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                    .attr("d", line)
                    .attr("stroke-dasharray", function() { return this.getTotalLength(); })
                    .attr("stroke-dashoffset", function() { return this.getTotalLength(); });

                if (animate) {
                    path.transition()
                        .duration(800)
                        .ease(d3.easeLinear)
                        .attr("stroke-dashoffset", 0);
                } else{
                    path.attr("stroke-dashoffset", 0);
                }
            }

            cellGroup
                .append("g")
                .attr("transform", `translate(0, ${this.size})`)
                .call(d3.axisBottom(xScale))
                .selectAll("text")
                .style("text-anchor", "end") 
                .attr("transform", "rotate(-45)") 
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)
                .append("title") 
                .text(d => d); 

            cellGroup.append("g")
                .call(d3.axisLeft(yScale))
                .selectAll("text")
                .style("font-size", "8px")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
                .append("title")  
                .text(d => d);
            
            svg
                .append("text")
                .attr("x", this.leftMargin + j * (this.size + this.xPadding) + this.size / 2)
                .attr("y", this.topMargin + (i + 1) * (this.size + this.yPadding)  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
                .style("text-anchor", "middle")
                .text(xCol);

            const xPosition = this.leftMargin + j * (this.size + this.xPadding) - this.labelPadding - 10; 
            const yPosition = (this.topMargin + i * (this.size + this.yPadding) + this.size / 2); 
            
            svg
                .append("text")
                .attr("x", xPosition) 
                .attr("y", yPosition - 20) 
                .style("text-anchor", "middle")
                .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                .text(yCol);
        }

        d3.select(this.parentNode).selectAll(".heatmap-button, .scatterplot-button").classed("active", false);

        const heatMapViewButton = cellGroup.append("image")
        .attr("class", "heatmap-button")
        .attr("x", -110)  
        .attr("y", -60)   
        .attr("width", 45) 
        .attr("height", 25)
        .attr("xlink:href", "icons/heatmap.png")
        .attr("cursor", "pointer")
        .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const scatterViewButton = cellGroup.append("image")
            .attr("class", "scatterplot-button")
            .attr("x", -110)  
            .attr("y", -35)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/scatterplot.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const lineViewButton = cellGroup.append("image")
            .attr("class", "linechart-button active")
            .attr("x", -110)  
            .attr("y", -10)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/linechart.png")
            .attr("cursor", "pointer")
            .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    }

    restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`); // Hardcoded for stackoverflow tab
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));
        this.drawScatterplot(cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);  

        d3.select(this.parentNode).selectAll(".linechart-button, .heatmap-button").classed("active", false);

        const heatMapViewButton = cellGroup.append("image")
            .attr("class", "heatmap-button")
            .attr("x", -110)  
            .attr("y", -60)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/heatmap.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const scatterViewButton = cellGroup.append("image")
            .attr("class", "scatterplot-button active")
            .attr("x", -110)  
            .attr("y", -35)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/scatterplot.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const lineViewButton = cellGroup.append("image")
            .attr("class", "linechart-button")
            .attr("x", -110)  
            .attr("y", -10)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/linechart.png")
            .attr("cursor", "pointer")
            .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    }

    restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`); // Hardcoded for stackoverflow tab
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));
        this.drawHeatMap(cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick);  

        d3.select(this.parentNode).selectAll(".linechart-button, .scatterplot-button").classed("active", false);


        const heatMapViewButton = cellGroup.append("image")
            .attr("class", "heatmap-button active")
            .attr("x", -110)  
            .attr("y", -60)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/heatmap.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const scatterViewButton = cellGroup.append("image")
            .attr("class", "scatterplot-button")
            .attr("x", -110)  
            .attr("y", -35)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/scatterplot.png")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

        const lineViewButton = cellGroup.append("image")
            .attr("class", "linechart-button")
            .attr("x", -110)  
            .attr("y", -10)   
            .attr("width", 45) 
            .attr("height", 25)
            .attr("xlink:href", "icons/linechart.png")
            .attr("cursor", "pointer")
            .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
    }

    drawPreviewPlot(givenData, containerId, isHistogram, groupByAttribute, xCol, yCol){
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
                  containerId === "preview-impute-average-x" ? `Preview of Imputing by Avg ${xCol}` :
                  `Preview of Imputing by Avg ${yCol}`);

        if(isHistogram)
        {
            if(containerId === "preview-impute-average-y")
            {
                return;
            }
            let data = [];

            if (groupByAttribute){
                data = givenData.select(["ID", xCol, groupByAttribute]).objects();
            }
            else{
                data = givenData.select(["ID", xCol]).objects();
            }

            const numericData = data.filter(d => 
                typeof d[xCol] === "number" && !isNaN(d[xCol])
            );
            
            const nonNumericData = data.filter(d => 
                typeof d[xCol] !== "number" || isNaN(d[xCol])
            ).map(d => ({
                ...d,
                [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
            }));

            const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));

            let uniqueCategories;
            
            if (numericData.length === data.length)
            {
                uniqueCategories = [];
            }else{
                uniqueCategories = ["NaN", ...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
            }

            const categorySpace = uniqueCategories.length * 20; 
            const numericSpace = width - categorySpace; 
            let categoricalScale = null;
            
            if (numericData.length > 0)
            {
                uniqueCategories = sortCategories(uniqueCategories);
                const xScale = d3.scaleLinear()
                    .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
                    .range([0, numericSpace]);

                let yScale = null;
                
                const histogramGenerator = d3.histogram()
                    .domain(xScale.domain())
                    .thresholds(10);

                const bins = histogramGenerator(numericData.map(d => d[xCol]));

                if (groupByAttribute) {
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
                        .domain(uniqueCategories)
                        .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

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
                            const groupData = binData.filter(d => d[groupByAttribute] === g);
                            obj[g] = groupData.length;  
                            obj.group = g;
                            obj.groupIDs[g] = groupData.map(d => d.ID);
                        });
                        stackedData.push(obj);
                    });
            
                    const yMax = d3.max(stackedData, d => d.total);
                    yScale = d3.scaleLinear()
                        .domain([0, yMax])
                        .range([numericSpace, 0]);
            
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
                        .attr("fill", d => d.category ? "gray" : colorScale(d.group))
                        .attr("opacity", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? 1 : 0.7;
                        })
                        .attr("stroke", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? "black" : "none";
                        })
                        .attr("stroke-width", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? 2 : 0;
                        })
                        .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.data.x0))
                        .attr("y", d => yScale(d[1]))
                        .attr("width", binWidth)
                        .attr("height", d => yScale(d[0]) - yScale(d[1]));
                }
                else{
                    // No group by
                    const histData = histogramGenerator(numericData.map(d => d[xCol])).map(bin => {
                        return {
                            x0: bin.x0,
                            x1: bin.x1,
                            length: bin.length,
                            ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.ID)
                        };
                    });

                    const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
                    const categoricalStart = xScale.range()[1] + 10;

                    categoricalScale = d3.scaleOrdinal()
                        .domain(uniqueCategories)
                        .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

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
                        .range([numericSpace, 0]);
                    
                    svg.selectAll("rect")
                        .data(histData)
                        .join("rect")
                        .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.x0))
                        .attr("width", binWidth)
                        .attr("y", d => yScale(d.length))
                        .attr("height", d => numericSpace - yScale(d.length))
                        .attr("fill", (d) => {
                            const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? "gold" : (d.category ? "gray" : "steelblue");
                        })
                        // .attr("stroke", d => d.category ? "red" : "none")
                        .attr("stroke", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? "red" : "none";
                        })
                        // .attr("stroke-width", d => d.category ? 1 : 0)
                        .attr("stroke-width", (d) => {
                            const isPredicated = d.ids.some(ID => this.predicatePoints.some(p => p.ID === ID));
                            return isPredicated ? 1 : 0
                        })
                        .attr("opacity", 0.8);
                }
                
                svg
                    .append("g")
                    .attr("transform", `translate(0, ${numericSpace})`)
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
                        .attr("transform", `translate(10, ${numericSpace})`)
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
            else{   // Data is all categorical
                uniqueCategories = uniqueCategories.slice(1);
                uniqueCategories = sortCategories(uniqueCategories);

                const xScale = d3.scaleBand()
                    .domain(uniqueCategories)
                    .range([0, width]);

                let yScale = null;

                if (groupByAttribute) {
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
                        .attr("fill", d => colorScale(d.group))
                        .attr("opacity", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? 1 : 0.7;
                        })
                        .attr("stroke", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? "black" : "none";
                        })
                        .attr("stroke-width", (d) => {
                            const isSelected = d.data.groupIDs[d.group].some(ID => this.selectedPoints.some(p => p.ID === ID));                            
                            return isSelected ? 2 : 0;
                        })
                        .attr("x", d => xScale(d.data.category))
                        .attr("y", d => yScale(d[1]))
                        .attr("width", xScale.bandwidth())
                        .attr("height", d => yScale(d[0]) - yScale(d[1]));
                }
                else{
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
                        .attr("fill", (d) => {
                            const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? "gold" : "steelblue";
                        })
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
        /// Draw Heatmap ///
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

                if(groupByAttribute){
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
                                    .attr("fill", groupColorScale(group))
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? "black" : "white";
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 2 : 0;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });   
                }
                else{
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
                        .attr("fill", d => {
                            const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));

                            if (isSelected) {
                                return "gold"; 
                            }
                            if (d.y === "NaN") {
                                return "gray";
                            }
                            if (uniqueYStringBins.includes(d.y) || uniqueXStringBins.includes(d.x)) {
                                return "gray";
                            }
        
                            return colorScale(d.value); 
                        })
                        // .attr("stroke", "gray")
                        // .attr("stroke-width", 0.5)
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

                if(groupByAttribute){
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
                                    .attr("fill", groupColorScale(group))
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? "black" : "white";
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 2 : 0;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });                
                }
                else{
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
                        .attr("fill", d => {
                            const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));

                            if (isSelected) {
                                return "gold"; 
                            }
                            if (d.y === "NaN") {
                                return "gray";
                            }
                            if (uniqueYStringBins.includes(d.y)) {
                                return "gray";
                            }
        
                            return colorScale(d.value); 
                        })
                        // .attr("stroke", "gray")
                        // .attr("stroke-width", 0.5)
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

                if(groupByAttribute){
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
                                    .attr("fill", groupColorScale(group))
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? "black" : "white";
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 2 : 0;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });         

                }
                else{
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
                        .attr("fill", d => {
                            const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));

                            if (isSelected) {
                                return "gold"; 
                            }
                            if (d.y === "NaN") {
                                return "gray";
                            }
                            if (uniqueXStringBins.includes(d.x)) {
                                return "gray";
                            }
                            return colorScale(d.value); 
                        })
                        // .attr("stroke", "gray")
                        // .attr("stroke-width", 0.5)    
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
                if(groupByAttribute){
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
                                    .attr("fill", groupColorScale(group))
                                    .attr("opacity", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 1 : 0.7;
                                    })
                                    .attr("stroke", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? "black" : "white";
                                    })
                                    .attr("stroke-width", (d) => {
                                        const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                        return isSelected ? 2 : 0;
                                    })
                                    .attr("data-group", group);

                                yOffset += (yScale.bandwidth() * count) / total; 
                            });
                        });

                }
                else{
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
                        .attr("fill", (d) => {
                            const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                            return isSelected ? "gold" : colorScale(d.value);
                        })
                        // .attr("stroke", "gray")
                        // .attr("stroke-width", 0.5)    
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
            // svg.append("g")
            //     .attr("transform", `translate(0, ${height})`)  // Position at bottom
            //     .call(d3.axisBottom(xScale).tickFormat(d => d.length > 10 ? d.substring(0, 10) + "…" : d))  
            //     .selectAll("text")
            //     .style("text-anchor", "end")
            //     .style("font-size", "8px")
            //     .attr("dx", "-0.5em")
            //     .attr("dy", "0.5em")
            //     .attr("transform", "rotate(-45)");

            // // Add y-axis
            // svg.append("g")
            //     .attr("transform", `translate(-15, 0)`)  // Position at left
            //     .call(d3.axisLeft(yScale))
            //     .selectAll("text")
            //     .style("font-size", "8px");
        }

    }

    getScatterScale(data, column, size, isX = true) {
        const isNumeric = data.every(d => typeof d[column] === "number" && !isNaN(d[column]));
    
        if (isNumeric) {
            return d3.scaleLinear()
                .domain([Math.min(0, d3.min(data, d => d[column])), d3.max(data, d => d[column]) + 1])
                .range(isX ? [0, size] : [size, 0]); // X is left to right, Y is bottom to top
        } else {
            const uniqueCategories = [...new Set(data.map(d => String(d[column])))].sort();
            
            return d3.scaleBand()
                .domain(uniqueCategories)
                .range([0, size])
                .padding(0.1);
        }
    }

}

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

    const allNonNumericX = [...nonNumericXData, ...nonNumericData].filter(d =>
        typeof d[xCol] !== "number" || isNaN(d[xCol])
    ).map(d => ({
        ...d,
        [xCol]: (typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol])
    }));

    const allNonNumericY = [...nonNumericYData, ...nonNumericData].filter(d =>
        typeof d[xCol] !== "number" || isNaN(d[yCol])
    ).map(d => ({
        ...d,
        [yCol]: (typeof d[yCol] === "boolean" ? String(d[yCol]) : d[yCol])
    }));


    const groupedXCategories = d3.group(allNonNumericX, d => String(d[xCol]));
    const groupedYCategories = d3.group(allNonNumericY, d => String(d[yCol]));

    let uniqueXCategories, uniqueYCategories;

    if (numericData.length === data.length)
    {
        uniqueXCategories = [];
        uniqueYCategories = [];
    }else{
        uniqueXCategories = ["NaN",...[...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
        uniqueYCategories = ["NaN",...[...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
    }

    const categorySpace = 20 * Math.max(uniqueXCategories.length, uniqueYCategories.length);
    const numericSpace = this.size - categorySpace;

    return {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace};
}