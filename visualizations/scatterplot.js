

/**
 * Plots scatterplots on the off-diagonals when the scatterplot icon is selected. A point is colored an error color if it contains a data point with that error. If group by 
 * is active, the points are colored by group. 
 * Plots can be 4 categories: 
 *      both x & y are numeric, 
 *      x is categorical & y is numeric, 
 *      x is numeric & y is categorical,
 *      both x & y are categorical.
 * Group by is handled within the "fill" for each circle.
 * 
 * @param {*} model The data model.
 * @param {*} view The view to plot the scatterplot in.
 * @param {*} canvas The DOM element for the cell.
 * @param {*} givenData Data to visualize.
 * @param {*} xCol The x attribute/column.
 * @param {*} yCol The y attribute/column.
 */




export function draw(model, view, canvas, givenData, xCol, yCol){

    let sampleData = query_sample2d(givenData.select(["ID", xCol, yCol]).objects(), model.getColumnErrors(), xCol, yCol, 50, 100);
    // console.log("sampleData", sampleData);

    const colorScale = view.errorColors


    let numHistDataX = sampleData.scaleX.numeric;
    let catHistDataX = sampleData.scaleX.categorical;
    let numHistDataY = sampleData.scaleY.numeric;
    let catHistDataY = sampleData.scaleY.categorical;

    let backgroundBox = createBackgroundBox(canvas, view.size, view.size);

    const xScale = createHybridScales(view.size, numHistDataX, catHistDataX, numHistDataX.length === 0 ? null : numHistDataX, catHistDataX.length === 0 ? null :catHistDataX.map(d => d), "horizontal");
    const yScale = createHybridScales(view.size, numHistDataY, catHistDataY, numHistDataY.length === 0 ? null : numHistDataY, catHistDataY.length === 0 ? null :catHistDataY.map(d => d), "vertical");

    xScale.draw(canvas);
    yScale.draw(canvas);

    let selectedData = [];
    const selectionBox = createSelectionBox(canvas);

    let circleFillFunc = d => {
                if( selectedData.includes(d) )
                    return "gold";
                if (d.errors.length === 0) 
                    return colorScale('none');
                if (d.errors.length === 1) 
                    return colorScale(d.errors[0]);
                return generate_pattern(view.svg, colorScale, d.errors);
            }

    const circles = canvas.selectAll("circle")
            .data(sampleData.data)
            .join("circle")
                .attr("cx", d => xScale.apply(d.x, d.xType))
                .attr("cy", d => yScale.apply(d.y, d.yType))
                .attr("r", 4)
                .attr("fill", circleFillFunc )


    backgroundBox.call(d3.drag()
        .on("start", function(event, d) {
            selectionControlPanel.clearSelection(canvas);
            selectionBox.start(event.x, event.y);
        })
        .on("drag", function(event, d) {
            selectionBox.update(event.x, event.y);
            selectedData = sampleData.data.filter(d => selectionBox.inRange(xScale.apply(d.x, d.xType), yScale.apply(d.y, d.yType)));
            circles.attr("fill", circleFillFunc )
        })
        .on("end", function(event, d) {
            selectionBox.end(event.x, event.y);
            selectionControlPanel.setSelection( canvas, "scatterplot", [model, view, canvas, givenData, xCol, yCol],
                {
                    data: selectedData,
                    scaleX: sampleData.scaleX,
                    scaleY: sampleData.scaleY,
                }, () => {
                    selectedData = [];
                    circles.attr("fill", circleFillFunc )
                });
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

