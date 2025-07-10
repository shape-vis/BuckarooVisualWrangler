




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
export function draw(model, view, cellGroup, svg, givenData, xCol, yCol, groupByAttribute ){

    view.errorColors['none'] = "steelblue";
    const colorScale = d3.scaleOrdinal().domain(Object.keys(view.errorColors)).range(Object.values(view.errorColors));
    
    let histData = query_histogram2d(givenData.select(["ID", xCol, yCol]).objects(), model.getColumnErrors(), xCol, yCol);
    // console.log("histData", histData);


    let defs = null;
    let patterns = {};

    function generate_pattern(svg, colorScale, errorArray) {

        if( defs === null){
            // svg.selectAll("defs").remove(); // Remove previous cell groups
            defs = svg.append("defs")
        }

        let patternName = errorArray.join("_") + "_pattern";
        console.log("patternName", patternName);
        if ( patternName in patterns ){
            return `url(#${patternName})`
        }

        let pattern = defs.append("pattern")
            .attr("id", patternName)
            .attr("width", 10)
            .attr("height", 10)
            .attr("patternUnits", "userSpaceOnUse")
        
        for( let i = -10; i < 10; ){
            errorArray.forEach( (error, idx) => {    
                pattern.append("line")
                    .attr("x1", i)
                    .attr("y1", 0)
                    .attr("x2", i + 20)
                    .attr("y2", 20)
                    .attr("stroke", colorScale(error))
                    .attr("stroke-width", 2)
                i += 2.5
            })
        }
        patterns[patternName] = pattern;

        return `url(#${patternName})`;

    }    

    let numHistDataX = histData.scaleX.numeric;
    let catHistDataX = histData.scaleX.categorical;

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

    let numHistDataY = histData.scaleY.numeric;
    let catHistDataY = histData.scaleY.categorical;
    let sizeDistY = view.size * (catHistDataY.length / (catHistDataY.length + numHistDataY.length));
    let spacingY = (numHistDataY.length === 0 || catHistDataY.length === 0) ? 0 : 5
    const yScaleNum = numHistDataY.length === 0 ? null : 
                        d3.scaleLinear()
                            .domain([d3.min(numHistDataY, (d) => d.x0), d3.max(numHistDataY, (d) => d.x1)])
                            .range([view.size, sizeDistY+spacingY]);
    const yScaleCat = catHistDataY.length === 0 ? null :
                         d3.scaleBand()
                            .domain(catHistDataY.map(d => d))
                            .range([sizeDistY-spacingY, 0]);

    if( yScaleCat !== null ){
        cellGroup
                .append("g")
                .call(d3.axisLeft(yScaleCat))
                .selectAll("text")
                .text(d => d.length > 10 ? d.substring(0, 10) + "…" : d )
                .attr("class", "left-axis-text")
                .append("title")
                .text(d => d);
    }

    if( yScaleNum !== null ){
        cellGroup
                .append("g")
                .call(d3.axisLeft(yScaleNum).tickFormat(d3.format(".2s")))
                .selectAll("text")
                .attr("class", "left-axis-text")
                .append("title")
                .text(d => d);
    }

    let bars = cellGroup.append("g")
                    .selectAll("rect")
                    .data(histData.histograms.filter( d => d.count.items > 0 ))
                    .enter()
                    .append("rect")
                        .attr("x", d => { return d.xType == "numeric" ? xScaleNum(numHistDataX[d.xBin].x0) : xScaleCat(d.xBin) })
                        .attr("y", d => { return d.yType == "numeric" ? yScaleNum(numHistDataY[d.yBin].x1) : yScaleCat(d.yBin) })
                        .attr("height", d => { return d.yType == "numeric" ? yScaleNum(numHistDataY[d.yBin].x0) - yScaleNum(numHistDataY[d.yBin].x1) : yScaleCat.bandwidth() } )
                        // .attr("height", d => { return 10 } )
                        .attr("width", d => { return d.xType == "numeric" ? xScaleNum(numHistDataX[d.xBin].x1)-xScaleNum(numHistDataX[d.xBin].x0) : xScaleCat.bandwidth() } )
                        // .attr("fill", d => colorScale(d.name))
                        .attr("fill", d => { 
                            let keys = Object.keys(d.count).filter( key => key !== "items" ); 
                            if( keys.length === 0 ) return colorScale("none")
                            if( keys.length === 1 ) return colorScale(keys[0])
                            return generate_pattern(svg,colorScale, keys)
                         })
                        .attr("stroke", "white")
                        .attr("stroke-width", 1);
            


    createTooltip(bars,
        d => {
            let xBin = d.xType == "numeric" ? `${Math.round(numHistDataX[d.xBin].x0)}-${Math.round(numHistDataX[d.xBin].x1)}` : d.xBin;
            let yBin = d.yType == "numeric" ? `${Math.round(numHistDataY[d.yBin].x0)}-${Math.round(numHistDataY[d.yBin].x1)}` : d.yBin;
            let errorList = "";
            Object.keys(d.count).forEach(key => {
                if( key === "items") return; // Skip items count in tooltip
                errorList += `<br> - ${key}: ${d.count[key]}`;
            });
            if( errorList !== "") errorList = "<br><strong>Errors: </strong> " + errorList; 
            return `<strong>Bin:</strong> ${xBin} x ${yBin}<br><strong>Items: </strong>${d.count.items}${errorList}`;
        },
        (d) => {
            console.log("Left click on heatmap bin", d);
        },
        (d) => {
            // Right click handler, if needed
            console.log("Right click on heatmap bin", d);
        },
        (d) => {
            // Double click handler, if needed
            console.log("Double click on heatmap bin", d);
        }
    );
}

