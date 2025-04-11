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
    this.columnErrorMap = {};
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
    function isNumeric(val) {
      return typeof val === "number" || (typeof val === "string" && /^\d+(\.\d+)?$/.test(val.trim()));
    }

    function parseValue(value) {
      if (typeof value === "number") return value; 
      if (typeof value === "string" && /^\d+(\.\d+)?$/.test(value.trim())) {
          return +value; 
      }
      return value; 
    }

    const rawData = table.objects();
    const columns = Object.keys(rawData[0] || {});

    // Step 1: Initial parsing
    let tempArr = rawData.map(row => {
      let newRow = {};
      for (let key of columns) {
        newRow[key] = parseValue(row[key]);
      }
      return newRow;
    });

    // Step 2: Determine majority type for each column
    let columnMajorTypes = {};
    for (let col of columns) {
      let numericCount = 0;
      let totalCount = 0;
      for (let row of tempArr) {
        if (row[col] !== null && row[col] !== undefined) {
          totalCount++;
          if (typeof row[col] === "number") numericCount++;
        }
      }
      columnMajorTypes[col] = numericCount > totalCount / 2 ? "numeric" : "non-numeric";
    }

    // Step 3: Convert numeric values to strings in non-numeric columns
    let finalArr = tempArr.map(row => {
      let newRow = { ...row };
      for (let col of columns) {
        if (columnMajorTypes[col] === "non-numeric" && typeof newRow[col] === "number") {
          newRow[col] = newRow[col].toString();
        }
      }
      return newRow;
    });

    return aq.from(finalArr);
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

  async runDetectors(detectors) {
    this.columnErrorMap = {}; // Reset
  
    for (const detector of detectors) {
      const path = detector.code.startsWith("/") ? detector.code : `/${detector.code}`;
      console.log("Importing detector from:", path);
      const module = await import(path);
      const result = module.default(this.filteredData);
  
      for (const [column, idErrorMap] of Object.entries(result)) {
        if (!this.columnErrorMap[column]) {
          this.columnErrorMap[column] = {};
        }
  
        for (const [id, errorType] of Object.entries(idErrorMap)) {
          if (!this.columnErrorMap[column][id]) {
            this.columnErrorMap[column][id] = [];
          }
          this.columnErrorMap[column][id].push(errorType);
        }
      }
    }
    console.log("this.columnErrorMap", this.columnErrorMap);
  }

  getColumnErrors() {
    return this.columnErrorMap;
  }

  getColumnErrorSummary() {
    const result = {}; // { column: { errorType: percent } }
    const totalRows = this.fullFilteredData.numRows();
    const errorMap = this.getColumnErrors();
  
    for (const [col, idErrors] of Object.entries(errorMap)) {
      const errorTypeCounts = {};
  
      for (const errorList of Object.values(idErrors)) {
        for (const errorType of errorList) {
          errorTypeCounts[errorType] = (errorTypeCounts[errorType] || 0) + 1;
        }
      }
  
      result[col] = {};
      for (const [type, count] of Object.entries(errorTypeCounts)) {
        result[col][type] = count / totalRows;
      }
    }
    console.log("Final summary:", result);

  
    return result;
  }
}