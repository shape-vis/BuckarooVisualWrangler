class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container);
      this.xCol = null;
      this.yCol = null;
  
      this.render();
      this.setupEventListeners();
      console.log(data.objects());
    }
  
    render() {
        this.view.plotMatrix(this.model.getData());
    }
  
    handleBrush(event, xScale, yScale, categoricalXScale, categoricalYScale, xCol, yCol) {
        document.getElementById("impute-average-x").textContent = `Impute average for ${xCol}`;
        document.getElementById("impute-average-y").textContent = `Impute average for ${yCol}`;
        this.xCol = xCol;
        this.yCol = yCol
        const selection = event.selection;

        console.log("Selection: ", selection);

        if (!selection) return; 

        const [[x0, y0], [x1, y1]] = selection; 

        const selectedPoints = this.model.getData().objects().filter(d => {
            let xPos, yPos;

            if (typeof d[xCol] === "number" && !isNaN(d[xCol]) && typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                xPos = xScale(d[xCol]);
                yPos = yScale(d[yCol]);
            } else if ((typeof d[xCol] !== "number" || isNaN(d[xCol])) && typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                xPos = categoricalXScale(d[xCol]);
                yPos = yScale(d[yCol]);
            } else if ((typeof d[xCol] === "number" && !isNaN(d[xCol])) && (typeof d[yCol] !== "number" || isNaN(d[yCol]))) {
                xPos = xScale(d[xCol]);
                yPos = categoricalYScale(d[yCol]);
            } else {
                xPos = categoricalXScale(d[xCol]);
                yPos = categoricalYScale(d[yCol]);
            }

            return xPos >= x0 && xPos <= x1 && yPos >= y0 && yPos <= y1;
        });

        console.log("Scatter points:", selectedPoints);
               
        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
    }
  
    handleBarClick(event, barData, column) {
        document.getElementById("impute-average-x").textContent = `Impute average for ${column}`;
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
            document.getElementById("impute-average-x").textContent = "Impute selected data with average for X";
            document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";
            this.view.setSelectedPoints([]);
            this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this))
        });

        d3.select("#remove-selected-data").on("click", () => {
        const selectedPoints = this.model.getSelectedPoints();
        this.model.filterData((row) => !selectedPoints.some((point) => point.id === row.id));
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
        });

        d3.select("#impute-average-x").on("click", () => {
        this.model.imputeAverage(this.xCol); 
        this.view.setSelectedPoints([]);
        this.view.enableBrushing(this.model.getData(), this.handleBrush.bind(this), this.handleBarClick.bind(this));
        });
        
        d3.select("#impute-average-y").on("click", () => {
            this.model.imputeAverage(this.yCol); 
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