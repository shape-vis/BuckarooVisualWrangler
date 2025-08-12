

function drawLegend(svg, legendItems, legendColormap, x, y ){

    const legendHeight = 15 * Object.keys(legendItems).length + 30;
    const legendWidth = 175;

    const legendGroup = svg.append("g")
        .attr("class", "svg-legend")
        .attr("transform", `translate(${x},${y})`);

    legendGroup.append("rect")
        .attr("width", legendWidth)
        .attr("height", legendHeight)
        .attr("stroke", "black")
        .attr("rx", 5)
        .attr("ry", 5)
        .attr("fill", "none")

    legendGroup.append("text")
        .attr("x", 5 + legendWidth / 2)
        .attr("y", 20)
        .attr("font-weight", "bold")
        .attr("font-size", "14px")
        .attr("text-anchor", "middle")
        .text("Legend")


    Object.keys(legendItems).forEach((item, index) => {
        const legendItem = legendGroup.append("g")
            // .attr("class", "legend-item")
            .attr("transform", `translate(5, ${30 + index * 15})`);

        legendItem.append("rect")
            .attr("width", 10)
            .attr("height", 10)
            .attr("fill", legendColormap(item));

        legendItem.append("text")
            .attr("x", 13)
            .attr("y", 8)
            .text(legendItems[item]);
    });


}


