




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

        this.defs = null;
        this.patterns = {};

    }




    generate_pattern(colorScale, errorArray) {
        let patternSize = 30;

        if( this.defs === null){
            // svg.selectAll("defs").remove(); // Remove previous cell groups
            this.defs = this.svg.append("defs")
        }

        let patternName = errorArray.join("_") + "_pattern";
        // console.log("patternName", patternName);
        if ( patternName in this.patterns ){
            return `url(#${patternName})`
        }

        let pattern = this.defs.append("pattern")
            .attr("id", patternName)
            .attr("width", patternSize)
            .attr("height", patternSize)
            .attr("patternUnits", "userSpaceOnUse")

        for( let i = -patternSize; i < patternSize; ){
            errorArray.forEach( (error, idx) => {
                pattern.append("line")
                    .attr("x1", i-1)
                    .attr("y1", 0-1)
                    .attr("x2", i + patternSize+1)
                    .attr("y2", patternSize+1)
                    .attr("stroke", colorScale(error))
                    .attr("stroke-width", 2)
                i += 2.5
            })
        }
        this.patterns[patternName] = pattern;

        return `url(#${patternName})`;
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
    
        this.svg = d3.select(this.container).select("#main-svg");
        this.svg.selectAll("*").remove();
        this.defs = null;
        this.patterns = {};
        // const svg = container
        //     .append("svg")
        //     .attr("width", svgWidth) // 575 + 20 + 60 + 60 = 715
        //     .attr("height", svgHeight);

        {
            const { total, ...legend } = this.errorTypes;
            drawLegend(this.svg, legend, this.errorColors);
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
            const cellGroup = this.svg
                .append("g")
                .attr("id", cellID)
                .attr("transform", `translate(${this.leftMargin + (j+1) * this.xPadding + j * this.size}, ${this.topMargin + i * (this.size + this.yPadding)})`);

                if (i === j) {      // On the diagonal, so this should be a bar plot.
                    let attr = ["ID", xCol];
                    if (groupByAttribute) attr.push(groupByAttribute);
                    visualizations['barchart'].module.draw(this.model, this, givenData.select(attr).objects(), cellGroup, xCol );
                } 
                else if (i < j) {   // Upper diagonal, so this should be a scatterplot.
                    visualizations['scatterplot'].module.draw(this.model, this, cellGroup, givenData, xCol, yCol );
                } else {
                    visualizations['heatmap'].module.draw(this.model, this, cellGroup,  givenData, xCol, yCol);  
                }
            });
        });
    }
}
