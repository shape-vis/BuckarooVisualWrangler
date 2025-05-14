

/**
 * Plots scatterplots on the off-diagonals when the scatterplot icon is selected. A point is colored an error color if it contains a data point with that error. If group by 
 * is active, the points are colored by group. 
 * Plots can be 4 categories: 
 *      both x & y are numeric, 
 *      x is categorical & y is numeric, 
 *      x is numeric & y is categorical,
 *      both x & y are categorical.
 * Group by is handled within the "fill" for each circle.
 * @param {*} cellGroup The DOM element for the cell.
 * @param {*} svg The overall matrix svg.
 * @param {*} i Which row in the matrix we are in.
 * @param {*} j Which column in the matrix we are in.
 * @param {*} givenData Data to visualize.
 * @param {*} xCol The x attribute/column.
 * @param {*} yCol The y attribute/column.
 * @param {*} groupByAttribute If active, the user-selected attribute to group by.
 * @param {*} selectionEnabled If true, the user can click on bins in the visualization to select.
 * @param {*} animate If true, the plots should have transitions.
 * @param {*} handleHeatmapClick Given to pass around. 
 */
export function draw(model, view, cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick){
    const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

    const columnErrors = model.getColumnErrors();

    const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(uniqueGroups);

    let data = [];

    if(groupByAttribute)
    {
        data = givenData.select(["ID", xCol, yCol, groupByAttribute]).objects(); 
    }
    else{
        data = givenData.select(["ID", xCol, yCol]).objects();
    }

    let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace, xIsNumericMajority, yIsNumericMajority} = splitData(data, xCol, yCol);

    const numericXValues = nonNumericYData.map(d => d[xCol]).filter(v => !isNaN(v));
    const numericYValues = nonNumericXData.map(d => d[yCol]).filter(v => !isNaN(v));
    const meanX = d3.mean(numericXValues);
    const stdDevX = d3.deviation(numericXValues);
    const meanY = d3.mean(numericYValues);
    const stdDevY = d3.deviation(numericYValues);

    /// All numeric plot ///
    if(xIsNumericMajority && yIsNumericMajority)
    {
        const xScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(numericData, d => d[xCol])), d3.max(numericData, d => d[xCol]) + 1])
            .range([0, numericSpace]);

        const xTickValues = xScale.ticks(); 
        const xTickSpacing = xScale(xTickValues[1]) - view.xScale(xTickValues[0]); 

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

        const isPredicated = (d) => view.predicatePoints.some(p => 
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
            .attr("fill", d => {
                if (groupByAttribute) {
                    return colorScale(d[groupByAttribute]);     // Group by is active
                } else {
                    return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale);     // No group by
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
                    .attr("r", d => (d.type.includes("nan") ? 4 : 3)) 
                    .attr("opacity", 0.6);
            } else{
                circles.attr("r", d => (d.type.includes("nan") ? 4 : 3))
                    .attr("opacity", 0.6);
            }  
            circles.on("mouseover", function(event, d) {
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
        
        const xText = svg.append("text")
            .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2)
            .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding) - categorySpace  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
            .style("text-anchor", "middle")
            .text(truncateText(xCol, 30));
        xText.append("title").text(xCol);  // Full column name on hover

        const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10; 
        const yPosition = (view.topMargin + i * (view.size + view.yPadding) + view.size / 2) - categorySpace; 
        
        const yText = svg.append("text")
            .attr("x", xPosition) 
            .attr("y", yPosition - 20) 
            .style("text-anchor", "middle")
            .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
            .text(truncateText(yCol));
        yText.append("title").text(yCol);  // Full column name on hover
    }

    /// Non numeric X plot ///
    else if(!xIsNumericMajority && yIsNumericMajority) // xCol is cat. yCol is num.
    {
        uniqueXCategories = uniqueXCategories.slice(1);
        uniqueYCategories = uniqueYCategories.slice(1);
        uniqueXCategories = sortCategories(uniqueXCategories);
        uniqueYCategories = sortCategories(uniqueYCategories);

        const xScale = d3.scalePoint()
            .domain(uniqueXCategories)
            .range([0, view.size]);

        const xTickValues = xScale.step(); 
        const xTickSpacing = xScale(xTickValues[1]) - view.xScale(xTickValues[0]); 
        
        const yScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(nonNumericXData, d => d[yCol])), d3.max(nonNumericXData, d => d[yCol]) + 1])
            .range([view.size, 0]);

        const categoricalYStart = yScale.range()[1] - 10;
        const categoricalYScale = d3.scaleOrdinal()
            .domain(uniqueYCategories)
            .range(uniqueYCategories.length > 0 
                ? [...Array(uniqueYCategories.length).keys()].map(i => categoricalYStart - (i * ((xTickSpacing || 5) + 5)))
                : [0]); 
            
        const tooltip = d3.select("#tooltip"); 

        const isPredicated = (d) => view.predicatePoints.some(p => 
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
            .attr("fill", d => {
                if (groupByAttribute) {     // Group by is active
                    if (!view.viewGroupsButton){
                        return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale);    
                    }
                    return colorScale(d[groupByAttribute]);
                } else {
                    return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale);     // No group by
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
                .attr("r", d => (d.type === "nan-y" ? 4 : 3)) 
                .attr("opacity", 0.6);
        } else{
            circles.attr("r", d => (d.type === "nan-y" ? 4 : 3))
                .attr("opacity", 0.6);
        }  
        circles.on("mouseover", function(event, d) {
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
                tooltip.style("display", "none");
            });

        cellGroup
            .append("g")
            .attr("transform", `translate(0, ${view.size})`)
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
                        const [min, max] = d.split("-").map(Number);
                        return `${d3.format(".3s")(min)}-${d3.format(".3s")(max)}`;
                    } 
                    return d;
                }                    
                return d3.format(".3s")(d);  
            }))
                .selectAll("text")
                .style("font-size", "8px");

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
        
        const xText = svg.append("text")
            .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2)
            .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding)  - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
            .style("text-anchor", "middle")
            .text(truncateText(xCol, 30));
        xText.append("title").text(xCol);  // Full column name on hover

        const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10; 
        const yPosition = (view.topMargin + i * (view.size + view.yPadding) + view.size / 2); 
        
        const yText = svg.append("text")
            .attr("x", xPosition) 
            .attr("y", yPosition - 20) 
            .style("text-anchor", "middle")
            .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
            .text(truncateText(yCol));
        yText.append("title").text(yCol);  // Full column name on hover        
    }

    /// Non numeric Y plot ///
    else if(xIsNumericMajority && !yIsNumericMajority) // xCol is num. yCol is cat.
    {
        uniqueYCategories = uniqueYCategories.slice(1);
        uniqueXCategories = uniqueXCategories.slice(1);
        uniqueYCategories = sortCategories(uniqueYCategories);
        uniqueXCategories = sortCategories(uniqueXCategories);

        const xScale = d3.scaleLinear()
            .domain([Math.min(0, d3.min(nonNumericYData, d => d[xCol])), d3.max(nonNumericYData, d => d[xCol]) + 1])
            .range([0, view.size]);

        const xTickValues = xScale.ticks(); 
        const xTickSpacing = xScale(xTickValues[1]) - view.xScale(xTickValues[0]); 

        const categoricalXStart = xScale.range()[1] + 10;
        const categoricalXScale = d3.scaleOrdinal()
            .domain(uniqueXCategories)
            .range(uniqueXCategories.length > 0 
                ? [...Array(uniqueXCategories.length).keys()].map(i => categoricalXStart + (i * ((xTickSpacing || 5) + 5)))
                : [0]); 
        
        const yScale = d3.scalePoint()
            .domain(uniqueYCategories)
            .range([view.size, 0]);

        const tooltip = d3.select("#tooltip"); 

        const isPredicated = (d) => view.predicatePoints.some(p => 
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
            .attr("fill", d => {
                if (groupByAttribute) {     // Group by is active
                    if (!view.viewGroupsButton){
                        return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale); 
                    }
                    return colorScale(d[groupByAttribute]);
                } else {
                    return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale);     // No group by
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
                .attr("r", d => (d.type === "nan-x" ? 4 : 3)) 
                .attr("opacity", 0.6);
        } else{
            circles.attr("r", d => (d.type === "nan-x" ? 4 : 3))
                .attr("opacity", 0.6);
        }  
        circles.on("mouseover", function(event, d) {
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
                tooltip.style("display", "none");
            });
        
        cellGroup.append("g")
            .attr("transform", `translate(0, ${view.size})`)
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

        if (uniqueXCategories.length > 0) {
        cellGroup.append("g")
            .attr("transform", `translate(0, ${view.size})`)
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

        const xText = svg.append("text")
            .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2)
            .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding) - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
            .style("text-anchor", "middle")
            .text(truncateText(xCol, 30));
        xText.append("title").text(xCol);  // Full column name on hover

        const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10; 
        const yPosition = (view.topMargin + i * (view.size + view.yPadding) + view.size / 2); 
        
        const yText = svg.append("text")
            .attr("x", xPosition) 
            .attr("y", yPosition - 20) 
            .style("text-anchor", "middle")
            .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
            .text(truncateText(yCol));
        yText.append("title").text(yCol);  // Full column name on hover        
    }

    /// All non numeric plot ///
    else{   
        uniqueXCategories = uniqueXCategories.slice(1);
        uniqueYCategories = uniqueYCategories.slice(1);
        uniqueXCategories = sortCategories(uniqueXCategories);
        uniqueYCategories = sortCategories(uniqueYCategories);

        const xScale = d3.scalePoint()
            .domain(uniqueXCategories)
            .range([0, view.size]);
        
        const yScale = d3.scalePoint()
            .domain(uniqueYCategories)
            .range([view.size, 0]);

        const tooltip = d3.select("#tooltip"); 

        const isPredicated = (d) => view.predicatePoints.some(p => 
            (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
            (p[xCol] === d[xCol]) &&
            (p[yCol] === d[yCol])
        );

        const circles = cellGroup.selectAll("circle")
            .data(combinedData)
            .join("circle")
            .attr("cx", d => xScale(d[xCol]))
            .attr("cy", d => yScale(d[yCol]))
            .attr("fill", d => {
                if (groupByAttribute) {     // Group by is active
                    if (!view.viewGroupsButton){
                        return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale); 
                    }
                    return colorScale(d[groupByAttribute]);
                } else {
                    return getFillColorScatter(d, xCol, yCol, columnErrors, view.errorColors, view.selectedPoints, colorScale);     // No group by
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
                tooltip.style("display", "none");
            });

        cellGroup
            .append("g")
            .attr("transform", `translate(0, ${view.size})`)
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

        const xText = svg.append("text")
            .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2)
            .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding) - 25) // 30 + [1,2,3] * ([120,140] + 60) - 20
            .style("text-anchor", "middle")
            .text(truncateText(xCol, 30));
        xText.append("title").text(xCol);  // Full column name on hover

        const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10; 
        const yPosition = (view.topMargin + i * (view.size + view.yPadding) + view.size / 2); 
        
        const yText = svg.append("text")
            .attr("x", xPosition) 
            .attr("y", yPosition - 20) 
            .style("text-anchor", "middle")
            .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
            .text(truncateText(yCol));
        yText.append("title").text(yCol);  // Full column name on hover
    }        
}

