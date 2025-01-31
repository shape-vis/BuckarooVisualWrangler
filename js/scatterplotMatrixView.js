let selectedBar = null;
let barX0 = 0;
let barX1 = 0;

class ScatterplotMatrixView{
    constructor(container) {
        this.container = container;

        this.size = 175; // Size of each cell in matrix
        this.padding = 60;
        this.labelPadding = 20;

        this.leftMargin = 60;
        this.topMargin = 10;
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

        // let nonNumericCounts = columns.map(col => {
        //     let nonNumericData = givenData.select([col]).objects().filter(d => isNaN(d[col]));
        //     let uniqueValues = new Set(nonNumericData.map(d => d[col]));
        //     return uniqueValues.size;
        // });
    
        // let maxNonNumericBins = Math.max(...nonNumericCounts); // Find the max needed bins
        // let extraWidth = maxNonNumericBins * 30; // Adjust width dynamically per extra bin
        // this.rightMargin = Math.max(100, extraWidth + 20); // Ensure minimum spacing

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

                const numericData = data.filter(d => !isNaN(d[xCol]));
                const nonNumericData = data.filter(d => isNaN(d[xCol]));

                // let nonNumericGroups = d3.group(nonNumericData, d => d[xCol]);

                const xScale = d3.scaleLinear()
                    .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
                    .range([0, this.size]);

                const histogramGenerator = d3.histogram()
                    .domain(xScale.domain())
                    .thresholds(10);

                const histData = histogramGenerator(numericData.map(d => d[xCol])).map(bin => {
                    return {
                        x0: bin.x0,
                        x1: bin.x1,
                        length: bin.length,
                        ids: data.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.id)
                    };
                });
                    
                const tooltip = d3.select("#tooltip");
    
                const yScale = d3.scaleLinear()
                    .domain([0, d3.max(histData, (d) => d.length)])
                    .range([this.size, 0]);
    
                cellGroup.selectAll("rect")
                    .data(histData)
                    .join("rect")
                    .attr("x", (d) => xScale(d.x0))
                    .attr("width", (d) => xScale(d.x1) - xScale(d.x0))
                    .attr("y", (d) => yScale(d.length))
                    .attr("height", (d) => this.size - yScale(d.length))
                    .attr("fill", "steelblue")                    
                    .attr("opacity", 0.8)
                    .attr("data-ids", d => d.ids.join(","))
                    .on("mouseover", function(event, d) {
                        d3.select(this).attr("fill", "orange");
                        tooltip.style("display", "block")
                            .html(`<strong>bin range:</strong> ${d.x0.toFixed(2)} - ${d.x1.toFixed(2)}<br><strong>count:</strong> ${d.length}`)
                            .style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mousemove", function(event) {
                        tooltip.style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mouseout", function() {
                        d3.select(this).attr("fill", "steelblue");
                        tooltip.style("display", "none");
                    });

                // let binIndex = 0;
                // nonNumericGroups.forEach((group,key) => {
                //     let binData = {
                //         label: key, 
                //         length: group.length,
                //         ids: group.map(d => d.id) 
                //     };

                let nanBinData = {
                    x0: this.size,  
                    x1: this.size + 40,  
                    length: nonNumericData.length,
                    ids: nonNumericData.map(d => d.id) 
                };

                cellGroup.append("rect")
                    .attr("class", "bar nan")
                    .attr("x", nanBinData.x0)
                    .attr("y", yScale(nanBinData.length))
                    .attr("width", 20)
                    .attr("height", this.size - yScale(nanBinData.length))
                    .attr("fill", "steelblue")                    
                    .attr("opacity", 0.8)
                    .attr("data-ids", nanBinData.ids.join(","))
                    .on("mouseover", function(event, d) {
                        d3.select(this).attr("fill", "orange");
                        tooltip.style("display", "block")
                            .html(`<strong>NaN Count:</strong> ${nanBinData.length}`)
                            .style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mousemove", function(event) {
                        tooltip.style("left", `${event.pageX + 10}px`)
                            .style("top", `${event.pageY + 10}px`);
                    })
                    .on("mouseout", function() {
                        d3.select(this).attr("fill", "steelblue");
                        tooltip.style("display", "none");
                    });

