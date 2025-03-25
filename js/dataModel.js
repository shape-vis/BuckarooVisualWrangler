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
    this.previewData = this.data;
    this.fullFilteredData = this.data;
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
      ) );
    } else {
      this.filteredData = selectedAttrData;
    }

    console.log("set filtered data", this.filteredData.objects());

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

  getFullFilteredData(){
    return this.fullFilteredData;
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

    // Filter the data but keep all the columns in this dataset
    this.fullFilteredData = this.fullFilteredData.filter(aq.escape(condition));
  }

  getPreviewData(condition) {
    return this.filteredData.filter(aq.escape(condition));
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

    const isNumeric = this.filteredData.array(column).some(v => typeof v === "number" && !isNaN(v));

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

  previewAverage(column) {
    const selectedIds = new Set(this.selectedPoints.map(p => p.ID));

    const isNumeric = this.filteredData.array(column).some(v => typeof v === "number" && !isNaN(v));

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

    return this.filteredData.derive({ 
      [column]: aq.escape(condition)
    });
  }

  setSelectedPoints(points) {
    this.selectedPoints = points;
  }

  getSelectedPoints() {
    return this.selectedPoints;
  }

  getColumnErrors() {
    const data = this.fullFilteredData.objects();
    const columns = this.fullFilteredData.columnNames().slice(1); 
    const errorsPerColumn = {};
  
    columns.forEach(col => {
      const values = data.map(row => row[col]);
      const errors = {};

      const total = values.length;
      const numericValues = values.filter(v => typeof v === "number" && !isNaN(v));

  
      // if (values.some(v => String(v) === "null" || String(v) === "none" || String(v) === "")) {
      //   errors.add("missing");
      // }

      const missingCount = values.filter(v => String(v) === "null" || String(v) === "none" || String(v) === "").length;
      if (missingCount > 0) errors.missing = missingCount / total;
  
      // const types = values.map(v => typeof v);
      // if (new Set(types).size > 1) {
      //   errors.add("incomplete");
      // }
      // if (values.some(v => String(v) === "0 years old")) {
      //   errors.add("incomplete");
      // }

      // const types = values.map(v => typeof v);
      // const majorityType = types.sort((a,b) =>
      //   types.filter(t => t === a).length - types.filter(t => t === b).length
      // ).pop();
      if (numericValues.length == 0) {
        const categoryCounts = {};
        values.forEach(v => {
          const key = String(v);
          categoryCounts[key] = (categoryCounts[key] || 0) + 1;
        });

        let infrequentCount = 0;
        for (const [key, count] of Object.entries(categoryCounts)) {
          if (count > 0 && count < 3) {
            infrequentCount += count;
          }
        }

        const totalIncomplete = infrequentCount;
        if (totalIncomplete > 0) errors.incomplete = totalIncomplete / total;
      }
  
      // const firstType = typeof values.find(v => v !== null && v !== undefined);
      // if (values.some(v => typeof v !== firstType)) {
      //   errors.add("mismatch");
      // }
      // if (values.some(v => ["billions", "seventy", "'0'", "'21.5'"].includes(v))) {
      //   errors.add("mismatch");
      // }
      const mismatchCount = values.filter(v => ["'00'", "'4'", "'0'", "'21.5'"].includes(v)).length;
      if (mismatchCount > 0) errors.mismatch = mismatchCount / total;
  
    //   const numericValues = values.filter(v => typeof v === "number" && !isNaN(v));
    //   if (numericValues.length > 0) {
    //     const mean = d3.mean(numericValues);
    //     const std = d3.deviation(numericValues);
    //     if (numericValues.some(v => Math.abs(v - mean) > 2 * std)) {
    //       errors.add("anomaly");
    //     }
    //   }
  
    //   errorsPerColumn[col] = Array.from(errors);
    // });
    if (numericValues.length > 0) {
      const mean = d3.mean(numericValues);
      const std = d3.deviation(numericValues);
      const anomalyCount = numericValues.filter(v => Math.abs(v - mean) > 2 * std).length;
      if (anomalyCount > 0) errors.anomaly = anomalyCount / total;
    }

    errorsPerColumn[col] = errors;
  });

    console.log("errospercolumn", errorsPerColumn);
  
    return errorsPerColumn;
  }
}