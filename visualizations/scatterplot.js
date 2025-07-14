

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




export function draw(model, view, cellGroup, givenData, xCol, yCol){

    let sampleData = query_sample2d(givenData.select(["ID", xCol, yCol]).objects(), model.getColumnErrors(), xCol, yCol, 50, 100);
    // console.log("sampleData", sampleData);

    const colorScale = view.errorColors


    let numHistDataX = sampleData.scaleX.numeric;
    let catHistDataX = sampleData.scaleX.categorical;
    let numHistDataY = sampleData.scaleY.numeric;
    let catHistDataY = sampleData.scaleY.categorical;


    let selectActive = false;
    let selectStart = [0,0];
    let selectEnd = [0,0];
    let selectionBox = null;
    let selectedData = [];

    let backgroundBox = createBackgroundBox(cellGroup, view.size, view.size);

    const xScale = createHybridScales(view.size, numHistDataX, catHistDataX, numHistDataX.length === 0 ? null : numHistDataX, catHistDataX.length === 0 ? null :catHistDataX.map(d => d), "horizontal");
    const yScale = createHybridScales(view.size, numHistDataY, catHistDataY, numHistDataY.length === 0 ? null : numHistDataY, catHistDataY.length === 0 ? null :catHistDataY.map(d => d), "vertical");

    xScale.draw(cellGroup);
    yScale.draw(cellGroup);


    let circleFillFunc = d => {
        // console.log("d", d);
                let x = xScale.apply(d.x, d.xType )
                let y = yScale.apply(d.y, d.yType );
                if( x > Math.min(selectStart[0], selectEnd[0]) &&
                    x < Math.max(selectStart[0], selectEnd[0]) &&
                    y > Math.min(selectStart[1], selectEnd[1]) &&
                    y < Math.max(selectStart[1], selectEnd[1]) ){
                        selectedData.push(d);
                        return "gold";
                    }
                if (d.errors.length === 0) 
                    return colorScale('none');
                if (d.errors.length === 1) 
                    return colorScale(d.errors[0]);
                return view.generate_pattern(colorScale, d.errors);
            }

    const circles = cellGroup.selectAll("circle")
            .data(sampleData.data)
            .join("circle")
                .attr("cx", d => xScale.apply(d.x, d.xType))
                .attr("cy", d => yScale.apply(d.y, d.yType))
                .attr("r", 4)
                .attr("fill", circleFillFunc )


    selectionBox = cellGroup.append("rect")
        .attr("stroke", "transparent")
        .attr("fill", "none")
        .attr("stroke-width", 3)

    backgroundBox.call(d3.drag()
        .on("start", function(event, d) {
            selectStart = [event.x, event.y];
            selectActive = true;
        })
        .on("drag", function(event, d) {
            selectEnd = [event.x, event.y];
            selectedData = []
            selectionBox
                .attr("width", Math.abs(selectStart[0] - selectEnd[0]))
                .attr("height", Math.abs(selectStart[1] - selectEnd[1]))
                .attr("x", Math.min(selectStart[0], selectEnd[0]))
                .attr("y", Math.min(selectStart[1], selectEnd[1]))
                .attr("stroke", "black" )
                .attr("fill", "#0000ff20")
            circles
                .attr("fill", circleFillFunc )
        })
        .on("end", function(event, d) {
            selectActive = false;
            selectionBox
                .attr("stroke", "transparent" )
                .attr("fill", "none");
            console.log("Selected data points:", selectedData);
        }));


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