                cellGroup.append("text")
                        .attr("x", nanBinData.x0 + 20)
                        .attr("y", this.size + 15)
                        .attr("text-anchor", "middle")
                        .style("font-size", "12px")
                        .text("Nan");

                //         binIndex++;
                // });
            
                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${this.size})`)
                    .call(d3.axisBottom(xScale));
    
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
                const tooltip = d3.select("#tooltip");
    
                // const xScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[xCol]))
                //     .range([0, this.size]);
                // const yScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[yCol]))
                //     .range([this.size, 0]);
    
                cellGroup
                    .selectAll("circle")
                    .data(data)
                    .join("circle")
                    .attr("cx", (d) => this.xScale(d[xCol]))
                    .attr("cy", (d) => this.yScale(d[yCol]))
                    .attr("r", 3)
                    .attr("fill", "steelblue")
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
                        d3.select(this).attr("fill", "steelblue");
                        tooltip.style("display", "none");
                    });
    
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
    
            const brush = d3.brush()
                .extent([[0, 0], [this.size, this.size]]) 
                .on("start brush end", (event) => handleBrush(event, this.xScale, this.yScale, xCol, yCol));  

            if (i === j) {
                
                const data = givenData.select(["id", xCol]).objects();
                const histogramGenerator = d3.histogram()
                    .domain([d3.min(data, (d) => d[xCol]), d3.max(data, (d) => d[xCol]) + 1])
                    .thresholds(10);

                const histData = histogramGenerator(data.map(d => d[xCol])).map(bin => {
                    return {
                        x0: bin.x0,
                        x1: bin.x1,
                        length: bin.length,
                        ids: data.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.id)
                    };
                });
    
                const tooltip = d3.select("#tooltip");
    
                const xScale = d3
                    .scaleLinear()
                    .domain([d3.min(data, (d) => d[xCol]), d3.max(data, (d) => d[xCol])])
                    .range([0, this.size]);
    
                const yScale = d3.scaleLinear().domain([0, d3.max(histData, (d) => d.length)]).range([this.size, 0]);    
    
                const bars = cellGroup.selectAll("rect")
                    .data(histData)
                    .join("rect")
                    .attr("x", (d) => xScale(d.x0))
                    .attr("width", (d) => xScale(d.x1) - xScale(d.x0))
                    .attr("y", (d) => yScale(d.length))
                    .attr("height", (d) => this.size - yScale(d.length))
                    .attr("fill", d => {
                        const isSelected = d.ids.some(id => this.selectedPoints.some(p => p.id === id));
                        return isSelected ? "red" : "steelblue";
                    })  
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

                // bars.on('click', function(event, d) {

                //     console.log(xCol);

                //     bars.attr('fill', 'steelblue');
                
                //     d3.select(this)
                //         .attr('fill', 'red');
                
                //     console.log('Selected value: ', d.x0);
                //     barX0 = d.x0;
                //     barX1 = d.x1;
                //     selectedBar = xCol;
                // });
            
                cellGroup
                    .append("g")
                    .attr("transform", `translate(0, ${this.size})`)
                    .call(d3.axisBottom(xScale));
    
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
                const tooltip = d3.select("#tooltip");
    
                // const xScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[xCol]))
                //     .range([0, this.size]);
                // const yScale = d3
                //     .scaleLinear()
                //     .domain(d3.extent(data, (d) => d[yCol]))
                //     .range([this.size, 0]);

                const brush = d3.brush()
                    .extent([[-10, -10], [this.size + 10, this.size + 10]]) 
                    .on("end", (event) => handleBrush(event, this.xScale, this.yScale, xCol, yCol));  
                    
                cellGroup
                    .selectAll("circle")
                    .data(data)
                    .join("circle")
                    .attr("cx", (d) => this.xScale(d[xCol]))
                    .attr("cy", (d) => this.yScale(d[yCol]))
                    .attr("r", 3)
                    .attr("fill", (d) => {
                        const isSelected = this.selectedPoints.some(p => 
                            p[xCol] === d[xCol] && p[yCol] === d[yCol]
                        );
                        return isSelected ? "red" : "steelblue"; 
                    })                    
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
                    //     d3.select(this).attr("fill", "steelblue");
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
            }
            });
        });
    }

}

