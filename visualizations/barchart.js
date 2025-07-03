

export function draw(view, data, groupByAttribute, cellGroup, columnErrors, svg, i, j, animate, selectionEnabled, handleBarClick, xCol) {

    let histData = query_histogram1d(data, columnErrors, xCol);

    // scales
    const xScale = d3.scaleBand()
        .domain(histData.map(d => d.bin))
        .range([0,view.size])
       .padding(0.2);

    const yScale = d3.scaleLinear()
        //.domain([0, d3.max(data, d => d.apples + d.oranges + d.grapes)]).nice()
        .domain([0, d3.max(histData, d => d.length)]).nice()
        .range([view.size, 0]);

    view.errorColors['none'] = "steelblue";
    const colorScale = d3.scaleOrdinal().domain(Object.keys(view.errorColors)).range(Object.values(view.errorColors));
    

    // Draw bars
    let bars = cellGroup.selectAll("g.series")
        .data(histData)
        .join("g")
        .attr("class", "series")
        .selectAll("rect")
            .data(d => {console.log(d); return d.counts})
            .join("rect")
            .attr("x", d => {console.log(xScale(d.bin), yScale(d.value)); return xScale(d.bin)})
            .attr("y", d => yScale(d.value))
            .attr("height", d => yScale(0) - yScale(d.value))
            .attr("width", xScale.bandwidth())
            .attr("fill", d => colorScale(d.name))

    // Draw axes
    cellGroup.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

    cellGroup
            .append("g")
            .attr("transform", `translate(0, ${view.size})`)
            // .call(d3.axisBottom(xScale).tickFormat(d3.format(".2s")))
            .call(d3.axisBottom(xScale))
            .selectAll("text") 
            .attr("class", "bottom-axis-text")
            // .style("text-anchor", "end") 
            // .style("font-size", "8px")
            .attr("dx", "-0.5em") 
            .attr("dy", "0.5em")  
            // .attr("transform", "rotate(-45)")
            .append("title")  
            .text(d => d);
        

    const tooltip = d3.select("#tooltip");
    bars.on("mouseover", function(event, d) {
            d3.select(this).attr("opacity", 0.5);
            tooltip.style("display", "block")
                // .html(`<strong>Bin Range:</strong> ${d.x0.toFixed(2)} - ${d.x1.toFixed(2)}<br><strong>Count: </strong>${d.length}`)
                .html(`<strong>Bin Range:</strong> ${d.bin}<br><strong>Error: </strong>${d.name}<br><strong>Count: </strong>${d.value}`)
                .style("left", `${event.pageX + 10}px`)
                .style("top", `${event.pageY + 10}px`);
        })
        .on("mousemove", function(event) {
            tooltip.style("left", `${event.pageX + 10}px`)
                .style("top", `${event.pageY + 10}px`);
        })
        .on("mouseout", function() {
            d3.select(this).attr("opacity", 1);
            tooltip.style("display", "none");
        })
        // .attr("data-ids", d => d.ids.join(","))
        .on("click", function (event, d) {
            if (!selectionEnabled) return;
            handleBarClick(event, d, xCol, groupByAttribute)
        });


    // // X axis
    // svg.append("g")
    //     .attr("transform", `translate(0,${height - margin.bottom})`)
    //     .call(d3.axisBottom(x));

    // // Y axis
    // svg.append("g")
    //     .attr("transform", `translate(${margin.left},0)`)
    //     .call(d3.axisLeft(y));

    // const numericData = data.filter(d => 
    //     typeof d[xCol] === "number" && !isNaN(d[xCol])
    // );
    
    // const nonNumericData = data.filter(d => 
    //     typeof d[xCol] !== "number" || isNaN(d[xCol])
    // ).map(d => ({
    //     ...d,
    //     [xCol]: typeof d[xCol] === "boolean" ? String(d[xCol]) : d[xCol] 
    // }));

    // const isNumericMajority = numericData.length >= nonNumericData.length;

    // const groupedCategories = d3.group(nonNumericData, d => String(d[xCol]));

    // let uniqueCategories;
    
    // if (numericData.length === data.length)
    // {
    //     uniqueCategories = [];
    // }else if (isNumericMajority){

    //     uniqueCategories = [...[...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
    // }
    // else{
    //     const mismatchNums = numericData.map(d => String(d[xCol]));
    //     uniqueCategories = [...[...mismatchNums, ...groupedCategories.keys()].filter(d => d !== "NaN").sort()]
    // }

    // const categorySpace = uniqueCategories.length * 20; 
    // const numericSpace = view.size - categorySpace; 
    // let categoricalScale = null;
    // const tooltip = d3.select("#tooltip");
    // let bars = null;
    // let yScale = null;
    
    // // Plot Numeric Data 
    // if (isNumericMajority)
    // {
    //     uniqueCategories = sortCategories(uniqueCategories);
    //     const xScale = d3.scaleLinear()
    //         .domain([d3.min(numericData, (d) => d[xCol]), d3.max(numericData, (d) => d[xCol]) + 1])
    //         .range([0, numericSpace]);
        
    //     const histogramGenerator = d3.histogram()
    //         .domain(xScale.domain())
    //         .thresholds(10);

    //     const bins = histogramGenerator(numericData.map(d => d[xCol]));

    //     const values = numericData.map(d => d[xCol]).filter(v => !isNaN(v));
    //     const mean = d3.mean(values);
    //     const stdDev = d3.deviation(values);

    //     // Data is grouped
    //     if (groupByAttribute) {
    //         const groups = Array.from(new Set(numericData.map(d => d[groupByAttribute])));
    //         const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(groups);
    
    //         const stackedData = bins.map(bin => {
    //             const binData = numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1);
    //             let obj = {
    //                 x0: bin.x0,
    //                 x1: bin.x1,
    //                 total: binData.length,
    //                 ids: binData.map(d => d.ID),
    //                 groupIDs: {}  
    //             };
    //             groups.forEach(g => {
    //                 const groupData = binData.filter(d => d[groupByAttribute] === g);
    //                 obj[g] = groupData.length;  
    //                 obj.groupIDs[g] = groupData.map(d => d.ID);
    //             });
    //             return obj;
    //         });
    
    //         const binWidth = xScale(bins[0].x1) - xScale(bins[0].x0);

    //         const categoricalStart = xScale.range()[1] + 10;

    //         categoricalScale = d3.scaleOrdinal()
    //             .domain(uniqueCategories)
    //             .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

    //         uniqueCategories.forEach(category => {
    //             const catData = nonNumericData.filter(d => String(d[xCol]) === category);
    //             let obj = {
    //                 x0: categoricalScale(category),
    //                 x1: categoricalScale(category) + binWidth,
    //                 group: null,
    //                 total: catData.length,
    //                 category: category,
    //                 ids: catData.map(d => d.ID),
    //                 groupIDs: {}   
    //             };
    //             groups.forEach(g => {
    //                 const groupData = catData.filter(d => d[groupByAttribute] === g);
    //                 obj[g] = groupData.length;  
    //                 obj.group = g;
    //                 obj.groupIDs[g] = groupData.map(d => d.ID);
    //             });
    //             stackedData.push(obj);
    //         });
    
    //         const yMax = d3.max(stackedData, d => d.total);
    //         yScale = d3.scaleLinear()
    //             .domain([0, yMax])
    //             .range([view.size, 0]);
    
    //         const stackGen = d3.stack().keys(groups);
    //         const series = stackGen(stackedData);
    
    //         bars = cellGroup.selectAll("g.series")
    //             .data(series)
    //             .join("g")
    //             .attr("class", "series")
    //             .attr("data-group", d => d.key)  
    //             .selectAll("rect")
    //             .data(d => {
    //                 d.forEach(item => item.group = d.key);  
    //                 return d;
    //             })
    //             .join("rect")
    //             .attr("fill", d => {
    //                 if (!view.viewGroupsButton){
    //                     return getFillColorNumeric(d, xCol, columnErrors, view.errorColors, view.selectedPoints); 
    //                 }
    //                 return d.data.category ? "gray" : colorScale(d.group);
    //             })
    //             .attr("stroke", (d) => {
    //                 const isSelected = d.data.groupIDs[d.group].some(ID => view.selectedPoints.some(p => p.ID === ID));                            
    //                 return isSelected ? "black" : (view.viewGroupsButton ? "none" : "white");
    //             })
    //             .attr("stroke-width", (d) => {
    //                 const isSelected = d.data.groupIDs[d.group].some(ID => view.selectedPoints.some(p => p.ID === ID));                            
    //                 return isSelected ? 2 : 0.5;
    //             })
    //             .attr("opacity", (d) => {
    //                 const isSelected = d.data.groupIDs[d.group].some(ID => view.selectedPoints.some(p => p.ID === ID));
    //                 if(selectionEnabled) {return isSelected ? 1 : 0.7;}
    //                 else {return 1;}
    //             })
    //             .attr("x", d => d.data.category ? categoricalScale(d.data.category) : xScale(d.data.x0))
    //             .attr("width", binWidth);
    //     }
    //     // No group by
    //     else{
    //         const histData = histogramGenerator(numericData.map(d => d[xCol])).map(bin => {
    //             return {
    //                 x0: bin.x0,
    //                 x1: bin.x1,
    //                 length: bin.length,
    //                 ids: numericData.filter(d => d[xCol] >= bin.x0 && d[xCol] < bin.x1).map(d => d.ID)
    //             };
    //         });

    //         const binWidth = xScale(histData[0].x1) - xScale(histData[0].x0);
    //         const categoricalStart = xScale.range()[1] + 10;

    //         categoricalScale = d3.scaleOrdinal()
    //             .domain(uniqueCategories)
    //             .range([...Array(uniqueCategories.length).keys()].map(i => categoricalStart + (i * binWidth))); 

    //         uniqueCategories.forEach(category => {
    //             histData.push({
    //                 x0: categoricalScale(category),
    //                 x1: categoricalScale(category) + binWidth,
    //                 length: nonNumericData.filter(d => String(d[xCol]) === category).length,
    //                 ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.ID),
    //                 category: category 
    //             });
    //         });

    //         yScale = d3.scaleLinear()
    //             .domain([0, d3.max(histData, (d) => d.length)])
    //             .range([view.size, 0]);
                                            
    //         bars = cellGroup.selectAll("rect")
    //             .data(histData)
    //             .join("rect")
    //             .attr("x", d => d.category ? categoricalScale(d.category) : xScale(d.x0))
    //             .attr("width", binWidth)
    //             .attr("fill", d => getFillColorNoGroupbyNumeric(d, xCol, columnErrors, view.errorColors, view.selectedPoints))
    //             .attr("stroke", (d) => {
    //                 const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
    //                 return isPredicated ? "red" : "none";
    //             })
    //             .attr("stroke-width", (d) => {
    //                 const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
    //                 return isPredicated ? 1 : 0
    //             })
    //             .attr("opacity", 0.8)
    //             .attr("data-ids", d => d.ids.join(","));   
    //     }
        

        // if (uniqueCategories.length > 0) {
        //     cellGroup.append("g")
        //         .attr("transform", `translate(10, ${view.size})`)
        //         .call(d3.axisBottom(categoricalScale))
        //         .selectAll("text")
        //         .attr("class", "bottom-axis-text")
        //         // .style("text-anchor", "end") 
        //         // .attr("transform", "rotate(-45)") 
        //         // .style("font-size", "8px")
        //         .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
        //         .append("title")  
        //         .text(d => d);
        // }

    //     const xText = svg
    //         .append("text")
    //         .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2) 
    //         .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding) - 25) 
    //         .style("text-anchor", "middle")
    //         .text(truncateText(xCol, 30));
    //     xText.append("title").text(xCol);  // Full column name on hover

    //     const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10; 
    //     const yPosition = (view.topMargin + i * (view.size + view.yPadding) + view.size / 2) - categorySpace; 
        
    //     svg
    //         .append("text")
    //         .attr("x", xPosition) 
    //         .attr("y", yPosition - 20) 
    //         .style("text-anchor", "middle")
    //         .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
    //         .text("count");
    // }
    // // Data is all categorical
    // else{   

    //     uniqueCategories = sortCategories(uniqueCategories);

    //     const xScale = d3.scaleBand()
    //         .domain(uniqueCategories)
    //         .range([0, view.size]);

    //     // Data is grouped
    //     if (groupByAttribute) {
    //         const groups = Array.from(new Set(nonNumericData.map(d => d[groupByAttribute])));
    //         const colorScale = d3.scaleOrdinal(d3.schemeCategory10).domain(groups);
            
    //         const stackedData = uniqueCategories.map(category => {
    //             const obj = {
    //                 category: category,
    //                 x0: xScale(category),
    //                 x1: xScale(category) + xScale.bandwidth(),
    //                 group: null,
    //                 total: 0, 
    //                 ids: [],  
    //                 groupIDs: {}
    //             };
    //             groups.forEach(g => {
    //                 const groupData = nonNumericData.filter(d => 
    //                     String(d[xCol]) === category && d[groupByAttribute] === g
    //                 );
                    
    //                 obj[g] = groupData.length;  
    //                 obj.groupIDs[g] = groupData.map(d => d.ID);
    //                 obj.group = g; 
    //                 obj.total += groupData.length; 
    //                 obj.ids.push(...groupData.map(d => d.ID)); 
    //             });
    //             return obj;
    //         });

    //         const yMax = d3.max(stackedData, d => groups.reduce((sum, g) => sum + d[g], 0));
    //         yScale = d3.scaleLinear().domain([0, yMax]).range([view.size, 0]);
            
    //         const stackGen = d3.stack().keys(groups);
    //         const series = stackGen(stackedData);
            
    //         bars = cellGroup.selectAll("g.series")
    //             .data(series)
    //             .join("g")
    //             .attr("class", "series")
    //             .attr("data-group", d => d.key)  
    //             .selectAll("rect")
    //             .data(d => {
    //                 d.forEach(item => item.group = d.key);  
    //                 return d;
    //             })
    //             .join("rect")
    //             .attr("fill", d => {
    //                 if (!view.viewGroupsButton){
    //                     return getFillColorCategorical(d, xCol, columnErrors, view.errorColors, view.selectedPoints); 
    //                 }
    //                 return colorScale(d.group);
    //             })
    //             .attr("stroke", (d) => {
    //                 const isSelected = d.data.groupIDs[d.group].some(ID => view.selectedPoints.some(p => p.ID === ID));                            
    //                 return isSelected ? "black" : (view.viewGroupsButton ? "none" : "white");
    //             })
    //             .attr("stroke-width", (d) => {
    //                 const isSelected = d.data.groupIDs[d.group].some(ID => view.selectedPoints.some(p => p.ID === ID));                            
    //                 return isSelected ? 2 : 0.5;
    //             })
    //             .attr("opacity", (d) => {
    //                 const isSelected = d.data.groupIDs[d.group].some(ID => view.selectedPoints.some(p => p.ID === ID));
    //                 if(selectionEnabled) {return isSelected ? 1 : 0.7;}
    //                 else {return 1;}
    //             })
    //             .attr("x", d => xScale(d.data.category))
    //             .attr("width", xScale.bandwidth());                          
    //     }
    //     // No group by
    //     else{
    //         const histData = [];

    //         uniqueCategories.forEach(category => {
    //             histData.push({
    //                 x0: xScale(category),
    //                 x1: xScale(category) + xScale.bandwidth(),
    //                 length: nonNumericData.filter(d => String(d[xCol]) === category).length,
    //                 ids: nonNumericData.filter(d => String(d[xCol]) === category).map(d => d.ID),
    //                 category: category 
    //             });
    //         });
            
    //         yScale = d3.scaleLinear()
    //             .domain([0, d3.max(histData, (d) => d.length)])
    //             .range([view.size, 0]);
            
    //         bars = cellGroup.selectAll("rect")
    //             .data(histData)
    //             .join("rect")
    //             .attr("x", d => xScale(d.category))
    //             .attr("width", xScale.bandwidth())
    //             .attr("fill", d => getFillColorNoGroupbyCategorical(d, xCol, columnErrors, view.errorColors, view.selectedPoints))
    //             .attr("stroke", (d) => {
    //                 const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
    //                 return isPredicated ? "red" : "none";
    //             })
    //             .attr("stroke-width", (d) => {
    //                 const isPredicated = d.ids.some(ID => view.predicatePoints.some(p => p.ID === ID));
    //                 return isPredicated ? 1 : 0
    //             })
    //             .attr("opacity", 0.8)
    //             .attr("data-ids", d => d.ids.join(","));
    //     }
        
    //     cellGroup
    //         .append("g")
    //         .attr("transform", `translate(0, ${view.size})`)
    //         .call(d3.axisBottom(xScale))
    //         .selectAll("text") 
    //         .attr("class", "bottom-axis-text")
    //         // .style("text-anchor", "end") 
    //         // .style("font-size", "8px")
    //         .attr("dx", "-0.5em") 
    //         .attr("dy", "0.5em")  
    //         // .attr("transform", "rotate(-45)")
    //         .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d)  
    //         .append("title")  
    //         .text(d => d);

    //     cellGroup.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");
            
    //     const xText = svg.append("text")
    //         .attr("x", view.leftMargin + j * (view.size + view.xPadding) + view.size / 2) 
    //         .attr("y", view.topMargin + (i + 1) * (view.size + view.yPadding) - 25) 
    //         .style("text-anchor", "middle")
    //         .text(truncateText(xCol, 30));
    //     xText.append("title").text(xCol);  // Full column name on hover

    //     const xPosition = view.leftMargin + j * (view.size + view.xPadding) - view.labelPadding - 10; 
    //     const yPosition = (view.topMargin + i * (view.size + view.yPadding) + view.size / 2); 
        
    //     svg.append("text")
    //         .attr("x", xPosition) 
    //         .attr("y", yPosition - 20) 
    //         .style("text-anchor", "middle")
    //         .attr("transform", `rotate(-90, ${xPosition}, ${yPosition})`) 
    //         .text("count");
    // }  
    
    // // Animation, tooltip, and handle bar clicks behavior varies if group by is on or not
    // if(groupByAttribute){
    //     if(animate){
    //         bars.attr("y", view.size)
    //         .attr("height", 0)
    //         .transition() 
    //         .duration(800)
    //         .ease(d3.easeCubicOut)
    //         .attr("y", d => yScale(d[1])) 
    //         .attr("height", d => yScale(d[0]) - yScale(d[1]));
    //     } else{
    //         bars.attr("y", d => yScale(d[1]))  
    //             .attr("height", d => yScale(d[0]) - yScale(d[1]));
    //     }
    //     bars.on("mouseover", function(event, d) {
    //         const group = d3.select(view.parentNode).datum().key;
    //         const count = d[1] - d[0];
    //         const totalCount = d.data.total;
    //         d3.select(this).attr("opacity", 0.5);
    //         tooltip.style("display", "block")
    //             .html(`<strong>Bin Range:</strong> ${d.data.x0.toFixed(2)} - ${d.data.x1.toFixed(2)}<br><strong>${group} Count:</strong> ${count}<br><strong>Total Bin Count:</strong> ${totalCount}`)
    //             .style("left", `${event.pageX + 10}px`)
    //             .style("top", `${event.pageY + 10}px`);
    //     })
    //     .on("mousemove", function(event) {
    //         tooltip.style("left", `${event.pageX + 10}px`)
    //             .style("top", `${event.pageY + 10}px`);
    //     })
    //     .on("mouseout", function() {
    //         const group = d3.select(view.parentNode).datum().key;
    //         d3.select(this).attr("opacity", 1);
    //         tooltip.style("display", "none");
    //     })
    //     .attr("data-ids", d => d.data.ids.join(","))
    //     .on("click", function (event, d) {
    //         if (!selectionEnabled) return;   
    //         const group = d3.select(view.parentNode).datum().key;  
    //         handleBarClick(event, d, xCol, groupByAttribute, group)
    //     });
    // }
    // else{
    //     if(animate){
    //         bars.attr("y", view.size)
    //             .attr("height", 0)
    //             .transition() 
    //             .duration(800)
    //             .ease(d3.easeCubicOut)
    //             .attr("y", d => yScale(d.length)) 
    //             .attr("height", d => Math.max(0, view.size - yScale(d.length)));
    //     } else{
    //         bars.attr("y", d => yScale(d.length)) 
    //             .attr("height", d => Math.max(0, view.size - yScale(d.length)));
    //     }
    //     if(!isNumericMajority){
    //         bars.on("mouseover", function(event, d) {
    //             d3.select(this).attr("opacity", 0.5);
    //             tooltip.style("display", "block")
    //                 .html(`<strong>${d.category}</strong><br><strong>Count: </strong>${d.length}`)
    //                 .style("left", `${event.pageX + 10}px`)
    //                 .style("top", `${event.pageY + 10}px`);
    //         })
    //         .on("mousemove", function(event) {
    //             tooltip.style("left", `${event.pageX + 10}px`)
    //                 .style("top", `${event.pageY + 10}px`);
    //         })
    //         .on("mouseout", function() {
    //             d3.select(this).attr("opacity", 0.8);
    //             tooltip.style("display", "none");
    //         })
    //         .attr("data-ids", d => d.ids.join(","))
    //         .on("click", function (event, d) {
    //             if (!selectionEnabled) return;
    //             handleBarClick(event, d, xCol, groupByAttribute)
    //         });
    //     }
    //     else{
    //         bars.on("mouseover", function(event, d) {
    //             d3.select(this).attr("opacity", 0.5);
    //             tooltip.style("display", "block")
    //                 .html(`<strong>Bin Range:</strong> ${d.x0.toFixed(2)} - ${d.x1.toFixed(2)}<br><strong>Count: </strong>${d.length}`)
    //                 .style("left", `${event.pageX + 10}px`)
    //                 .style("top", `${event.pageY + 10}px`);
    //         })
    //         .on("mousemove", function(event) {
    //             tooltip.style("left", `${event.pageX + 10}px`)
    //                 .style("top", `${event.pageY + 10}px`);
    //         })
    //         .on("mouseout", function() {
    //             d3.select(this).attr("opacity", 0.8);
    //             tooltip.style("display", "none");
    //         })
    //         .attr("data-ids", d => d.ids.join(","))
    //         .on("click", function (event, d) {
    //             if (!selectionEnabled) return;
    //             handleBarClick(event, d, xCol, groupByAttribute)
    //         });
    //     }
        
    // }    
}