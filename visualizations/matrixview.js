




class MatrixView {
    constructor(container, model) {
        this.container = container;
        this.model = model;

        this.size = 180;                                                        // Size of each cell in matrix
        this.xPadding = 85;
        this.yPadding = 70;
        this.labelPadding = 60;

        this.leftMargin = 30;
        this.topMargin = 50;
        this.bottomMargin = 0; 
        this.rightMargin = 30; 

        this.errorTypes = {"total": "Total Error %",
                            "missing": "Missing Values", 
                            "mismatch": "Data Type Mismatch", 
                            "anomaly": "Average Anomalies (Outliers)", 
                            "incomplete": "Incomplete Data (< 3 points)", 
                            "none": "None"};

        this.errorColors = d3.scaleOrdinal()
                                .domain(Object.keys(this.errorTypes))
                                .range(["#00000000", "saddlebrown", "hotpink", "red", "gray", "steelblue"]);        
    }




    /**
     * Initial plotting code upon browser loading. Plots bar plots on diagonal and calls drawHeatMap to plot off-diagonal plots. Categorizes data for the bar plot as numeric or 
     * non-numeric and handles those cases separately. Within each case, plotting is handled separately when the group by function is active vs. when the data is not grouped. 
     * Each bar is colored by its error type, or is steelblue if no errors. Selected data is colored gold.
     * @param {*} givenData Data to visualize.
     * @param {*} groupByAttribute User selected group by attribute if active.
     * @param {*} selectedGroups Selected groups to plot as chosen by the user in the box-and-whisker plots for the groups.
     * @param {*} selectionEnabled If true, the user can click on the plots to select points.
     * @param {*} animate If true, the plots will draw with transitions.
     * @param {*} handleBrush Handles user selected scatterplot points.
     * @param {*} handleBarClick Handles user selected bars. 
     * @param {*} handleHeatmapClick Passes to drawHeatMap to handle user selected bins.
     */
    plotMatrix(givenData, groupByAttribute, selectedGroups, selectionEnabled, animate, handleBrush, handleBarClick, handleHeatmapClick) {  

        // console.log("Plotting matrix with data:", givenData);
        // console.log("Group by attribute:", groupByAttribute);

        const columnErrors = this.model.getColumnErrors();


        let columns = givenData.columnNames().slice(1).filter(col => col !== groupByAttribute);

        let matrixWidth = columns.length * this.size + (columns.length) * this.xPadding;
        let matrixHeight = columns.length * this.size + (columns.length) * this.yPadding;

        // let svgWidth = matrixWidth + this.leftMargin + this.rightMargin;
        // let svgHeight = matrixHeight + this.topMargin + this.bottomMargin;

        let ySize = (900 - this.topMargin - this.bottomMargin - (columns.length) * this.yPadding) / columns.length;
        let xSize = (900 - this.leftMargin - this.rightMargin - (columns.length) * this.xPadding) / columns.length;

        // console.log("xSize, ySize:", xSize, ySize);

        this.size = Math.min(xSize, ySize);


        // const container = d3.select(this.container);
        // container.selectAll("*").remove();
    
        const svg = d3.select(this.container).select("#main-svg");
        svg.selectAll("*").remove();
        // const svg = container
        //     .append("svg")
        //     .attr("width", svgWidth) // 575 + 20 + 60 + 60 = 715
        //     .attr("height", svgHeight);

        {
            const { total, ...legend } = this.errorTypes;
            drawLegend(svg, legend, this.errorColors);
        }

        let labels = svg.append("g")
        columns.forEach((col, i) => {
            labels.append("text")
                .attr("x", this.leftMargin + (i+1) * this.xPadding + i * (this.size) + this.size / 2)
                .attr("y", this.topMargin - 10)
                .attr("text-anchor", "middle")
                .text(col);
            labels.append("text")
                .attr("x", this.leftMargin - 10)
                .attr("y", this.topMargin + i * (this.size + this.yPadding) + this.size / 2)
                .attr("text-anchor", "middle")
                .attr("transform", "rotate(-90, " + (this.leftMargin - 10) + ", " + (this.topMargin + i * (this.size + this.yPadding) + this.size / 2) + ")")
                .text(col);
        });

                
        columns.forEach((xCol, j) => {
            columns.forEach((yCol, i) => {
            const cellID = `cell-${i}-${j}`;
            const cellGroup = svg
                .append("g")
                .attr("id", cellID)
                .attr("transform", `translate(${this.leftMargin + (j+1) * this.xPadding + j * this.size}, ${this.topMargin + i * (this.size + this.yPadding)})`);

                if (i === j) {      // On the diagonal, so this should be a bar plot.
                    let attr = ["ID", xCol];
                    if (groupByAttribute) attr.push(groupByAttribute);
                    visualizations['barchart'].module.draw(this, givenData.select(attr).objects(), groupByAttribute, cellGroup, columnErrors, svg, xCol );
                } 
                else if (i < j) {   // Upper diagonal, so this should be a scatterplot.
                    visualizations['scatterplot'].module.draw(this.model, this, cellGroup, svg, givenData, xCol, yCol, groupByAttribute );
                } else {
                    visualizations['heatmap'].module.draw(this.model, this, cellGroup,  svg, givenData, xCol, yCol, groupByAttribute);  
                }
            });
        });
    }
}
