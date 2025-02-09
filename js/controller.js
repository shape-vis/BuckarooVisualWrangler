class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container);
      this.xCol = null;
  
      this.render();
      this.setupEventListeners();
      console.log(data.objects());
    }
  
    render() {
        this.view.plotMatrix(this.model.getData());
    }
  
    handleBrush(event, xScale, yScale, categoricalXScale, categoricalYScale, xCol, yCol) {
        this.xCol = xCol;
        const selection = event.selection;

        console.log("Selection: ", selection);

        if (!selection) return; 

        const [[x0, y0], [x1, y1]] = selection; // Brush selection bounds

        const selectedPoints = this.model.getData().objects().filter(d => {
            let xPos, yPos;

            if (typeof d[xCol] === "number" && !isNaN(d[xCol]) && typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                // Both are numeric
                xPos = xScale(d[xCol]);
                yPos = yScale(d[yCol]);
            } else if ((typeof d[xCol] !== "number" || isNaN(d[xCol])) && typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                // x is categorical, y is numeric
                xPos = categoricalXScale(d[xCol]);
                yPos = yScale(d[yCol]);
            } else if ((typeof d[xCol] === "number" && !isNaN(d[xCol])) && (typeof d[yCol] !== "number" || isNaN(d[yCol]))) {
                // x is numeric, y is categorical
                xPos = xScale(d[xCol]);
                yPos = categoricalYScale(d[yCol]);
            } else {
                // Both x and y are categorical
                xPos = categoricalXScale(d[xCol]);
                yPos = categoricalYScale(d[yCol]);
            }

            // Adjust for inverted y-axis in D3
            return xPos >= x0 && xPos <= x1 && yPos >= y0 && yPos <= y1;
        });

        console.log("Scatter points:", selectedPoints);

        // d3.selectAll("circle")
        //     .classed("selected", d => {
        //         const cx = this.view.xScale(d[xCol]);
        //         const cy = this.view.yScale(d[yCol]);
        //         this.view.brushXCol = xCol;
        //         this.view.brushYCol = yCol;
        //         return cx >= x0 && cx <= x1 && cy >= y0 && cy <= y1;
        //     });

        // // Highlight bars
        // d3.selectAll("rect")
        //     .classed("selected", d => {
        //         return selectedPoints.some(p => p[xCol] >= d.x0 && p[xCol] <= d.x1 || p[yCol] >= d.x0 && p[yCol] <= d.x1);
        //     });
        
        
        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
    }
  
    handleBarClick(event, barData, column) {
        this.xCol = column;
        const selectedPoints = this.model.getData().objects().filter(d => barData.ids.includes(d.id));

        console.log("Selected bar points:", selectedPoints);

        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));

        d3.select(event.target)
            .attr('fill', 'red');

        barX0 = barData.x0;
        barX1 = barData.x1;
        selectedBar = barData;
    }
  
    setupEventListeners() {
        d3.select("#undo").on("click", () => {
            this.model.undoLastTransformation(); 
            this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
        });

        d3.select("#redo").on("click", () => {
            this.model.redoLastTransformation(); 
            this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
        });

        d3.select("#clear-selection").on("click", () => {
            this.view.setSelectedPoints([]);
            this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this))
        });

        d3.select("#remove-selected-data").on("click", () => {
        const selectedPoints = this.model.getSelectedPoints();
        this.model.filterData((row) => !selectedPoints.some((point) => point.id === row.id));
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
        });

        d3.select("#impute-average").on("click", () => {
        this.model.imputeAverage(this.xCol); 
        this.view.setSelectedPoints([]);
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
        });

        const radioButtons = document.querySelectorAll("input[name='options']");

        radioButtons.forEach((radio) => {
            radio.addEventListener("change", (event) => {
                if (event.target.value === "selectData" && event.target.checked) {
                    console.log("selected");
                    this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this)); 
                } else {
                    this.render();
                }
            });
        });
    }
  }