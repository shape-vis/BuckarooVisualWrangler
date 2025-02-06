let selectedBar = null;
let barX0 = 0;
let barX1 = 0;

class ScatterplotMatrixView{
    constructor(container) {
        this.container = container;

        this.size = 180; // Size of each cell in matrix
        this.padding = 60;
        this.labelPadding = 20;

        this.leftMargin = 60;
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
        let matrixSize = columns.length * this.size + (columns.length - 1) * this.padding; // 3 * 175 + (2) * 25 = 575

        let svgWidth = matrixSize + this.labelPadding + this.leftMargin + this.rightMargin;
        let svgHeight = matrixSize + this.labelPadding + this.topMargin + this.bottomMargin;

        const container = d3.select(this.container);
        container.selectAll("*").remove();
        this.selectedPoints = [];
    
        const svg = container
            .append("svg")
            .attr("width", svgWidth) // 575 + 20 + 60 + 60 = 715
            .attr("height", svgHeight);
                
        columns.forEach((xCol, i) => {
            columns.forEach((yCol, j) => {
            const cellGroup = svg
                .append("g")
                .attr("transform", `translate(${this.leftMargin + j * (this.size + this.padding)}, ${this.topMargin + i * (this.size + this.padding)})`);

            if (i === j) {
                const data = givenData.select(["id", xCol]).objects();

                // const numericData = data.filter(d => !isNaN(d[xCol])); //isNumber()
                // const nonNumericData = data.filter(d => isNaN(d[xCol])); //Convert all other types to strings. Use scaleOrdinal. Order the set.
                const numericData = data.filter(d => 
                    typeof d[xCol] === "number" && !isNaN(d[xCol])
                );
                
                const nonNumericData = data.filter(d => 
                    typeof d[xCol] !== "number" || isNaN(d[xCol])
                ).map(d => ({
                    ...d,
                    [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
                }));
                const uniqueCategories = [...new Set(nonNumericData.map(d => String(d[xCol])))] 

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
                        ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.id)
                    };
                });

                const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
                const categoricalStart = xScale.range()[1] + 10;

                const categoricalScale = d3.scaleOrdinal()
                    .domain(uniqueCategories)
                    .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

                // if (nonNumericData.length > 0) {
                //     histData.push({
                //         x0: this.size,  
                //         x1: this.size + 40,  
                //         length: nonNumericData.length,
                //         ids: nonNumericData.map(d => d.id),
                //         isNan: true  
                //     });
                // }

                uniqueCategories.forEach(category => {
                    histData.push({
                        x0: categoricalScale(category),
                        x1: categoricalScale(category) + binWidth,
                        length: nonNumericData.filter(d => String(d[xCol]) === category).length,
                        ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.id),
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
                    // .attr("x", (d) => d.isNan ? d.x0 : xScale(d.x0))
                    // .attr("width", (d) => d.isNan ? 20 : xScale(d.x1) - xScale(d.x0))
                    // .attr("y", (d) => yScale(d.length))
                    // .attr("height", (d) => this.size - yScale(d.length))
                    // .attr("fill", (d) => d.isNan ? "gray" : "steelblue") 
                    // .attr("stroke", d => (d.isNan ? "red" : "none")) 
                    // .attr("stroke-width", d => (d.isNan ? 1 : 0))  
                    // .attr("opacity", 0.8)
                    // .attr("data-ids", d => d.ids.join(","))
                    // .on("mouseover", function(event, d) {
                    //     d3.select(this).attr("fill", "orange");
                    //     tooltip.style("display", "block")
                    //         .html(d.isNan
                    //             ? `<strong>NaN Count:</strong> ${d.length}`
                    //             : `<strong>Bin Range:</strong> ${d.x0.toFixed(2)} - ${d.x1.toFixed(2)}<br><strong>Count:</strong> ${d.length}`)
                    //         .style("left", `${event.pageX + 10}px`)
                    //         .style("top", `${event.pageY + 10}px`);
                    // })
                    // .on("mousemove", function(event) {
                    //     tooltip.style("left", `${event.pageX + 10}px`)
                    //         .style("top", `${event.pageY + 10}px`);
                    // })
                    // .on("mouseout", function() {
                    //     d3.select(this).attr("fill", (d) => d.isNan ? "gray" : "steelblue");
                    //     tooltip.style("display", "none");
                    // });

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
                    .attr("x", this.leftMargin + j * (this.size + this.padding) + this.size / 2) 
                    .attr("y", this.topMargin + (i + 1) * (this.size + this.padding) - 20) 
                    .style("text-anchor", "middle")
                    .text(xCol);
    
                const xPosition = this.leftMargin + j * (this.size + this.padding) - this.labelPadding - 10; 
                const yPosition = this.topMargin + i * (this.size + this.padding) + this.size / 2; 
                
                svg
                    .append("text")
                    .attr("x", xPosition) 
                    .attr("y", yPosition) 
                    .style("text-anchor", "middle")
                    .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                    .text("count");
            } 
            else {
                const data = givenData.select([xCol, yCol]).objects(); 

                let numericData = data.filter(d => !isNaN(d[xCol]) && !isNaN(d[yCol]));
                let nonNumericXData = data.filter(d => isNaN(d[xCol]) && !isNaN(d[yCol])); 
                let nonNumericYData = data.filter(d => !isNaN(d[xCol]) && isNaN(d[yCol])); 
                let nonNumericData = data.filter(d => isNaN(d[xCol]) && isNaN(d[yCol]));

                const combinedData = [
                    ...numericData.map(d => ({ ...d, type: "numeric" })),
                    ...nonNumericXData.map(d => ({ ...d, type: "nan-x" })),
                    ...nonNumericYData.map(d => ({ ...d, type: "nan-y" })),
                    ...nonNumericData.map(d => ({ ...d, type: "nan-xy" }))
                ];

                const tooltip = d3.select("#tooltip");

                const nanXPosition = this.size + 15; 
                const nanYPosition = this.size - (this.size + 15); 

                cellGroup.selectAll("circle")
                    .data(combinedData)
                    .join("circle")
                    .attr("cx", d => {
                        if (d.type === "numeric") return this.xScale(d[xCol]);
                        if (d.type === "nan-x" || d.type === "nan-xy") return nanXPosition;
                        return this.xScale(d[xCol]); 
                    })
                    .attr("cy", d => {
                        if (d.type === "numeric") return this.yScale(d[yCol]);
                        if (d.type === "nan-y" || d.type === "nan-xy") return nanYPosition;
                        return this.yScale(d[yCol]);
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
    
                // const xScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[xCol]))
                //     .range([0, this.size]);
                // const yScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[yCol]))
                //     .range([this.size, 0]);
    
                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${this.size})`)
                    .call(d3.axisBottom(this.xScale));
    
                cellGroup.append("g").call(d3.axisLeft(this.yScale));
    
                svg
                    .append("text")
                    .attr("x", this.leftMargin + j * (this.size + this.padding) + this.size / 2)
                    .attr("y", this.topMargin + (i + 1) * (this.size + this.padding) - 20) 
                    .style("text-anchor", "middle")
                    .text(xCol);
    
                const xPosition = this.leftMargin + j * (this.size + this.padding) - this.labelPadding - 10; 
                const yPosition = this.topMargin + i * (this.size + this.padding) + this.size / 2; 
                
                svg
                    .append("text")
                    .attr("x", xPosition) 
                    .attr("y", yPosition) 
                    .style("text-anchor", "middle")
                    .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                    .text(yCol);

                cellGroup
                    .append("text")
                    .attr("x", this.size + 22)
                    .attr("y", this.size + 16)
                    .style("font-size", "12px")
                    .attr("text-anchor", "middle")
                    .text("Nan");

                cellGroup.append("text")
                    .attr("x", -22) 
                    .attr("y", 5) 
                    .attr("text-anchor", "middle")
                    .attr("transform", `rotate(-90, -30, -10)`) 
                    .style("font-size", "12px")
                    .text("Nan");
                }
            });
        });

    }

    enableBrushing (givenData, handleBrush, handleBarClick){
        let columns = givenData.columnNames().slice(1);
        let matrixSize = columns.length * this.size + (columns.length - 1) * this.padding; // 3 * 175 + (2) * 25 = 575
        let svgWidth = matrixSize + this.labelPadding + this.leftMargin + this.rightMargin;
        let svgHeight = matrixSize + this.labelPadding + this.topMargin + this.bottomMargin;

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
                .attr("transform", `translate(${this.leftMargin + j * (this.size + this.padding)}, ${this.topMargin + i * (this.size + this.padding)})`); 
    
            // const brush = d3.brush()
            //     .extent([[0, 0], [this.size, this.size]]) 
            //     .on("start brush end", (event) => handleBrush(event, this.xScale, this.yScale, xCol, yCol));  

            if (i === j) {
                
                const data = givenData.select(["id", xCol]).objects();

                const numericData = data.filter(d => 
                    typeof d[xCol] === "number" && !isNaN(d[xCol])
                );
                
                const nonNumericData = data.filter(d => 
                    typeof d[xCol] !== "number" || isNaN(d[xCol])
                ).map(d => ({
                    ...d,
                    [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
                }));
                const uniqueCategories = [...new Set(nonNumericData.map(d => String(d[xCol])))] 

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
                        ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.id)
                    };
                });

                const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
                const categoricalStart = xScale.range()[1] + 10;

                const categoricalScale = d3.scaleOrdinal()
                    .domain(uniqueCategories)
                    .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

                // if (nonNumericData.length > 0) {
                //     histData.push({
                //         x0: this.size,  
                //         x1: this.size + 40,  
                //         length: nonNumericData.length,
                //         ids: nonNumericData.map(d => d.id),
                //         isNan: true  
                //     });
                // }

                uniqueCategories.forEach(category => {
                    histData.push({
                        x0: categoricalScale(category),
                        x1: categoricalScale(category) + binWidth,
                        length: nonNumericData.filter(d => String(d[xCol]) === category).length,
                        ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.id),
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
                        const isSelected = d.ids.some(id => this.selectedPoints.some(p => p.id === id));
                        return isSelected ? "red" : (d.category ? "gray" : "steelblue");
                    })
                    .attr("stroke", d => (d.category ? "red" : "none")) 
                    .attr("stroke-width", d => (d.category ? 1 : 0))  
                    .attr("opacity", 0.8)
                    .attr("data-ids", d => d.ids.join(","))
                    .on("click", (event, d) => handleBarClick(event, d, xCol));
                    // .on("mouseover", function(event, d) {
                    //     d3.select(this).attr("fill", "orange");
                    //     tooltip.style("display", "block")
                    //         .html(`<strong>bin range:</strong> ${d.x0.toFixed(2)} - ${d.x1.toFixed(2)}<br><strong>count:</strong> ${d.length}`)
                    //         .style("left", `${event.pageX + 10}px`)
                    //         .style("top", `${event.pageY + 10}px`);
                    // })
                    // .on("mousemove", function(event) {
                    //     tooltip.style("left", `${event.pageX + 10}px`)
                    //         .style("top", `${event.pageY + 10}px`);
                    // })
                    // .on("mouseout", function() {
                    //     d3.select(this).attr("fill", "steelblue");
                    //     tooltip.style("display", "none");
                    // });
            
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
                    .attr("x", this.leftMargin + j * (this.size + this.padding) + this.size / 2) 
                    .attr("y", this.topMargin + (i + 1) * (this.size + this.padding) - 20) 
                    .style("text-anchor", "middle")
                    .text(xCol);
    
                const xPosition = this.leftMargin + j * (this.size + this.padding) - this.labelPadding - 10; 
                const yPosition = this.topMargin + i * (this.size + this.padding) + this.size / 2; 
                
                svg
                    .append("text")
                    .attr("x", xPosition) 
                    .attr("y", yPosition) 
                    .style("text-anchor", "middle")
                    .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                    .text("count");
            } 
            else {
                const data = givenData.select([xCol, yCol]).objects(); 

                let numericData = data.filter(d => !isNaN(d[xCol]) && !isNaN(d[yCol]));
                let nonNumericXData = data.filter(d => isNaN(d[xCol]) && !isNaN(d[yCol])); 
                let nonNumericYData = data.filter(d => !isNaN(d[xCol]) && isNaN(d[yCol])); 
                let nonNumericData = data.filter(d => isNaN(d[xCol]) && isNaN(d[yCol]));

                const combinedData = [
                    ...numericData.map(d => ({ ...d, type: "numeric" })),
                    ...nonNumericXData.map(d => ({ ...d, type: "nan-x" })),
                    ...nonNumericYData.map(d => ({ ...d, type: "nan-y" })),
                    ...nonNumericData.map(d => ({ ...d, type: "nan-xy" }))
                ];

                const tooltip = d3.select("#tooltip");

                const isSelected = (d) => this.selectedPoints.some(p => 
                    (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
                    (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
                    (p[yCol] === d[yCol] || isNaN(d[yCol]))
                );
    
                // const xScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[xCol]))
                //     .range([0, this.size]);
                // const yScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[yCol]))
                //     .range([this.size, 0]);

                const brush = d3.brush()
                    .extent([[-20, -40], [this.size + 20, this.size + 20]]) 
                    .on("end", (event) => handleBrush(event, this.xScale, this.yScale, xCol, yCol));  

                const nanXPosition = this.size + 15; 
                const nanYPosition = this.size - (this.size + 15); 

                cellGroup.selectAll("circle")
                    .data(combinedData)
                    .join("circle")
                    .attr("cx", d => {
                        if (d.type === "numeric") return this.xScale(d[xCol]);
                        if (d.type === "nan-x" || d.type === "nan-xy") return nanXPosition;
                        return this.xScale(d[xCol]);
                    })
                    .attr("cy", d => {
                        if (d.type === "numeric") return this.yScale(d[yCol]);
                        if (d.type === "nan-y" || d.type === "nan-xy") return nanYPosition;
                        return this.yScale(d[yCol]); 
                    })
                    .attr("r", d => (d.type.includes("nan") ? 4 : 3))
                    .attr("fill", d => isSelected(d) ? "red" : (d.type === "numeric" ? "steelblue" : "gray"))
                    .attr("stroke", d => (d.type.includes("nan") ? "red" : "none")) 
                    .attr("stroke-width", d => (d.type.includes("nan") ? 1 : 0))
                    .attr("opacity", 0.8);
                    // .on("mouseover", function(event, d) {
                    //     d3.select(this).attr("fill", "orange");
                    //     tooltip.style("display", "block")
                    //         .html(`<strong>${xCol}:</strong> ${d[xCol]}<br><strong>${yCol}:</strong> ${d[yCol]}`)
                    //         .style("left", `${event.pageX + 10}px`)
                    //         .style("top", `${event.pageY + 10}px`);
                    // })
                    // .on("mousemove", function(event) {
                    //     tooltip.style("left", `${event.pageX + 10}px`)
                    //         .style("top", `${event.pageY + 10}px`);
                    // })
                    // .on("mouseout", function() {
                    //     d3.select(this).attr("fill", d => isSelected(d) ? "red" : (d.type === "numeric" ? "steelblue" : "gray"));
                    //     tooltip.style("display", "none");
                    // });
                    
                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${this.size})`)
                    .call(d3.axisBottom(this.xScale));
    
                cellGroup.append("g").call(d3.axisLeft(this.yScale));
    
                cellGroup.append("g")
                    .attr("class", "brush")  
                    .call(brush);            
    
                svg
                    .append("text")
                    .attr("x", this.leftMargin + j * (this.size + this.padding) + this.size / 2) 
                    .attr("y", this.topMargin + (i + 1) * (this.size + this.padding) - 20) 
                    .style("text-anchor", "middle")
                    .text(xCol);
    
                const xPosition = this.leftMargin + j * (this.size + this.padding) - this.labelPadding - 10; 
                const yPosition = this.topMargin + i * (this.size + this.padding) + this.size / 2; 
                
                svg
                    .append("text")
                    .attr("x", xPosition) 
                    .attr("y", yPosition) 
                    .style("text-anchor", "middle")
                    .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
                    .text(yCol);

                cellGroup
                    .append("text")
                    .attr("x", this.size + 22)
                    .attr("y", this.size + 16)
                    .style("font-size", "12px")
                    .attr("text-anchor", "middle")
                    .text("Nan");

                cellGroup.append("text")
                    .attr("x", -22) 
                    .attr("y", 5) 
                    .attr("text-anchor", "middle")
                    .attr("transform", `rotate(-90, -30, -10)`) 
                    .style("font-size", "12px")
                    .text("Nan");
            }
            });
        });
    }

}

