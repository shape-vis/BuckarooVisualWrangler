class DataModel {
    constructor(initialData) {
      this.originalData = initialData;
      this.data = initialData;
      this.selectedPoints = [];
      this.dataStates = [];
      this.redoStack = [];
      this.dataTransformations = [];
      this.transformationPoints = [];
    }
  
    getData() {
      return this.data;
    }
  
    filterData(condition) {
      this.dataStates.push(this.data);
      this.redoStack = [];
      this.dataTransformations.push(condition);
      this.transformationPoints.push(this.selectedPoints);
      console.log(`Transformations: ${this.dataTransformations[0]}`);
      console.log(`Points: ${this.transformationPoints[0]}`);
      this.data = this.data.filter(aq.escape(condition));
    }

    undoLastTransformation() {
      if (this.dataStates.length > 0) {
          this.redoStack.push(this.data); 
          this.data = this.dataStates.pop(); 
          console.log("Undo works:", this.data);
      } else {
          console.log("Nothing to undo.");
      }
    } 

    redoLastTransformation() {
      if (this.redoStack.length > 0) {
          this.dataStates.push(this.data);
  
          this.data = this.redoStack.pop();
          console.log("Redo works:", this.data.objects());
      } else {
          console.log("Nothing to redo.");
      }
  }
  
  imputeAverage(column) {
    let condition = (d) => selectedIds.has(d.id) ? avg : d[column];

    this.dataStates.push(this.data);
    this.redoStack = [];
    this.dataTransformations.push(condition);
    this.transformationPoints.push(this.selectedPoints);

    console.log("Column: ", column);
    const columnValues = this.data.array(column).filter((v) => !isNaN(v) && v > 0);
    console.log("Column values: ", columnValues);
    const avg = columnValues.length > 0 
        ? parseFloat((columnValues.reduce((a, b) => a + b, 0) / columnValues.length).toFixed(1))
        : 0;
      
    console.log("Avg: ", avg);

    const selectedIds = new Set(this.selectedPoints.map(p => p.id));
    this.data = this.data.derive({ 
        [column]: aq.escape(condition)
    });

    console.log("Updated data:", this.data.objects());
  
  }
    setSelectedPoints(points) {
      this.selectedPoints = points;
    }
  
    getSelectedPoints() {
      return this.selectedPoints;
    }
  }