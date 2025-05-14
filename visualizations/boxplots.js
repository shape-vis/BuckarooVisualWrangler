/**
 * Draws the boxplots for each group when grouped by the group by attribute. Highlights groups in red text when the group median is more that 2 median absolute deviations
 * from the overall dataset median. Median was used to be resistant to outliers, but mean can be implemented as well. User can select groups they want to view, and the 
 * data will be filtered down to just those groups and visualized.
 * @param {*} groupStats 
 * @param {*} onSelectGroups 
 * @param {*} overallMedian 
 * @param {*} selectedGroups User selected groups they want to view
 * @param {*} significantGroups Groups more than 2 Median Absolute Deviations (MAD) from dataset median
 */
export function draw(groupStats, onSelectGroups, overallMedian, selectedGroups, significantGroups) {
    console.log("significant groups", significantGroups);
    const container = d3.select("#boxplot-container");
    container.html(""); 

    const width = 1300; 
    const height = 500; 
    const margin = { top: 30, right: 120, bottom: 50, left: 100 };

    const salaryExtent = d3.extent(groupStats.flatMap(d => [d.min, d.max]).filter(v => !isNaN(v)));

    salaryExtent[0] = Math.min(salaryExtent[0], overallMedian);
    salaryExtent[1] = Math.max(salaryExtent[1], overallMedian);

    const xScale = d3.scaleBand()
                        .domain(groupStats.map(d => d.group))
                        .range([margin.left, width - margin.right])
                        .padding(0.2);

    const yScale = d3.scaleLinear()
                        .domain(salaryExtent)
                        .range([height - margin.bottom, margin.top]);

    const svg = container.append("svg")
                            .attr("width", width)
                            .attr("height", height);

    svg.append("g")
        .attr("transform", `translate(${margin.left}, 0)`)
        .call(d3.axisLeft(yScale).ticks(10));

    svg.append("g")
        .attr("transform", `translate(0, ${height - margin.bottom})`)
        .call(d3.axisBottom(xScale))
        .selectAll("text") 
        .style("font-size", "10px")
        .style("fill", d => significantGroups.some(group => group.group === d) ? "red" : "black")            
        .text(d => d.length > 10 ? d.substring(0, 12) + "…" : d)  
        .append("title")  
        .text(d => d);

    svg.append("line")
        .attr("x1", margin.left)
        .attr("x2", width - margin.right)
        .attr("y1", yScale(overallMedian))
        .attr("y2", yScale(overallMedian))
        .attr("stroke", "blue")
        .attr("stroke-dasharray", "5,5") 
        .attr("stroke-width", 2);

    svg.append("text")
        .attr("x", width - margin.right) 
        .attr("y", yScale(overallMedian) + 4) 
        .attr("fill", "blue")
        .attr("font-size", "10px")
        .attr("font-weight", "bold")
        .attr("text-anchor", "start") 
        .text(`Dataset Median: ${overallMedian.toFixed(2)}`);

    svg.append("text")
        .attr("x", 0) 
        .attr("y", 0) 
        .attr("transform", `translate(${margin.left - 60}, ${height / 2}) rotate(-90)`) 
        .attr("text-anchor", "middle") 
        .attr("font-size", "18px") 
        .text("Salary $");

    groupStats.forEach(d => {
        const groupX = xScale(d.group) + xScale.bandwidth() / 2; 

        svg.append("line")
            .attr("x1", groupX).attr("x2", groupX)
            .attr("y1", yScale(d.min)).attr("y2", yScale(d.max))
            .attr("stroke", "black");

        svg.append("rect")
            .attr("x", xScale(d.group))
            .attr("width", xScale.bandwidth())
            .attr("y", yScale(d.q3))
            .attr("height", yScale(d.q1) - yScale(d.q3)) 
            .attr("fill", "steelblue").attr("opacity", 0.6);

        svg.append("line")
            .attr("x1", xScale(d.group)).attr("x2", xScale(d.group) + xScale.bandwidth())
            .attr("y1", yScale(d.median)).attr("y2", yScale(d.median))
            .attr("stroke", "black").attr("stroke-width", 2);
    });

    const checkboxContainer = container.append("div")
        .attr("id", "checkbox-container")
        .style("position", "absolute")
        .style("top", `${height - margin.bottom + 80}px`) 
        .style("left", "0px") 
        .style("width", `${width}px`) 
        .style("display", "flex")
        .style("justify-content", "center") 
        .style("gap", "10px");

    groupStats.forEach((d, i) => {
        const whiskerX = xScale(d.group) + xScale.bandwidth() / 2 + 20; 

        const checkboxWrapper = checkboxContainer.append("div")
            .attr("class", "group-checkbox")
            .style("position", "absolute") 
            .style("left", `${whiskerX}px`) 
            .style("transform", "translateX(-50%)") 
            .style("text-align", "center");

        const checkbox = checkboxWrapper.append("input")
            .attr("type", "checkbox")
            .attr("value", d.group)
            .attr("id", `checkbox-${i}`);

        if (selectedGroups.includes(d.group)) {
            checkbox.property("checked", true);
        }

        checkbox.on("change", function () {
            onSelectGroups();
        });
    });

    const legend = svg.append("g")
        .attr("transform", `translate(${width - margin.right - 300}, ${margin.top - 30})`);

    legend.append("rect")
        .attr("width", 15)
        .attr("height", 15)
        .attr("fill", "red")
        .attr("stroke", "black")
        .attr("stroke-width", 1);

    legend.append("text")
        .attr("x", 20) 
        .attr("y", 12) 
        .attr("font-size", "12px")
        .attr("fill", "black")
        .text("Indicates groups > 2 Median Absolute Deviations (MAD) from dataset median");
}