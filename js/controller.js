class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container);
  
      this.render();
      this.setupEventListeners();
      console.log(data.objects());
    }
  
    render() {
        this.view.plotMatrix(this.model.getData());
    }
  
    handleBrush(event, xScale, yScale, xCol, yCol) {
        const selection = event.selection;

        const nanXPosition = 190; 
        const nanYPosition = -15; 

        if (!selection) return; 

        if (selection) {
            const [[x0, y0], [x1, y1]] = selection;

            // const selectedPoints = this.model.getData().objects().filter(d => {
            //     if (isNaN(d[xCol]) || isNaN(d[yCol])) return true; //New for selecting Nans
            //     const x = this.view.xScale(d[xCol]);
            //     const y = this.view.yScale(d[yCol]);
            //     // console.log(d);
            //     return x >= x0 && x <= x1 && y >= y0 && y <= y1;
            // });

            const selectedPoints = this.model.getData().objects().filter(d => {
                let xPos, yPos;
    
                if (isNaN(d[xCol]) && isNaN(d[yCol])) {
                    xPos = nanXPosition;
                    yPos = nanYPosition;
                } else if (isNaN(d[xCol])) {
                    xPos = nanXPosition;
                    yPos = this.view.yScale(d[yCol]);
                } else if (isNaN(d[yCol])) {
                    xPos = this.view.xScale(d[xCol]);
                    yPos = nanYPosition;
                } else {
                    xPos = this.view.xScale(d[xCol]);
                    yPos = this.view.yScale(d[yCol]);
                }
    
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

        } else {
            d3.selectAll("circle").classed("selected", false);
        }
    }
  
    handleBarClick(event, barData, column) {
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
        this.model.imputeAverage("age"); 
        this.render();
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