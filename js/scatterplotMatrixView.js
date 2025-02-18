let selectedBar = null;
let barX0 = 0;
let barX1 = 0;

class ScatterplotMatrixView{
    constructor(container) {
        this.container = container;

        this.size = 180; // Size of each cell in matrix
        this.xPadding = 150;
        this.yPadding = 60;
        this.labelPadding = 20;

        this.leftMargin = 120;
        this.topMargin = 30;
        this.bottomMargin = 25; 
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

    plotMatrix(givenData) {    
        let columns = givenData.columnNames().slice(1);
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
                const data = givenData.select(["ID", xCol]).objects();

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

                const xScale = d3.scaleLinear()
                    .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
                    .range([0, numericSpace]);

                const histogramGenerator = d3.histogram()
                    .domain(xScale.domain())
                    .thresholds(10);

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

                const categoricalScale = d3.scaleOrdinal()
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
                    
                const tooltip = d3.select("#tooltip");
    
                const yScale = d3.scaleLinear()
                    .domain([0, d3.max(histData, (d) => d.length)])
                    .range([numericSpace, 0]);
    
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
                        d3.select(this).attr("fill", "orange");
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
                        d3.select(this).attr("fill", (d) => d.category ? "gray" : "steelblue");
                        tooltip.style("display", "none");
                    });

                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${numericSpace})`)
                    .call(d3.axisBottom(xScale));

                if (uniqueCategories.length > 0) {
                    cellGroup.append("g")
                        .attr("transform", `translate(10, ${numericSpace})`)
                        .call(d3.axisBottom(categoricalScale))
                        .selectAll("text")
                        .style("text-anchor", "end") 
                        .attr("transform", "rotate(-45)") 
                        .style("font-size", "10px"); 
                }
    
                cellGroup.append("g").call(d3.axisLeft(yScale));
    
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
            else {
                const lineViewButton = cellGroup.append("g")
                    .attr("class", "linechart-button")
                    .attr("cursor", "pointer")
                    .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID));

                lineViewButton.append("rect")
                    .attr("x", - 105)
                    .attr("y", 0)
                    .attr("width", 40)
                    .attr("height", 15)
                    .attr("rx", 3)
                    .attr("fill", "#d3d3d3")
                    .attr("stroke", "#333");

                lineViewButton.append("text")
                    .attr("x", - 85)
                    .attr("y", 10)
                    .attr("text-anchor", "middle")
                    .attr("font-size", "10px")
                    .attr("fill", "#333")
                    .text("Linechart");
                
                this.drawScatterplot(cellGroup, svg, i, j, givenData, xCol, yCol);
            }
            });
        });

    }

    enableBrushing (givenData, handleBrush, handleBarClick){
        let columns = givenData.columnNames().slice(1);
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
                
                const data = givenData.select(["ID", xCol]).objects();

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

                const xScale = d3.scaleLinear()
                    .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
                    .range([0, numericSpace]);

                const histogramGenerator = d3.histogram()
                    .domain(xScale.domain())
                    .thresholds(10);

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

                const categoricalScale = d3.scaleOrdinal()
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
                    
                const tooltip = d3.select("#tooltip");
    
                const yScale = d3.scaleLinear()
                    .domain([0, d3.max(histData, (d) => d.length)])
                    .range([numericSpace, 0]);
    
                const bars = cellGroup.selectAll("rect")
                    .data(histData)
                    .join("rect")
                    .attr("x", (d) => d.category ? categoricalScale(d.category) : xScale(d.x0))
                    .attr("width", binWidth)
                    .attr("y", (d) => yScale(d.length))
                    .attr("height", (d) => numericSpace - yScale(d.length))
                    .attr("fill", (d) => {
                        const isSelected = d.ids.some(ID => this.selectedPoints.some(p => p.ID === ID));
                        return isSelected ? "red" : (d.category ? "gray" : "steelblue");
                    })
                    .attr("stroke", d => (d.category ? "red" : "none")) 
                    .attr("stroke-width", d => (d.category ? 1 : 0))  
                    .attr("opacity", 0.8)
                    .attr("data-ids", d => d.ids.join(","))
                    .on("click", (event, d) => handleBarClick(event, d, xCol));
            
                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${numericSpace})`)
                    .call(d3.axisBottom(xScale));

                if (uniqueCategories.length > 0) {
                    cellGroup.append("g")
                        .attr("transform", `translate(10, ${numericSpace})`)
                        .call(d3.axisBottom(categoricalScale))
                        .selectAll("text")
                        .style("text-anchor", "end") 
                        .attr("transform", "rotate(-45)") 
                        .style("font-size", "10px"); 
                }
    
                cellGroup.append("g").call(d3.axisLeft(yScale));
    
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
            else {
                const data = givenData.select([xCol, yCol]).objects(); 

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

                const xScale = d3.scaleLinear()
                    .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
                    .range([0, numericSpace]);

                const xTickValues = xScale.ticks(); 
                const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

                const categoricalXStart = xScale.range()[1] + 10;
                const categoricalXScale = d3.scaleOrdinal()
                    .domain(uniqueXCategories)
                    .range([...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * (xTickSpacing + 5)))); 

                const yScale = d3.scaleLinear()
                    .domain([Math.min(0, d3.min(numericData, d => d[yCol])), d3.max(numericData, d => d[yCol]) + 1])
                    .range([numericSpace, 0]);

                const categoricalYStart = yScale.range()[1] - 10;
                const categoricalYScale = d3.scaleOrdinal()
                    .domain(uniqueYCategories)
                    .range([...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * (xTickSpacing + 5))));
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
                    .attr("fill", d => isSelected(d) ? "red" : (d.type === "numeric" ? "steelblue" : "gray"))
                    .attr("stroke", d => (d.type.includes("nan") ? "red" : "none")) 
                    .attr("stroke-width", d => (d.type.includes("nan") ? 1 : 0))
                    .attr("opacity", 0.8);
                    
                cellGroup.append("g")
                    .attr("class", "brush")  
                    .call(brush);  

                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${numericSpace})`)
                    .call(d3.axisBottom(xScale));

                if (uniqueXCategories.length > 0) {
                cellGroup.append("g")
                    .attr("transform", `translate(0, ${numericSpace})`)
                    .call(d3.axisBottom(categoricalXScale))
                    .selectAll("text")
                    .style("text-anchor", "end") 
                    .attr("transform", "rotate(-45)") 
                    .style("font-size", "10px"); 
                }

                cellGroup.append("g").call(d3.axisLeft(yScale));

                if (uniqueYCategories.length > 0) {
                cellGroup.append("g")
                    .attr("transform", `translate(0, 0)`)
                    .call(d3.axisLeft(categoricalYScale))
                    .selectAll("text")
                    .style("text-anchor", "end") 
                    .style("font-size", "10px"); 
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
            });
        });
    }

    drawScatterplot(cellGroup, svg, i, j, givenData, xCol, yCol){
        const data = givenData.select([xCol, yCol]).objects(); 

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

        const xScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
            .range([0, numericSpace]);

        const xTickValues = xScale.ticks(); 
        const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

        const categoricalXStart = xScale.range()[1] + 10;
        const categoricalXScale = d3.scaleOrdinal()
            .domain(uniqueXCategories)
            .range([...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * (xTickSpacing + 5)))); 

        const yScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(numericData, d => d[yCol])), d3.max(numericData, d => d[yCol]) + 1])
            .range([numericSpace, 0]);

        const categoricalYStart = yScale.range()[1] - 10;
        const categoricalYScale = d3.scaleOrdinal()
            .domain(uniqueYCategories)
            .range([...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * (xTickSpacing + 5))));
            

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
            .attr("fill", d => (d.type === "numeric" ? "steelblue" : "gray"))
            .attr("stroke", d => (d.type.includes("nan") ? "red" : "none")) 
            .attr("stroke-width", d => (d.type.includes("nan") ? 1 : 0))
            .attr("opacity", 0.8)
            .on("mouseover", function(event, d) {
                d3.select(this).attr("fill", "orange");
                tooltip.style("display", "block")
                    .html(`<strong>${xCol}:</strong> ${d[xCol]}<br><strong>${yCol}:</strong> ${d[yCol]}`)
                    .style("left", `${event.pageX + 10}px`)
                    .style("top", `${event.pageY + 10}px`);
            })
            .on("mousemove", function(event) {
                tooltip.style("left", `${event.pageX + 10}px`)
                    .style("top", `${event.pageY + 10}px`);
            })
            .on("mouseout", function() {
                d3.select(this).attr("fill", d => (d.type === "numeric" ? "steelblue" : "gray"));
                tooltip.style("display", "none");
            });

        cellGroup
            .append("g")
            .attr("transform", `translate(0, ${numericSpace})`)
            .call(d3.axisBottom(xScale));

        if (uniqueXCategories.length > 0) {
        cellGroup.append("g")
            .attr("transform", `translate(0, ${numericSpace})`)
            .call(d3.axisBottom(categoricalXScale))
            .selectAll("text")
            .style("text-anchor", "end") 
            .attr("transform", "rotate(-45)") 
            .style("font-size", "10px"); 
        }

        cellGroup.append("g").call(d3.axisLeft(yScale));

        if (uniqueYCategories.length > 0) {
        cellGroup.append("g")
            .attr("transform", `translate(0, 0)`)
            .call(d3.axisLeft(categoricalYScale))
            .selectAll("text")
            .style("text-anchor", "end") 
            .style("font-size", "10px"); 
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

    switchToLineChart(givenData, svg, xCol, yCol, cellID) {
        const cellGroup = d3.select(`#${cellID}`);
        const [, i, j] = cellID.split("-").map(d => parseInt(d));

        cellGroup.selectAll("*").remove();  

        const data = givenData.select([xCol, yCol]).objects(); 

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

        const xScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
            .range([0, numericSpace]);

        const xTickValues = xScale.ticks(); 
        const xTickSpacing = xScale(xTickValues[1]) - this.xScale(xTickValues[0]); 

        const categoricalXStart = xScale.range()[1] + 10;
        const categoricalXScale = d3.scaleOrdinal()
            .domain(uniqueXCategories)
            .range([...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * (xTickSpacing + 5)))); 

        const yScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(numericData, d => d[yCol])), d3.max(numericData, d => d[yCol]) + 1])
            .range([numericSpace, 0]);

        const categoricalYStart = yScale.range()[1] - 10;
        const categoricalYScale = d3.scaleOrdinal()
            .domain(uniqueYCategories)
            .range([...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * (xTickSpacing + 5))));

        console.log("Before sorting:", combinedData.map(d => ({ x: d[xCol], type: d.type })));


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

        console.log("After sorting:", combinedData.map(d => ({ x: d[xCol], type: d.type })));

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

        cellGroup.append("path")
            .datum(combinedData)
            .attr("fill", "none")
            .attr("stroke", "steelblue")
            .attr("stroke-width", 2)
            .attr("d", line);

        cellGroup
            .append("g")
            .attr("transform", `translate(0, ${numericSpace})`)
            .call(d3.axisBottom(xScale));

        if (uniqueXCategories.length > 0) {
        cellGroup.append("g")
            .attr("transform", `translate(0, ${numericSpace})`)
            .call(d3.axisBottom(categoricalXScale))
            .selectAll("text")
            .style("text-anchor", "end") 
            .attr("transform", "rotate(-45)") 
            .style("font-size", "10px"); 
        }

        cellGroup.append("g").call(d3.axisLeft(yScale));

        if (uniqueYCategories.length > 0) {
        cellGroup.append("g")
            .attr("transform", `translate(0, 0)`)
            .call(d3.axisLeft(categoricalYScale))
            .selectAll("text")
            .style("text-anchor", "end") 
            .style("font-size", "10px"); 
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

        const lineViewButton = cellGroup.append("g")
            .attr("class", "scatterplot-button")
            .attr("cursor", "pointer")
            .on("click", () => this.restoreScatterplot(givenData, svg, xCol, yCol, cellID));

        lineViewButton.append("rect")
            .attr("x", - 110)
            .attr("y", 0)
            .attr("width", 45)
            .attr("height", 15)
            .attr("rx", 3)
            .attr("fill", "#d3d3d3")
            .attr("stroke", "#333");

        lineViewButton.append("text")
            .attr("x", - 87)
            .attr("y", 10)
            .attr("text-anchor", "middle")
            .attr("font-size", "10px")
            .attr("fill", "#333")
            .text("Scatterplot");
    }

    restoreScatterplot(givenData, svg, xCol, yCol, cellID) {
        const cellGroup = d3.select(`#${cellID}`);
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));
        this.drawScatterplot(cellGroup,  svg, i, j, givenData, xCol, yCol);  

        const lineViewButton = cellGroup.append("g")
            .attr("class", "linechart-button")
            .attr("cursor", "pointer")
            .on("click", () => this.switchToLineChart(givenData, svg, xCol, yCol, cellID));

        lineViewButton.append("rect")
            .attr("x", - 105)
            .attr("y", 0)
            .attr("width", 40)
            .attr("height", 15)
            .attr("rx", 3)
            .attr("fill", "#d3d3d3")
            .attr("stroke", "#333");

        lineViewButton.append("text")
            .attr("x", - 85)
            .attr("y", 10)
            .attr("text-anchor", "middle")
            .attr("font-size", "10px")
            .attr("fill", "#333")
            .text("Linechart");
    }

}