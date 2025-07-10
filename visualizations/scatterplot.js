

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




export function draw(model, view, cellGroup, svg, givenData, xCol, yCol, groupByAttribute){

    let sampleData = query_sample2d(givenData.select(["ID", xCol, yCol]).objects(), model.getColumnErrors(), xCol, yCol, 50, 100);
    // console.log("sampleData", sampleData);


    let defs = null;
    let patterns = {};

    function generate_pattern(svg, colorScale, errorArray) {
        let patternSize = 30;

        if( defs === null){
            // svg.selectAll("defs").remove(); // Remove previous cell groups
            defs = svg.append("defs")
        }

        let patternName = errorArray.join("_") + "_pattern";
        // console.log("patternName", patternName);
        if ( patternName in patterns ){
            return `url(#${patternName})`
        }

        let pattern = defs.append("pattern")
            .attr("id", patternName)
            .attr("width", patternSize)
            .attr("height", patternSize)
            .attr("patternUnits", "userSpaceOnUse")

        for( let i = -patternSize; i < patternSize; ){
            errorArray.forEach( (error, idx) => {
                pattern.append("line")
                    .attr("x1", i-1)
                    .attr("y1", 0-1)
                    .attr("x2", i + patternSize+1)
                    .attr("y2", patternSize+1)
                    .attr("stroke", colorScale(error))
                    .attr("stroke-width", 2)
                i += 2.5
            })
        }
        patterns[patternName] = pattern;

        return `url(#${patternName})`;

    }    

    // view.errorColors['none'] = "steelblue";
    // const colorScale = d3.scaleOrdinal().domain(Object.keys(view.errorColors)).range(Object.values(view.errorColors));
    const colorScale = view.errorColors


    let numHistDataX = sampleData.scaleX.numeric;
    let catHistDataX = sampleData.scaleX.categorical;

    let sizeDistNum = view.size * (numHistDataX.length / (catHistDataX.length + numHistDataX.length));

    let spacingX = (numHistDataX.length === 0 || catHistDataX.length === 0) ? 0 : 5

    const xScaleNum = numHistDataX.length === 0 ? null : 
                        d3.scaleLinear()
                            .domain(numHistDataX)
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

    let numHistDataY = sampleData.scaleY.numeric;
    let catHistDataY = sampleData.scaleY.categorical;
    let sizeDistY = view.size * (catHistDataY.length / (catHistDataY.length + numHistDataY.length));
    let spacingY = (numHistDataY.length === 0 || catHistDataY.length === 0) ? 0 : 5
    const yScaleNum = numHistDataY.length === 0 ? null : 
                        d3.scaleLinear()
                            .domain(numHistDataY)
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

    const circles = cellGroup.selectAll("circle")
            .data(sampleData.data)
            .join("circle")
            .attr("cx", d => {
                if (d.xType === "numeric") return xScaleNum(d.x);
                return xScaleCat(d.x);
            })
            .attr("cy", d => {
                if (d.yType === "numeric") return yScaleNum(d.y);
                return yScaleCat(d.y);
            })
            .attr("r", 4) // Larger radius for NaN points
            .attr("fill", d => {
                if (d.errors.length === 0) 
                    return colorScale('none');
                if (d.errors.length === 1) 
                    return colorScale(d.errors[0]);
                return generate_pattern(svg, colorScale, d.errors);
                // return "black"
            })

    createTooltip(circles,
        d => {
            let bin = String(d.x) + " x " + String(d.y);
            let errorList = "";
            if( d.errors.length >= 1 ) errorList = "<br><strong>Errors: </strong>" + d.errors[0];
            if( d.errors.length > 1 )
                d.errors.slice(1).forEach(key => {
                    errorList += `, ${key}`;
                });
            return `<strong>Data:</strong> ${bin}${errorList}`;
        },
        d => {
            console.log("Left click on point", d);
        },
        d => {
            console.log("Right click on point", d);
        },
        d => {
            console.log("Double click on point", d);
        }
    );

}

