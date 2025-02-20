class DataModel {
    constructor(initialData) {
      this.originalData = initialData;
      this.data = this.preprocessData(initialData);
      // this.data = initialData;
      console.log("Cleaned Data: ", this.data.objects());
      this.selectedPoints = [];
      this.dataStates = [];
      this.redoStack = [];
      this.dataTransformations = [];
      this.transformationPoints = [];
    }

    preprocessData(table) {
      function parseValue(value) {
        if (typeof value === "number") return value; 

        if (typeof value === "string" && /^\d+(\.\d+)?$/.test(value.trim())) {
            return +value; 
        }

        return value; 
      }

      let tempArr = table.objects().map(row => {
        let newRow = { ...row }; 

        Object.keys(row).forEach(column => {
            newRow[column] = parseValue(row[column]); 
        });

        return newRow;
      });

      return aq.from(tempArr);
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
    this.dataStates.push(this.data);
    this.redoStack = [];

    console.log("Column: ", column);

    const selectedIds = new Set(this.selectedPoints.map(p => p.ID));

    const isNumeric = this.data.array(column).some(v => typeof v === "number" && !isNaN(v));

    let imputedValue;

    /// Calculate numeric average ///
    if(isNumeric){
      const columnValues = this.data.array(column).filter((v) => !isNaN(v) && v > 0);
      console.log("Column values: ", columnValues);
      imputedValue = columnValues.length > 0 
          ? parseFloat((columnValues.reduce((a, b) => a + b, 0) / columnValues.length).toFixed(1))
          : 0;
        
      console.log("Avg: ", imputedValue);
    }
    /// Calculate categorical mode ///
    else{
        const frequencyMap = this.data.array(column).reduce((acc, val) => {
            acc[val] = (acc[val] || 0) + 1;
            return acc;
        }, {});

        console.log("Category Frequency Map: ", frequencyMap);

        imputedValue = Object.keys(frequencyMap).reduce((a, b) =>
            frequencyMap[a] > frequencyMap[b] ? a : b
        );

        console.log("Computed Categorical Mode: ", imputedValue);
    }

    let condition = (d) => selectedIds.has(d.ID) ? imputedValue : d[column];
    this.dataTransformations.push(condition);
    this.transformationPoints.push(this.selectedPoints);

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