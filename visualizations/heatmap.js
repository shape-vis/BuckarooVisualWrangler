

/**
 * Plots heatmaps on the off-diagonals. Heatmaps are colored by a gradient colorscale based on frequency. A bin is colored an error color if it contains a data point with
 * that error. If group by is active, the bins are colored by group. 
 * Plots can be 4 categories: 
 *      both x & y are numeric, 
 *      x is categorical & y is numeric, 
 *      x is numeric & y is categorical,
 *      both x & y are categorical.
 * These cases are all handled separately. Within each case, there are two options: 
 *      Group by is active or group by is not active. 
 * These two cases are handled separately.
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
 * @param {*} handleHeatmapClick Handles user clicks on heatmap bins.
 */
export function draw(model, view, cellGroup, svg, i, j, givenData, xCol, yCol, groupByAttribute, selectionEnabled, animate, handleHeatmapClick){

    let histData = query_histogram2d(givenData.select(["ID", xCol, yCol]).objects(), model.getColumnErrors(), xCol, yCol);

    const uniqueGroups = [...new Set(givenData.objects().map(d => d[groupByAttribute]))];

    const columnErrors = model.getColumnErrors();

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

    let {xIsNumeric, yIsNumeric, numericData, nonNumericXData, nonNumericYData, nonNumericData, combinedData, uniqueXCategories, uniqueYCategories, categorySpace, numericSpace, xIsNumericMajority, yIsNumericMajority} = splitData(data, xCol, yCol);

    const numericXValues = nonNumericYData.map(d => d[xCol]).filter(v => !isNaN(v));
    const numericYValues = nonNumericXData.map(d => d[yCol]).filter(v => !isNaN(v));

    const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10;
    const yPosition = view.topMargin + i * (view.size + view.yPadding) + view.size / 2;

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

    let xCategories = [...xBinLabels.map(String), ...uniqueXStringBins].filter((v, i, self) => self.indexOf(v) === i); 
    let yCategories = [...yBinLabels.map(String), ...uniqueYStringBins].filter((v, i, self) => self.indexOf(v) === i); 

    const tooltip = d3.select("#tooltip");
    const self = this;
    let rect = null;

    /// All numeric plot ///
    if(xIsNumericMajority && yIsNumericMajority)
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

        if(groupByAttribute){       // Group by is activated
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

            xScale = d3.scaleBand().domain(xCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(yCategories).range([view.size, 0]).padding(0.05);

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
                            .attr("fill", d => {
                                if (!self.viewGroupsButton){
                                    return getFillColorHeatmap(d, group, xCol, yCol, columnErrors, self.errorColors, self.selectedPoints); 
                                }
                                return groupColorScale(group);
                            })
                            .attr("stroke", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? "black" : (view.viewGroupsButton ? "none" : "white");
                            })
                            .attr("stroke-width", (d) => {
                                const isSelected = d.d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? 2 : 0.5;
                            })
                            .attr("opacity", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                else {return 1;}
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
                                const group = view.getAttribute("data-group");                                    
                                handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                            });

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

            xScale = d3.scaleBand().domain(xCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(yCategories).range([view.size, 0]).padding(0.05);
            colorScale = d3.scaleSequential(d3.interpolateBlues)
                .domain([0, d3.max(heatmapData, d => d.value)]);
    
            rect = cellGroup.selectAll("rect")
                .data(heatmapData)
                .join("rect")
                .attr("x", d => xScale(d.x))
                .attr("y", d => yScale(d.y))
                .attr("opacity", 0.8)
                .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, view.errorColors, colorScale, view.selectedPoints))
                .attr("stroke", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? "red" : "gray";
                })
                .attr("stroke-width", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? 1 : 0.5
                });
        }
    }
    /// Non numeric X plot ///
    else if(!xIsNumericMajority && yIsNumericMajority) // xCol is cat. yCol is num.
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

            xScale = d3.scaleBand().domain(uniqueXCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(yCategories).range([view.size, 0]).padding(0.05);

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
                            .attr("fill", d => {
                                if (!self.viewGroupsButton){
                                    return getFillColorHeatmap(d, group, xCol, yCol, columnErrors, self.errorColors, self.selectedPoints); 
                                }
                                return groupColorScale(group);
                            })
                            .attr("stroke", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? "black" : (view.viewGroupsButton ? "none" : "white");
                            })
                            .attr("stroke-width", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? 2 : 0.5;
                            })
                            .attr("opacity", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                else {return 1;}
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
                                const group = view.getAttribute("data-group");                                    
                                handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                            });

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

            xScale = d3.scaleBand().domain(uniqueXCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(yCategories).range([view.size, 0]).padding(0.05);
            colorScale = d3.scaleSequential(d3.interpolateBlues)
                .domain([0, d3.max(heatmapData, d => d.value)]);

            rect = cellGroup.selectAll("rect")
                .data(heatmapData)
                .join("rect")
                .attr("x", d => xScale(d.x))
                .attr("y", d => yScale(d.y))
                .attr('opactiy', 0.8)
                .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, view.errorColors, colorScale, view.selectedPoints))
                .attr("stroke", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? "red" : "gray";
                })
                .attr("stroke-width", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? 1 : 0.5
                });
        }

        cellGroup.append("g")
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
    else if(xIsNumericMajority && !yIsNumericMajority) // xCol is num. yCol is cat.
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

            xScale = d3.scaleBand().domain(xCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(uniqueYCategories).range([view.size, 0]).padding(0.05);

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
                            .attr("fill", d => {
                                if (!self.viewGroupsButton){
                                    return getFillColorHeatmap(d, group, xCol, yCol, columnErrors, self.errorColors, self.selectedPoints); 
                                }
                                return groupColorScale(group);
                            })
                            .attr("stroke", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? "black" : (view.viewGroupsButton ? "none" : "white");
                            })
                            .attr("stroke-width", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? 2 : 0.5;
                            })
                            .attr("opacity", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                else {return 1;}
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
                                const group = view.getAttribute("data-group");                                    
                                handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                            });

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

            xScale = d3.scaleBand().domain(xCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(uniqueYCategories).range([view.size, 0]).padding(0.05);
            colorScale = d3.scaleSequential(d3.interpolateBlues)
                .domain([0, d3.max(heatmapData, d => d.value)]);

            rect = cellGroup.selectAll("rect")
                .data(heatmapData)
                .join("rect")
                .attr("x", d => xScale(d.x))
                .attr("y", d => yScale(d.y))
                .attr("opacity", 0.8)
                .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, view.errorColors, colorScale, view.selectedPoints))   
                .attr("stroke", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? "red" : "gray";
                })
                .attr("stroke-width", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? 1 : 0.5
                });
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

            xScale = d3.scaleBand().domain(uniqueXCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(uniqueYCategories).range([view.size, 0]).padding(0.05);

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
                            .attr("fill", d => {
                                if (!self.viewGroupsButton){
                                    return getFillColorHeatmap(d, group, xCol, yCol, columnErrors, self.errorColors, self.selectedPoints); 
                                }
                                return groupColorScale(group);
                            })
                            .attr("stroke", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? "black" : (view.viewGroupsButton ? "none" : "white");
                            })
                            .attr("stroke-width", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));                            
                                return isSelected ? 2 : 0.5;
                            })
                            .attr("opacity", (d) => {
                                const isSelected = d.ids[group].some(ID => self.selectedPoints.some(p => p.ID === ID));
                                if(selectionEnabled) {return isSelected ? 1 : 0.7;}
                                else {return 1;}
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
                                const group = view.getAttribute("data-group");                                    
                                handleHeatmapClick(event, d, xCol, yCol, groupByAttribute, group);
                            });

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

            xScale = d3.scaleBand().domain(uniqueXCategories).range([0, view.size]).padding(0.05);
            yScale = d3.scaleBand().domain(uniqueYCategories).range([view.size, 0]).padding(0.05);
            
            colorScale = d3.scaleSequential(d3.interpolateBlues)
                .domain([0, d3.max(heatmapData, d => d.value)]);
    
            rect = cellGroup.selectAll("rect")
                .data(heatmapData)
                .join("rect")
                .attr("x", d => xScale(d.x))
                .attr("y", d => yScale(d.y))
                .attr("opacity", 0.8)
                .attr("fill", d => getFillColorHeatmapNoGroupby(d, xCol, yCol, columnErrors, view.errorColors, colorScale, view.selectedPoints)) 
                .attr("stroke", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? "red" : "gray";
                })
                .attr("stroke-width", (d) => {
                    const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
                    return isPredicated ? 1 : 0.5
                });             
        }
        
        cellGroup.append("g")
            .attr("transform", `translate(0, ${view.size})`)
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

        const legendHeight = view.size;
        const legendWidth = 10;
        const legendX = view.size + 5; 
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

    const xText = svg.append("text")
        .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2)
        .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding) - 25)
        .style("text-anchor", "middle")
        .text(truncateText(xCol, 30));
    xText.append("title").text(xCol);  // Full column name on hover

    const yText = svg.append("text")
        .attr("x", xPosition)
        .attr("y", yPosition - 20)
        .style("text-anchor", "middle")
        .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`)
        .text(truncateText(yCol));
    yText.append("title").text(yCol);  // Full column name on hover
}

