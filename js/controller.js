class ScatterplotController {
    constructor(data, container) {
      this.model = new DataModel(data);
      this.view = new ScatterplotMatrixView(container);
      this.selectedAttributes = []; // Store selected columns
      this.xCol = null;
      this.yCol = null;
      this.filteredData = this.model.getData();
  
      this.render();
      this.setupEventListeners();
    }

    updateSelectedAttributes(attributes) {
        this.selectedAttributes = ["ID", ...attributes];
        this.filteredData = this.model.getData().select(this.selectedAttributes);
        this.render(); // Re-render visualization with updated columns
    }
  
    render() {
        this.view.plotMatrix(this.filteredData);
    }
  
    handleBrush(event, xScale, yScale, categoricalXScale, categoricalYScale, xCol, yCol) {
        document.getElementById("impute-average-x").textContent = `Impute average for ${xCol}`;
        document.getElementById("impute-average-y").textContent = `Impute average for ${yCol}`;
        this.xCol = xCol;
        this.yCol = yCol
        const selection = event.selection;

        if (!selection) return; 

        const [[x0, y0], [x1, y1]] = selection; 

        const selectedPoints = this.model.getData().objects().filter(d => {
            let xPos, yPos;

            if(categoricalXScale != null && categoricalYScale != null )
            {
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
            }
            else if(categoricalXScale != null)
            {
                if (typeof d[xCol] === "number" && !isNaN(d[xCol])) {
                    xPos = xScale(d[xCol]);
                }
                else {
                    xPos = categoricalXScale(d[xCol]);
                }

                yPos = yScale(d[yCol]);
            }
            else if(categoricalYScale != null)
            {
                if (typeof d[yCol] === "number" && !isNaN(d[yCol])) {
                    yPos = yScale(d[yCol]);
                }
                else {
                    yPos = categoricalYScale(d[yCol]);
                }

                xPos = xScale(d[xCol]);
            }
            else
            {
                xPos = xScale(d[xCol]);
                yPos = yScale(d[yCol]);
            }
            

            return xPos >= x0 && xPos <= x1 && yPos >= y0 && yPos <= y1;
        });

        console.log("Scatter points:", selectedPoints);
               
        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        this.view.enableBrushing(this.filteredData, this.handleBrush.bind(this), this.handleBarClick.bind(this));
    }
  
    handleBarClick(event, barData, column) {
        console.log("Bar data: ", barData);
        document.getElementById("impute-average-x").textContent = `Impute average for ${column}`;
        document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";

        this.xCol = column;
        const selectedPoints = this.model.getData().objects().filter(d => barData.ids.includes(d.ID));

        console.log("Selected bar points:", selectedPoints);

        this.model.setSelectedPoints(selectedPoints);
        this.view.setSelectedPoints(selectedPoints);
        
        this.view.enableBrushing(this.filteredData, this.handleBrush.bind(this), this.handleBarClick.bind(this));

        d3.select(event.target)
            .attr('fill', 'red');

        barX0 = barData.x0;
        barX1 = barData.x1;
        selectedBar = barData;
    }
  
    setupEventListeners() {
        const getActiveController = () => {
            return activeDataset === "practice" ? practiceController : stackoverflowController;
        };

        document.querySelectorAll(".tab-button").forEach(button => {
            button.addEventListener("click", function() {
                document.querySelectorAll(".tab-button").forEach(btn => btn.classList.remove("active"));
                this.classList.add("active");
    
                document.querySelectorAll(".tab-content").forEach(tab => {
                    tab.style.display = "none";
                });
    
                activeDataset = this.dataset.target === "tab1" ? "practice" : "stackoverflow";

                const targetTab = document.getElementById(this.getAttribute("data-target"));
                targetTab.style.display = "block";

                document.querySelector("input[name='options'][value='allData']").checked = true;
                document.getElementById("impute-average-x").textContent = "Impute selected data with average for X";
                document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";

                const activeController = getActiveController();
                activeController.render();

                // Update dropdown with correct dataset using the view function
                console.log("Updating dropdown for dataset:", activeController);

                activeController.view.populateDropdownFromTable(activeController.model.data, activeController);

                attachButtonEventListeners();
            });
        });

    }
}

function attachButtonEventListeners(){
    d3.select("#undo").on("click", null);
    d3.select("#redo").on("click", null);
    d3.select("#clear-selection").on("click", null);
    d3.select("#remove-selected-data").on("click", null);
    d3.select("#impute-average-x").on("click", null);
    d3.select("#impute-average-y").on("click", null);

     const getActiveController = () => {
        return activeDataset === "practice" ? practiceController : stackoverflowController;
    };

    d3.select("#undo").on("click", () => {
        const controller = getActiveController();
        console.log("Controller undo: ", controller);
        controller.model.undoLastTransformation();
        controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
    });

    d3.select("#redo").on("click", () => {
        const controller = getActiveController();
        controller.model.redoLastTransformation();
        controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
    });

    d3.select("#clear-selection").on("click", () => {
        document.getElementById("impute-average-x").textContent = "Impute selected data with average for X";
        document.getElementById("impute-average-y").textContent = "Impute selected data with average for Y";
        const controller = getActiveController();
        controller.view.setSelectedPoints([]);
        controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
    });

    d3.select("#remove-selected-data").on("click", () => {
        const controller = getActiveController();
        const selectedPoints = controller.model.getSelectedPoints();
        controller.model.filterData((row) => !selectedPoints.some((point) => point.ID === row.ID));
        controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
    });

    d3.select("#impute-average-x").on("click", () => {
        const controller = getActiveController();
        controller.model.imputeAverage(controller.xCol);
        controller.view.setSelectedPoints([]);
        controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
    });

    d3.select("#impute-average-y").on("click", () => {
        const controller = getActiveController();
        controller.model.imputeAverage(controller.yCol);
        controller.view.setSelectedPoints([]);
        controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
    });

    const radioButtons = document.querySelectorAll("input[name='options']");

    radioButtons.forEach((radio) => {
        radio.addEventListener("change", (event) => {
            const controller = getActiveController();
            if (event.target.value === "selectData" && event.target.checked) {
                controller.view.enableBrushing(controller.filteredData, controller.handleBrush.bind(controller), controller.handleBarClick.bind(controller));
            } else {
                controller.render();
            }
        });
    });
}

    
       