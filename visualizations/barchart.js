

export function draw(view, data, groupByAttribute, cellGroup, columnErrors, svg, i, j, animate, selectionEnabled, handleBarClick, xCol) {

    let histData = query_histogram1d(data, columnErrors, xCol);
    // console.log("histData", histData);
    // scales
    // let numHistData = histData.filter(d => d.type == "numeric")
    // let catHistData = histData.filter(d => d.type == "categorical")

    // let sizeDistNum = view.size * (numHistData.length / (catHistData.length + numHistData.length));

    // let spacing = (numHistData.length === 0 || catHistData.length === 0) ? 0 : 5

    // const xScaleNum = d3.scaleLinear()
    //     .domain([d3.min(numHistData, (d) => d.bin[0]), d3.max(numHistData, (d) => d.bin[1])])
    //     .range([0, sizeDistNum-spacing]);

    // const xScaleCat = d3.scaleBand()
    //     .domain(catHistData.map(d => d.bin))
    //     .range([sizeDistNum+spacing, view.size])
    //     // .padding(0.2);

    const yScale = d3.scaleLinear()
        .domain([0, d3.max(histData.histograms, d => d.count.items)]).nice()
        .range([view.size, 0]);

    let numHistDataX = histData.scaleX[0];
    let catHistDataX = histData.scaleX[1];

    let sizeDistNum = view.size * (numHistDataX.length / (catHistDataX.length + numHistDataX.length));

    let spacingX = (numHistDataX.length === 0 || catHistDataX.length === 0) ? 0 : 5

    const xScaleNum = numHistDataX.length === 0 ? null : 
                        d3.scaleLinear()
                            .domain([d3.min(numHistDataX, (d) => d.x0), d3.max(numHistDataX, (d) => d.x1)])
                            .range([0, sizeDistNum-spacingX]);

    const xScaleCat = catHistDataX.length === 0 ? null :
                         d3.scaleBand()
                            .domain(catHistDataX.map(d => d))
                            .range([sizeDistNum+spacingX, view.size])

    if( xScaleCat !== null ){        
        cellGroup
                .append("g")
                .attr("transform", `translate(0, ${view.size})`)
                .call(d3.axisBottom(xScaleCat))            
                .selectAll("text") 
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d )  
                .attr("class", "bottom-axis-text")
                .attr("dx", "-0.5em") 
                .attr("dy", "0.5em")  
                .append("title")  
                .text(d => d);
    }
            
    if( xScaleNum !== null ){
        cellGroup
                .append("g")
                .attr("transform", `translate(0, ${view.size})`)
                .call(d3.axisBottom(xScaleNum).tickFormat(d3.format(".2s")))
                .selectAll("text") 
                .attr("class", "bottom-axis-text")
                .attr("dx", "-0.5em") 
                .attr("dy", "0.5em")  
                .append("title")  
                .text(d => d);
    }        

    // Draw axes
    cellGroup.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");

    view.errorColors['none'] = "steelblue";
    const colorScale = d3.scaleOrdinal().domain(Object.keys(view.errorColors)).range(Object.values(view.errorColors));
    
    let myData = []
    histData.histograms.forEach(d => {
        console.log("d", d);
        let items = d.count.items;

        Object.keys(d.count).filter(d => d !== "items").forEach(key => {
            myData.push({
                bin: d.xBin,
                type: d.xType,
                value: d.count[key],
                name: key,
                top: items,
                bottom: items - d.count[key],
            });
            items -= d.count[key];
        });

        if (items > 0) {
            myData.push({
                bin: d.xBin,
                type: d.xType,
                value: items,
                name: "none",
                top: items,
                bottom: 0
            });
        }
    });

    // Draw bars
    let bars = cellGroup.selectAll("rect")
        .data(myData)
        .join("rect")
            .attr("x", d => { return d.type == "numeric" ? xScaleNum(numHistDataX[d.bin].x0) : xScaleCat(d.bin) })
            .attr("y", d => yScale(d.top))
            .attr("height", d => yScale(d.bottom) - yScale(d.top))
            .attr("width", d => { return d.type == "numeric" ? (xScaleNum(numHistDataX[d.bin].x1) - xScaleNum(numHistDataX[d.bin].x0)) : xScaleCat.bandwidth() })
            .attr("fill", d => colorScale(d.name))
            .attr("stroke", "white")
            .attr("stroke-width", 2);    


    // const tooltip = d3.select("#tooltip");
    // bars.on("mouseover", function(event, d) {
    //         d3.select(this).attr("opacity", 0.5)

    //         tooltip.style("display", "block")
    //             .html(`<strong>Bin:</strong> ${d.desc}<br><strong>Error: </strong>${d.name}<br><strong>Count: </strong>${d.value}`)
    //             .style("left", `${event.pageX + 10}px`)
    //             .style("top", `${event.pageY + 10}px`);
    //     })
    //     .on("mousemove", function(event) {
    //         tooltip
    //             .style("left", `${event.pageX + 10}px`)
    //             .style("top", `${event.pageY + 10}px`);
    //     })
    //     .on("mouseout", function() {
    //         d3.select(this).attr("opacity", 1)

    //         tooltip.style("display", "none");
    //     })
    //     // .attr("data-ids", d => d.ids.join(","))
    //     .on("click", function (event, d) {
    //         if (!selectionEnabled) return;
    //         handleBarClick(event, d, xCol, groupByAttribute)
    //     });

}