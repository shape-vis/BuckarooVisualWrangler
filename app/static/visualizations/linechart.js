
/**
 * Plots line charts on the off-diagonals when the line chart icon is selected. A line is colored an error color if it contains a data point with that error. If group by 
 * is active, the lines are colored by group. 
 * Plots can be 4 categories: 
 *      both x & y are numeric, 
 *      x is categorical & y is numeric, 
 *      x is numeric & y is categorical,
 *      both x & y are categorical.
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
export function draw(model, view, givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick) {
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

    let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace, xIsNumericMajority, yIsNumericMajority} = splitData(data, xCol, yCol);

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

        const isPredicated = (d) => view.predicatePoints.some(p => 
            (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
            (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
            (p[yCol] === d[yCol] || isNaN(d[yCol]))
        );

        if(groupByAttribute){       // Group by is active
            groupedData = d3.group(combinedData, d => d[groupByAttribute]);
            groupedData.forEach((groupArray, key) => {
                const path = cellGroup.append("path")
                    .datum(groupArray)
                    .attr("class", "line")
                    .attr("d", line)
                    .attr("stroke", colorScale(key))
                    .attr("fill", "none")
                    .attr("stroke-width", 2)
                    .attr("stroke-dasharray", function() { return view.getTotalLength(); }) 
                    .attr("stroke-dashoffset", function() { return view.getTotalLength(); }) 

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
        else{       // No group by
            const path = cellGroup.append("path")
                .datum(combinedData)
                .attr("fill", "none")
                .attr("stroke", d => isPredicated(d) ? "red" : "steelblue")
                .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                .attr("d", line)
                .attr("stroke-dasharray", function() { return view.getTotalLength(); })
                .attr("stroke-dashoffset", function() { return view.getTotalLength(); });

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

        const isPredicated = (d) => view.predicatePoints.some(p => 
            (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
            (p[xCol] === d[xCol]) &&
            (p[yCol] === d[yCol] || isNaN(d[yCol]))
        );

        if(groupByAttribute){       // Group by is active
            groupedData = d3.group(combinedData, d => d[groupByAttribute]);
            groupedData.forEach((groupArray, key) => {
                const path = cellGroup.append("path")
                    .datum(groupArray)
                    .attr("class", "line")
                    .attr("d", line)
                    .attr("stroke", colorScale(key))
                    .attr("fill", "none")
                    .attr("stroke-width", 2)
                    .attr("stroke-dasharray", function() { return view.getTotalLength(); }) 
                    .attr("stroke-dashoffset", function() { return view.getTotalLength(); }) 

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
        else{       // No group by
            const path = cellGroup.append("path")
                .datum(combinedData)
                .attr("fill", "none")
                // .attr("stroke", "steelblue")
                // .attr("stroke-width", 2)
                .attr("stroke", d => isPredicated(d) ? "red" : "steelblue")
                .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                .attr("d", line)
                .attr("stroke-dasharray", function() { return view.getTotalLength(); })
                .attr("stroke-dashoffset", function() { return view.getTotalLength(); });

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
            .attr("transform", `translate(0, ${view.size})`)
            .call(d3.axisBottom(xScale))
            .selectAll("text")
            .style("text-anchor", "end") 
            .attr("transform", "rotate(-45)") 
            .style("font-size", "8px")
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

        const isPredicated = (d) => view.predicatePoints.some(p => 
            (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
            (p[xCol] === d[xCol] || isNaN(d[xCol])) &&
            (p[yCol] === d[yCol])
        );

        if(groupByAttribute){       // Group by is active
            groupedData = d3.group(combinedData, d => d[groupByAttribute]);
            groupedData.forEach((groupArray, key) => {
                const path = cellGroup.append("path")
                    .datum(groupArray)
                    .attr("class", "line")
                    .attr("d", line)
                    .attr("stroke", colorScale(key))
                    .attr("fill", "none")
                    .attr("stroke-width", 2)
                    .attr("stroke-dasharray", function() { return view.getTotalLength(); }) 
                    .attr("stroke-dashoffset", function() { return view.getTotalLength(); }) 

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
        else{       // No group by
            const path = cellGroup.append("path")
                .datum(combinedData)
                .attr("fill", "none")
                .attr("stroke", d => isPredicated(d) ? "red" : "steelblue")
                .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                .attr("d", line)
                .attr("stroke-dasharray", function() { return view.getTotalLength(); })
                .attr("stroke-dashoffset", function() { return view.getTotalLength(); });

            if (animate) {
                path.transition()
                    .duration(800)
                    .ease(d3.easeLinear)
                    .attr("stroke-dashoffset", 0);
            } else{
                path.attr("stroke-dashoffset", 0);
            }
        }

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
            .range([0, view.size]);
        
        const yScale = d3.scalePoint()
            .domain(uniqueYCategories)
            .range([view.size, 0]);

        combinedData.sort((a, b) => {
            return uniqueXCategories.indexOf(a[xCol]) - uniqueXCategories.indexOf(b[xCol]);
        });

        const line = d3.line()
                        .x(d => {
                                return xScale(d[xCol]);
                        })
                        .y(d => {
                                return yScale(d[yCol]); 
                        })
                        .curve(d3.curveMonotoneX);

        let groupedData;

        const isPredicated = (d) => view.predicatePoints.some(p => 
            (isNaN(p[xCol]) === isNaN(d[xCol])) && (isNaN(p[yCol]) === isNaN(d[yCol])) && 
            (p[xCol] === d[xCol]) &&
            (p[yCol] === d[yCol])
        );

        if(groupByAttribute){       // Group by is active
            groupedData = d3.group(combinedData, d => d[groupByAttribute]);
            groupedData.forEach((groupArray, key) => {
                const path = cellGroup.append("path")
                    .datum(groupArray)
                    .attr("class", "line")
                    .attr("d", line)
                    .attr("stroke", colorScale(key))
                    .attr("fill", "none")
                    .attr("stroke-width", 2)
                    .attr("stroke-dasharray", function() { return view.getTotalLength(); }) 
                    .attr("stroke-dashoffset", function() { return view.getTotalLength(); }) 

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
        else{       // No group by
            const path = cellGroup.append("path")
                .datum(combinedData)
                .attr("fill", "none")
                .attr("stroke", d => {
                    let result = isPredicated(d);
                    console.log(`isPredicated(${d}):`, result);
                    return result ? "red" : "steelblue";
                })
                .attr("stroke-width", d => isPredicated(d) ? 3 : 2)
                .attr("d", line)
                .attr("stroke-dasharray", function() { return view.getTotalLength(); })
                .attr("stroke-dashoffset", function() { return view.getTotalLength(); });

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
            .attr("transform", `translate(0, ${view.size})`)
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

    d3.select(view.parentNode).selectAll(".heatmap-button, .scatterplot-button").classed("active", false);

    const heatMapViewButton = cellGroup.append("image")
    .attr("class", "heatmap-button")
    .attr("x", -110)  
    .attr("y", -60)   
    .attr("width", 45) 
    .attr("height", 25)
    .attr("xlink:href", "/static/images/icons/heatmap.png")
    .attr("cursor", "pointer")
    .on("click", () => view.restoreHeatmap(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

    const scatterViewButton = cellGroup.append("image")
        .attr("class", "scatterplot-button")
        .attr("x", -110)  
        .attr("y", -35)   
        .attr("width", 45) 
        .attr("height", 25)
        .attr("xlink:href", "/static/images/icons/scatterplot.png")
        .attr("cursor", "pointer")
        .on("click", () => view.restoreScatterplot(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));

    const lineViewButton = cellGroup.append("image")
        .attr("class", "linechart-button active")
        .attr("x", -110)  
        .attr("y", -10)   
        .attr("width", 45) 
        .attr("height", 25)
        .attr("xlink:href", "/static/images/icons/linechart.png")
        .attr("cursor", "pointer")
        .on("click", () => view.switchToLineChart(givenData, svg, xCol, yCol, cellID, groupByAttribute, selectionEnabled, animate, handleHeatmapClick));
}


