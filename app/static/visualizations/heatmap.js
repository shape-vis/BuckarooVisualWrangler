import {queryHistogram2d} from "../js/serverCalls.js";


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
 *
 * @param {*} model The data model.
 * @param {*} view The view to plot the heatmap in.
 * @param {*} canvas The DOM element for the cell.
 * @param {*} givenData Data to visualize.
 * @param {*} xCol The x attribute/column.
 * @param {*} yCol The y attribute/column.
 */
export async function draw(model, view, canvas, givenData, xCol, yCol) {

    // let histData = query_histogram2d(givenData.select(["ID", xCol, yCol]).objects(), model.getColumnErrors(), xCol, yCol);
    // // console.log("histData", histData);
    let histData;
    // let minId = 1
    // let maxId = 400
    let binsToCreate = 10
    try {
        let response = await queryHistogram2d(xCol, yCol, model.getSampleIDRangeMin(), model.getSampleIDRangeMax(), binsToCreate)
        histData = response["binned_data"]

    console.log("2d histData from the server", histData)

    // console.log("current selection: ", selectionControlPanel.currentSelection)

    // console.log("current table: ", localStorage.getItem("table"))


    let backgroundBox = createBackgroundBox(canvas, view.size, view.size);

    let numHistDataX = histData.scaleX.numeric;
    const numDomainX = numHistDataX.length === 0 ? null : [d3.min(numHistDataX, (d) => d.x0), d3.max(numHistDataX, (d) => d.x1)];
    let catHistDataX = histData.scaleX.categorical;
    const catDomainX = catHistDataX.length === 0 ? null : catHistDataX.map(d => d);

    let numHistDataY = histData.scaleY.numeric;
    const numDomainY = numHistDataY.length === 0 ? null : [d3.min(numHistDataY, (d) => d.x0), d3.max(numHistDataY, (d) => d.x1)];
    let catHistDataY = histData.scaleY.categorical;
    const catDomainY = catHistDataY.length === 0 ? null : catHistDataY.map(d => d);

    const xScale = createHybridScales(view.size, numHistDataX, catHistDataX, numDomainX, catDomainX, "horizontal");
    const yScale = createHybridScales(view.size, numHistDataY, catHistDataY, numDomainY, catDomainY, "vertical");

    xScale.draw(canvas);
    yScale.draw(canvas);

    const colorScale = view.errorColors

    let selected = []
    let barColor = d => {
        if (selected.includes(d)) return "gold";
        let keys = Object.keys(d.count).filter(key => key !== "items");
        if (keys.length === 0) return colorScale("none")
        if (keys.length === 1) return colorScale(keys[0])
        return generate_pattern(view.svg, colorScale, keys)
    }

    let bars = canvas.append("g")
        .selectAll("rect")
        .data(histData.histograms.filter(d => d.count.items > 0))
        .enter()
        .append("rect")
        .attr("x", d => {
            return xScale.apply(d.xType == "numeric" ? numHistDataX[d.xBin].x0 : d.xBin, d.xType)
        })
        .attr("y", d => {
            return yScale.apply(d.yType == "numeric" ? numHistDataY[d.yBin].x1 : d.yBin, d.yType)
        })
        .attr("height", d => {
            return d.yType == "numeric" ? yScale.numericalBandwidth(numHistDataY[d.yBin].x1, numHistDataY[d.yBin].x0) : yScale.categoricalBandwidth()
        })
        .attr("width", d => {
            return d.xType == "numeric" ? xScale.numericalBandwidth(numHistDataX[d.xBin].x0, numHistDataX[d.xBin].x1) : xScale.categoricalBandwidth()
        })
        .attr("fill", barColor)
        .attr("stroke", "white")
        .attr("stroke-width", 1);


    backgroundBox.on("click", function (event) {
        console.log("Clicked on heatmap background", event);
        selected = []; // Reset selection
        bars.attr("fill", barColor); // Update colors of all bars
    });

    createTooltip(bars,
        d => {
            let xBin = d.xType == "numeric" ? `${Math.round(numHistDataX[d.xBin].x0)}-${Math.round(numHistDataX[d.xBin].x1)}` : d.xBin;
            let yBin = d.yType == "numeric" ? `${Math.round(numHistDataY[d.yBin].x0)}-${Math.round(numHistDataY[d.yBin].x1)}` : d.yBin;
            let errorList = "";
            Object.keys(d.count).forEach(key => {
                if (key === "items") return; // Skip items count in tooltip
                errorList += `<br> - ${key}: ${d.count[key]}`;
            });
            if (errorList !== "") errorList = "<br><strong>Errors: </strong> " + errorList;
            return `<strong>Bin:</strong> ${xBin} x ${yBin}<br><strong>Items: </strong>${d.count.items}${errorList}`;
        },
        (d, event) => {
            selectionControlPanel.clearSelection(canvas);

            console.log("Left click on heatmap bin", d, event);
            if (event.shiftKey) {
                if (selected.includes(d)) {
                    selected = selected.filter(item => item !== d);
                } else {
                    selected.push(d);
                }
            } else {
                selected = [d]; // Reset selection to only the clicked bin
            }
            bars.attr("fill", barColor); // Update colors of all bars

            selectionControlPanel.setSelection(canvas, "heatmap", [model, view, canvas, givenData, xCol, yCol],
                {
                    data: selected,
                    scaleX: histData.scaleX,
                    scaleY: histData.scaleY,
                }, () => {
                    selected = []; // Reset selection after callback
                    bars.attr("fill", barColor); // Update colors of all bars
                });
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
}catch (error) {
        console.error(error.message)
    }
}

