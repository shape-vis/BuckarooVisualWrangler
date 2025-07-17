

export function draw(model, view, canvas, givenData, xCol) {

    console.log("Drawing bar chart for column:", xCol);

    let histData = query_histogram1d(givenData.select(["ID", xCol]).objects(), model.getColumnErrors(), xCol);
    console.log("histData", histData);


    let backgroundBox = createBackgroundBox(canvas, view.size, view.size);


    let numHistDataX = histData.scaleX.numeric;
    let catHistDataX = histData.scaleX.categorical;

    const xScale = createHybridScales(view.size, numHistDataX, catHistDataX, numHistDataX.length === 0 ? null : [d3.min(numHistDataX, (d) => d.x0), d3.max(numHistDataX, (d) => d.x1)], catHistDataX.length === 0 ? null :catHistDataX.map(d => d));

    const yScale = d3.scaleLinear()
        .domain([0, d3.max(histData.histograms, d => d.count.items)]).nice()
        .range([view.size, 0]);



    // view.errorColors['none'] = "steelblue";
    // const colorScale = d3.scaleOrdinal().domain(Object.keys(view.errorColors)).range(Object.values(view.errorColors));
    const colorScale = view.errorColors
    
    let myData = []
    histData.histograms.forEach(d => {
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

    let selected = []
    let barColor = d => {
        if( selected.includes(d) ) return "gold";
        return colorScale(d.name);
    }

    // Draw bars
    let bars = canvas.append("g")
        .selectAll("rect")
        .data(myData)
        .join("rect")
            .attr("x", d => xScale.apply( d.type == "numeric" ? numHistDataX[d.bin].x0 : d.bin, d.type ))
            .attr("y", d => yScale(d.top))
            .attr("height", d => yScale(d.bottom) - yScale(d.top) )
            .attr("width", d => { return d.type == "numeric" ? (xScale.numericalBandwidth(numHistDataX[d.bin].x0, numHistDataX[d.bin].x1)) : xScale.categoricalBandwidth() })
            .attr("fill", barColor)
            .attr("stroke", "white")
            .attr("stroke-width", 2);    


    xScale.draw(canvas);


    // Draw axes
    canvas.append("g").call(d3.axisLeft(yScale)).style("font-size", "8px");
    

    backgroundBox.on("click", function(event) {
        console.log("Clicked on heatmap background", event);
        selected = []; // Reset selection
        bars.attr("fill", barColor); // Update colors of all bars
    });    

    createTooltip(bars, 
        d => {
            let bin = d.type == "numeric" ? `${Math.round(numHistDataX[d.bin].x0)}-${Math.round(numHistDataX[d.bin].x1)}` : d.bin;
            return `<strong>Bin: </strong>${bin}<br><strong>Items: </strong>${d.value}<br><strong>Errors: </strong>${d.name}`;
        },
        (d, event) => {
            selectionControlPanel.clearSelection(canvas);

            console.log("Left click on bar", d, event);
            if ( event.shiftKey ) {
                // If shift is pressed, toggle selection
                if (selected.includes(d)) {
                    selected = selected.filter(item => item !== d);
                } else {
                    selected.push(d);
                }
            }
            else{
                selected = [d]; // Reset selection to only the clicked bar
            }
            bars.attr("fill", barColor); // Update colors of all bars

            selectionControlPanel.setSelection( canvas, "barchart", [model, view, canvas, givenData, xCol],
                {
                    data: selected,
                    scaleX: histData.scaleX,
                    scaleY: histData.scaleY,
                }, () => {
                    console.log("Selection cleared", this);
                    selected = []; // Reset selection after callback
                    bars.attr("fill", barColor); // Update colors of all bars
                });

        },
        (d) => {
            console.log("Right click on bar", d);
        },
        (d) => {
            console.log("Double click on bar", d);
        }
    );
       

}