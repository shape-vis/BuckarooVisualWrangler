




class MatrixView {
    constructor(container, model) {
        this.container = container;
        this.model = model;

        this.size = 180;                                                        // Size of each cell in matrix
        this.xPadding = 100;
        this.yPadding = 90;
        this.labelPadding = 60;

        this.leftMargin = 30;
        this.topMargin = 50;
        this.bottomMargin = 0; 
        this.rightMargin = 30; 

        this.errorColors = {                                                    // To be updated as new error detectors are added
            "mismatch": "hotpink",
            "missing": "saddlebrown",
            "anomaly": "red",
            "incomplete": "gray"
        };

        // this.errorPriority = ["anomaly", "mismatch", "missing", "incomplete"];  // Preference given to which errors are highlighted if both are present in a row
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

        const columnErrors = this.model.getColumnErrors();

        let columns = givenData.columnNames().slice(1).filter(col => col !== groupByAttribute);

        let matrixWidth = columns.length * this.size + (columns.length) * this.xPadding;
        let matrixHeight = columns.length * this.size + (columns.length) * this.yPadding;

        let svgWidth = matrixWidth + this.leftMargin + this.rightMargin;
        let svgHeight = matrixHeight + this.topMargin + this.bottomMargin;

        const container = d3.select(this.container);
        container.selectAll("*").remove();
    
        const svg = container
            .append("svg")
            .attr("width", svgWidth) // 575 + 20 + 60 + 60 = 715
            .attr("height", svgHeight);

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

                
        columns.forEach((xCol, i) => {
            columns.forEach((yCol, j) => {
            const cellID = `cell-${i}-${j}`;
            const cellGroup = svg
                .append("g")
                .attr("id", cellID)
                .attr("transform", `translate(${this.leftMargin + (j+1) * this.xPadding + j * this.size}, ${this.topMargin + i * (this.size + this.yPadding)})`);

                if (i === j) {      // On the diagonal, so this should be a bar plot.
                    let data = [];

                    if (groupByAttribute){
                        data = givenData.select(["ID", xCol, groupByAttribute]).objects();
                    }
                    else{
                        data = givenData.select(["ID", xCol]).objects();
                    }

                    visualizations['barchart'].module.draw(this, data, groupByAttribute, cellGroup, columnErrors, svg, xCol );
                } 
                else {
                    this.updateDrawing('heatmap', givenData, svg, yCol, xCol, cellID, groupByAttribute );
                }
            });
        });
    }


    updateDrawing( drawingType, givenData, svg, xCol, yCol, cellID, groupByAttribute ) {
        const cellGroup = d3.select(`#matrix-vis-stackoverflow`).select(`#${cellID}`); // Hardcoded for stackoverflow tab
        cellGroup.selectAll("*").remove();  
        const [, i, j] = cellID.split("-").map(d => parseInt(d));

        if (drawingType === 'heatmap') {
            visualizations['heatmap'].module.draw(this.model, this, cellGroup,  svg, givenData, xCol, yCol, groupByAttribute);  
            d3.select(this.parentNode).selectAll(".scatterplot-button").classed("active", false);
        }
        if (drawingType === 'scatterplot') {
            visualizations['scatterplot'].module.draw(this.model, this, cellGroup, svg, givenData, xCol, yCol, groupByAttribute );
            d3.select(this.parentNode).selectAll(".heatmap-button").classed("active", false);
        }

        const heatMapViewButton = cellGroup.append("image")
            .attr("class", "heatmap-button" + (drawingType === 'heatmap' ? " active" : ""))
            .attr("x", this.size)  
            .attr("y", 0)   
            .attr("width", 25) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/heatmap.png")
            .attr("cursor", "pointer")
            .on("click", () => this.updateDrawing('heatmap', givenData, svg, xCol, yCol, cellID, groupByAttribute));

        const scatterViewButton = cellGroup.append("image")
            .attr("class", "scatterplot-button" + (drawingType === 'scatterplot' ? " active" : ""))
            .attr("x", this.size)  
            .attr("y", 25)   
            .attr("width", 25) 
            .attr("height", 25)
            .attr("xlink:href", "images/icons/scatterplot.png")
            .attr("cursor", "pointer")
            .on("click", () => this.updateDrawing('scatterplot', givenData, svg, xCol, yCol, cellID, groupByAttribute));
    }

}
