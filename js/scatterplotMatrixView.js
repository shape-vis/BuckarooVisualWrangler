
let selectedBar = null;
let barX0 = 0;
let barX1 = 0;

class ScatterplotMatrixView{
    constructor(container) {
        this.container = container;

        this.size = 180; // Size of each cell in matrix
        this.xPadding = 150;
        this.yPadding = 90;
        this.labelPadding = 60;

        this.leftMargin = 120;
        this.topMargin = 30;
        this.bottomMargin = 125; 
        this.rightMargin = 60; 

        this.selection = null;

        this.xScale = d3.scaleLinear().domain([0, 100]).range([0, this.size]);
        this.yScale = d3.scaleLinear().domain([0, 100]).range([this.size, 0]);
        this.brushXCol = 0;
        this.brushYCol = 0;

        this.selectedPoints = [];
    }

    setSelectedPoints(points) {
        this.selectedPoints = points;
      }

    populateDropdownFromTable(table, controller) {
        const dropdownMenu = document.getElementById("dropdown-menu");
        const dropdownButton = document.getElementById("dropdown-button");
        const groupDropdown = document.getElementById("group-dropdown");
    
        dropdownMenu.innerHTML = ""; 
        groupDropdown.innerHTML = '<option value="">None</option>'; 

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

            // Group by append options
            let option = document.createElement("option");
            option.value = attr;
            option.textContent = attr;
            groupDropdown.appendChild(option);
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
    
        updateDropdownButton();
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
        const margin = { top: 30, right: 100, bottom: 50, left: 100 };
    
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
    }

