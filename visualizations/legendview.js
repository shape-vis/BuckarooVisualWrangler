

function drawLegend(svg, legendItems, legendColormap ){

    const legendGroup = svg.append("g")
        .attr("class", "svg-legend")
        .attr("transform", "translate(900,25)");

    legendGroup.append("rect")
        .attr("width", 195)
        .attr("height", 15*Object.keys(legendItems).length + 22)
        .attr("stroke", "black")
        .attr("rx", 5)
        .attr("ry", 5)
        .attr("fill", "none")

    legendGroup.append("text")
        .attr("x", 5)
        .attr("y", 14)
        .attr("font-weight", "bold")
        .attr("font-size", "12px")
        .text("Legend")


    Object.keys(legendItems).forEach((item, index) => {
        const legendItem = legendGroup.append("g")
            // .attr("class", "legend-item")
            .attr("transform", `translate(5, ${22 + index * 15})`);

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

