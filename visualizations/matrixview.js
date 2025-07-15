




class MatrixView {
    constructor(container, model) {
        this.container = container;
        this.model = model;

        this.size = 180;                                                        // Size of each cell in matrix
        this.xPadding = 85;
        this.yPadding = 70;

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
     */
    plotMatrix(givenData, groupByAttribute ) {  

        let columns = givenData.columnNames().slice(1).filter(col => col !== groupByAttribute);

        let xSize = (900 - this.leftMargin - this.rightMargin - (columns.length) * this.xPadding) / columns.length;
        let ySize = (900 - this.topMargin - this.bottomMargin - (columns.length) * this.yPadding) / columns.length;

        this.size = Math.min(xSize, ySize);

        this.svg = d3.select(this.container).select("#main-svg");
        this.svg.selectAll("*").remove();

        {
            const { total, ...legend } = this.errorTypes;
            selectionControlPanel.drawControls(this.svg, 900, 25);
            drawLegend(this.svg, legend, this.errorColors, 900, 180);
        }

        let labels = this.svg.append("g")
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
                const canvas = this.svg
                                    .append("g")
                                        .attr("id", cellID)
                                        .attr("transform", `translate(${this.leftMargin + (j+1) * this.xPadding + j * this.size}, ${this.topMargin + i * (this.size + this.yPadding)})`);

                if (i === j) {      // On the diagonal, so this should be a bar plot.
                    visualizations['barchart'].module.draw(this.model, this, canvas, givenData, xCol );
                } 
                else if (i < j) {   // Upper diagonal, so this should be a scatterplot.
                    visualizations['scatterplot'].module.draw(this.model, this, canvas, givenData, xCol, yCol );
                } else {
                    visualizations['heatmap'].module.draw(this.model, this, canvas,  givenData, xCol, yCol);  
                }
            });
        });
    }
}