    plotMatrix(givenData, groupByAttribute, selectedGroups) {  
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
        this.selectedPoints = [];
    
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
                                total: binData.length  
                            };
                            groups.forEach(g => {
                                obj[g] = binData.filter(d => d[groupByAttribute] === g).length;
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
                                total: catData.length,
                                category: category 
                            };
                            groups.forEach(g => {
                                obj[g] = catData.filter(d => d[groupByAttribute] === g).length;
                            });
                            stackedData.push(obj);
                        });
                
                        const yMax = d3.max(stackedData, d => d.total);
                        yScale = d3.scaleLinear()
                            .domain([0, yMax])
                            .range([numericSpace, 0]);
                
                        const stackGen = d3.stack().keys(groups);
                        const series = stackGen(stackedData);
                
                        const tooltip = d3.select("#tooltip");
                
                        cellGroup.selectAll("g.series")
                            .data(series)
                            .join("g")
                            .attr("class", "series")
                            .attr("fill", d => d.category ? "gray" : colorScale(d.key))
                            .attr("opacity", 0.8)
                            .selectAll("rect")
                            .data(d => d)
                            .join("rect")
                            .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.data.x0))
                            .attr("y", d => yScale(d[1]))
                            .attr("width", binWidth)
                            .attr("height", d => yScale(d[0]) - yScale(d[1]))
                            .on("mouseover", function(event, d) {
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
                            });
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
                            .attr("fill", d => d.category ? "gray" : "steelblue")
                            .attr("stroke", d => d.category ? "red" : "none")
                            .attr("stroke-width", d => d.category ? 1 : 0)
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.ids.join(","))
                            .on("mouseover", function(event, d) {
                                d3.select(this).attr("opacity", 0.5);
                                tooltip.style("display", "block")
                                    .html(d.category
                                        ? `<strong>${d.category} Count:</strong> ${d.length}`
                                        : `<strong>Bin Range:</strong> ${d.x0.toFixed(2)} - ${d.x1.toFixed(2)}<br><strong>Count:</strong> ${d.length}`)
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
                            });
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
                    cellGroup.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

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
                        
                        const stackedData = uniqueCategories.map(category => {
                            const obj = {
                            category: category,
                            x0: xScale(category),
                            x1: xScale(category) + xScale.bandwidth()
                            };
                            groups.forEach(g => {
                            obj[g] = nonNumericData.filter(d =>
                                String(d[xCol]) === category && d[groupByAttribute] === g
                            ).length;
                            });
                            return obj;
                        });
                        
                        const yMax = d3.max(stackedData, d => groups.reduce((sum, g) => sum + d[g], 0));
                        yScale = d3.scaleLinear().domain([0, yMax]).range([this.size, 0]);
                        const tooltip = d3.select("#tooltip");
                        
                        const stackGen = d3.stack().keys(groups);
                        const series = stackGen(stackedData);
                        
                        cellGroup.selectAll("g.series")
                            .data(series)
                            .join("g")
                            .attr("class", "series")
                            .attr("fill", d => colorScale(d.key))
                            .attr("opacity", 0.8)
                            .selectAll("rect")
                            .data(d => d)
                            .join("rect")
                            .attr("x", d => xScale(d.data.category))
                            .attr("y", d => yScale(d[1]))
                            .attr("width", xScale.bandwidth())
                            .attr("height", d => yScale(d[0]) - yScale(d[1]))
                            .on("mouseover", function(event, d) {
                            const group = d3.select(this.parentNode).datum().key;
                            const count = d[1] - d[0];
                            const totalCount = groups.reduce((sum, key) => sum + (d.data[key] || 0), 0);
                            d3.select(this).attr("opacity", 0.5);
                            tooltip.style("display", "block")
                                .html(`<strong>${d.data.category}</strong><br><strong>${group} Count:</strong> ${count}<br><strong>Total Bin Count:</strong> ${totalCount}`)
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
                            });
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
                        
                        const tooltip = d3.select("#tooltip");

                        cellGroup.selectAll("rect")
                            .data(histData)
                            .join("rect")
                            .attr("x", d => xScale(d.category))
                            .attr("width", xScale.bandwidth())
                            .attr("y", d => yScale(d.length))
                            .attr("height", d => Math.max(0, this.size - yScale(d.length)))
                            .attr("fill", "steelblue")
                            .attr("opacity", 0.8)
                            .attr("data-ids", d => d.ids.join(","))
                            .on("mouseover", function(event, d) {
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
                            });
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
    
            } 
            else {
                const lineViewButton = cellGroup.append("g")
                    .attr("class", "linechart-button")
                    .attr("cursor", "pointer")
                    .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute));

                lineViewButton.append("rect")
                    .attr("x", - 105)
                    .attr("y", - 35)
                    .attr("width", 40)
                    .attr("height", 15)
                    .attr("rx", 3)
                    .attr("fill", "#d3d3d3")
                    .attr("stroke", "#333");

                lineViewButton.append("text")
                    .attr("x", - 85)
                    .attr("y", - 25)
                    .attr("text-anchor", "middle")
                    .attr("font-size", "10px")
                    .attr("fill", "#333")
                    .text("Linechart");
                
                this.drawScatterplot(cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute);
            }
            });
        });

        this.updateLegend(groupByAttribute, givenData);

    }

    enableBrushing (givenData, handleBrush, handleBarClick, groupByAttribute){
        const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];
        console.log("Unique groups:", uniqueGroups);

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
                            .on("click", (event, d) => handleBarClick(event, d, xCol, groupByAttribute));
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
                            .on("click", (event, d) => handleBarClick(event, d, xCol, groupByAttribute));
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

                const allNonNumericX = [...nonNumericXData, ...nonNumericData].map(d => ({
                    ...d,
                    [xCol]: (typeof d[xCol] === "number" && isNaN(d[xCol])) || d[xCol] == null ? "NaN" : String(d[xCol])
                }));

                const allNonNumericY = [...nonNumericYData, ...nonNumericData].map(d => ({
                    ...d,
                    [yCol]: (typeof d[yCol] === "number" && isNaN(d[yCol])) || d[yCol] == null ? "NaN" : String(d[yCol])
                }));

                const groupedXCategories = d3.group(allNonNumericX, d => d[xCol]);
                const groupedYCategories = d3.group(allNonNumericY, d => d[yCol]);

                let uniqueXCategories, uniqueYCategories;

                if (numericData.length === data.length)
                {
                    uniqueXCategories = [];
                    uniqueYCategories = [];
                }else{
                    uniqueXCategories = ["NaN", ...[...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
                    uniqueYCategories = ["NaN", ...[...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
                }

                const categorySpace = 20 * Math.max(uniqueXCategories.length, uniqueYCategories.length);
                const numericSpace = this.size - categorySpace;

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

    drawScatterplot(cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute){
        const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];
        // console.log("Unique groups:", uniqueGroups);

        const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

        let data = [];

        if(groupByAttribute)
        {
            data = givenData.select([xCol, yCol, groupByAttribute]).objects(); 
        }
        else{
            data = givenData.select([xCol, yCol]).objects();
        }

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

        const allNonNumericX = [...nonNumericXData, ...nonNumericData].map(d => ({
            ...d,
            [xCol]: (typeof d[xCol] === "number" && isNaN(d[xCol])) || d[xCol] == null ? "NaN" : String(d[xCol])
        }));

        const allNonNumericY = [...nonNumericYData, ...nonNumericData].map(d => ({
            ...d,
            [yCol]: (typeof d[yCol] === "number" && isNaN(d[yCol])) || d[yCol] == null ? "NaN" : String(d[yCol])
        }));

        const groupedXCategories = d3.group(allNonNumericX, d => d[xCol]);
        const groupedYCategories = d3.group(allNonNumericY, d => d[yCol]);

        let uniqueXCategories, uniqueYCategories;

        if (numericData.length === data.length)
        {
            uniqueXCategories = [];
            uniqueYCategories = [];
        }else{
            uniqueXCategories = ["NaN", ...[...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
            uniqueYCategories = ["NaN", ...[...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
        }

        const categorySpace = 20 * Math.max(uniqueXCategories.length, uniqueYCategories.length);
        const numericSpace = this.size - categorySpace;

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
                // .attr("fill", d => (d.type === "numeric" ? "steelblue" : "gray"))
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return d.type === "numeric" ? "steelblue" : "gray"; 
                    }
                })
                .attr("stroke", d => (d.type.includes("nan") ? "red" : "none")) 
                .attr("stroke-width", d => (d.type.includes("nan") ? 1 : 0))
                .attr("opacity", 0.6)
                .on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "orange");
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
                // .attr("fill", d => (d.type === "nan-y" ? "gray" : "steelblue"))
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return d.type === "nan-y" ? "gray" : "steelblue"; 
                    }
                })
                .attr("stroke", d => (d.type === "nan-y" ? "red" : "none")) 
                .attr("stroke-width", d => (d.type === "nan-y" ? 1 : 0))
                .attr("opacity", 0.6)
                .on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "orange");
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
                // .attr("fill", d => (d.type === "nan-x" ? "gray" : "steelblue"))
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return d.type === "nan-x" ? "gray" : "steelblue"; 
                    }
                })
                .attr("stroke", d => (d.type === "nan-x" ? "red" : "none")) 
                .attr("stroke-width", d => (d.type === "nan-x" ? 1 : 0))
                .attr("opacity", 0.6)
                .on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "orange");
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

            cellGroup.selectAll("circle")
                .data(combinedData)
                .join("circle")
                .attr("cx", d => xScale(d[xCol]))
                .attr("cy", d => yScale(d[yCol]))
                .attr("r", 3)
                // .attr("fill", "steelblue")
                .attr("fill", d => {
                    if (groupByAttribute) {
                        return colorScale(d[groupByAttribute]);
                    } else {
                        return "steelblue"; 
                    }
                })
                .attr("opacity", 0.6)
                .on("mouseover", function(event, d) {
                    d3.select(this).attr("fill", "orange");
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

    switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute) {
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

        const allNonNumericX = [...nonNumericXData, ...nonNumericData].map(d => ({
            ...d,
            [xCol]: (typeof d[xCol] === "number" && isNaN(d[xCol])) || d[xCol] == null ? "NaN" : String(d[xCol])
        }));

        const allNonNumericY = [...nonNumericYData, ...nonNumericData].map(d => ({
            ...d,
            [yCol]: (typeof d[yCol] === "number" && isNaN(d[yCol])) || d[yCol] == null ? "NaN" : String(d[yCol])
        }));

        const groupedXCategories = d3.group(allNonNumericX, d => d[xCol]);
        const groupedYCategories = d3.group(allNonNumericY, d => d[yCol]);

        let uniqueXCategories, uniqueYCategories;

        if (numericData.length === data.length)
        {
            uniqueXCategories = [];
            uniqueYCategories = [];
        }else{
            uniqueXCategories = ["NaN", ...[...groupedXCategories.keys()].filter(d => d !== "NaN").sort()];
            uniqueYCategories = ["NaN", ...[...groupedYCategories.keys()].filter(d => d !== "NaN").sort()];
        }

        const categorySpace = 20 * Math.max(uniqueXCategories.length, uniqueYCategories.length);
        const numericSpace = this.size - categorySpace;

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

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2);
                  });
            }
            else{
                cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    .attr("stroke", "steelblue")
                    .attr("stroke-width", 2)
                    .attr("d", line);
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

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2);
                  });
            }
            else{
                cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    .attr("stroke", "steelblue")
                    .attr("stroke-width", 2)
                    .attr("d", line);
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

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2);
                  });
            }
            else{
                cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    .attr("stroke", "steelblue")
                    .attr("stroke-width", 2)
                    .attr("d", line);
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
            console.log("here in non numeric plot");
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

            if(groupByAttribute){
                groupedData = d3.group(combinedData, d => d[groupByAttribute]);
                groupedData.forEach((groupArray, key) => {
                    cellGroup.append("path")
                      .datum(groupArray)
                      .attr("class", "line")
                      .attr("d", line)
                      .attr("stroke", colorScale(key))
                      .attr("fill", "none")
                      .attr("stroke-width", 2);
                  });
            }
            else{
                console.log("here in no groupBy");
                cellGroup.append("path")
                    .datum(combinedData)
                    .attr("fill", "none")
                    .attr("stroke", "steelblue")
                    .attr("stroke-width", 2)
                    .attr("d", line);
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

        const lineViewButton = cellGroup.append("g")
            .attr("class", "scatterplot-button")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute));

        lineViewButton.append("rect")
            .attr("x", - 110)
            .attr("y", - 35)
            .attr("width", 45)
            .attr("height", 15)
            .attr("rx", 3)
            .attr("fill", "#d3d3d3")
            .attr("stroke", "#333");

        lineViewButton.append("text")
            .attr("x", - 87)
            .attr("y", - 25)
            .attr("text-anchor", "middle")
            .attr("font-size", "10px")
            .attr("fill", "#333")
            .text("Scatterplot");
    }

    restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`); // Hardcoded for stackoverflow tab
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));
        this.drawScatterplot(cellGroup,  svg, i, j, givenData, xCol, yCol, groupByAttribute);  

        const lineViewButton = cellGroup.append("g")
            .attr("class", "linechart-button")
            .attr("cursor", "pointer")
            .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute));

        lineViewButton.append("rect")
            .attr("x", - 105)
            .attr("y", - 35)
            .attr("width", 40)
            .attr("height", 15)
            .attr("rx", 3)
            .attr("fill", "#d3d3d3")
            .attr("stroke", "#333");

        lineViewButton.append("text")
            .attr("x", - 85)
            .attr("y", - 25)
            .attr("text-anchor", "middle")
            .attr("font-size", "10px")
            .attr("fill", "#333")
            .text("Linechart");
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
