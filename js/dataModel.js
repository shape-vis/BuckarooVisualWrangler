class DataModel {
  constructor(initialData) {
    this.originalData = initialData;
    this.data = this.preprocessData(initialData);
    this.filteredData = this.data;
    // this.data = initialData;
    this.selectedPoints = [];
    this.dataStates = [];
    this.redoStack = [];
    this.dataTransformations = [];
    this.transformationPoints = [];
    this.selectedGroups = [];
    this.groupByAttribute = null;
  }

  // New method to update the selected groups:
  setSelectedGroups(groups, selectedAttributes) {
    this.selectedGroups = groups;  
    const selectedColumns = new Set([...selectedAttributes]); 
        if (this.groupByAttribute && !selectedColumns.has(this.groupByAttribute)) {
            selectedColumns.add(this.groupByAttribute);  
        }

    const selectedAttrData = this.getFullData().select([...selectedColumns])

    const groupByCol = this.groupByAttribute; 
    if (groupByCol && groups && groups.length > 0) {
      this.filteredData = selectedAttrData.filter(aq.escape(d =>
        groups.includes(d[groupByCol])
      ));
    } else {
      this.filteredData = selectedAttrData;
    }
  }
  getSelectedGroups() {
    return this.selectedGroups;
  }

  getData() {
    return this.filteredData;
  }

  getFullData() {
    return this.data;
  }

  setFilteredData(filteredData) {
    this.filteredData = filteredData;  
  } 
  
  setGroupByAttribute(attribute) {
    console.log("Grouping by:", attribute);
    this.groupByAttribute = attribute && attribute !== "None" ? attribute : null;
  }

  getGroupByAttribute() {
    return this.groupByAttribute;
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
  
  filterData(condition) {
    this.dataStates.push(this.filteredData);
    this.redoStack = [];
    this.dataTransformations.push(condition);
    this.transformationPoints.push(this.selectedPoints);
    this.filteredData = this.filteredData.filter(aq.escape(condition));
  }

  undoLastTransformation() {
    if (this.dataStates.length > 0) {
        this.redoStack.push(this.filteredData); 
        this.filteredData = this.dataStates.pop(); 
        console.log("Undo works:", this.filteredData);
    } else {
        console.log("Nothing to undo.");
    }
  } 

  redoLastTransformation() {
    if (this.redoStack.length > 0) {
        this.dataStates.push(this.filteredData);

        this.filteredData = this.redoStack.pop();
        console.log("Redo works:", this.filteredData.objects());
    } else {
        console.log("Nothing to redo.");
    }
  }
  
  imputeAverage(column) {
    this.dataStates.push(this.filteredData);
    this.redoStack = [];

    console.log("Column: ", column);

    const selectedIds = new Set(this.selectedPoints.map(p => p.ID));

    const isNumeric = this. filteredData.array(column).some(v => typeof v === "number" && !isNaN(v));

    let imputedValue;

    /// Calculate numeric average ///
    if(isNumeric){
      const columnValues = this.filteredData.array(column).filter((v) => !isNaN(v) && v > 0);
      console.log("Column values: ", columnValues);
      imputedValue = columnValues.length > 0 
          ? parseFloat((columnValues.reduce((a, b) => a + b, 0) / columnValues.length).toFixed(1))
          : 0;
        
      console.log("Avg: ", imputedValue);
    }
    /// Calculate categorical mode ///
    else{
        const frequencyMap = this.filteredData.array(column).reduce((acc, val) => {
            acc[val] = (acc[val] || 0) + 1;
            return acc;
        }, {});

        imputedValue = Object.keys(frequencyMap).reduce((a, b) =>
            frequencyMap[a] > frequencyMap[b] ? a : b
        );

        console.log("Computed Categorical Mode: ", imputedValue);
    }

    let condition = (d) => selectedIds.has(d.ID) ? imputedValue : d[column];
    this.dataTransformations.push(condition);
    this.transformationPoints.push(this.selectedPoints);

    this.filteredData = this.filteredData.derive({ 
      [column]: aq.escape(condition)
    });

  }
    setSelectedPoints(points) {
      this.selectedPoints = points;
    }
  
    getSelectedPoints() {
      return this.selectedPoints;
    }
  }