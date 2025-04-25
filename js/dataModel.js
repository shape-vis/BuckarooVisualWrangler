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
    this.originalFilename = null;
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
  
  filterData(condition, filterInfo=null) {
    console.log("condition", condition);
    this.dataStates.push(this.filteredData);
    this.redoStack = [];
    this.transformationPoints.push(this.selectedPoints);
    console.log("filterInfo", filterInfo);
    if (filterInfo) {
      this.dataTransformations.push({
        type: "remove",
        ...filterInfo,
      });
    }
    console.log("Data Transformations", this.dataTransformations);

    this.filteredData = this.filteredData.filter(aq.escape(condition));

    // Filter the data but keep all the columns in this dataset
    this.fullFilteredData = this.fullFilteredData.filter(aq.escape(condition));
  }

  // Transforms the data such as imputing average, etc.
  transformData(column, condition, transformInfo=null){
    this.dataStates.push(this.filteredData);
    this.redoStack = [];
    this.transformationPoints.push(this.selectedPoints);
    if (transformInfo) {
      this.dataTransformations.push({
        type: "transform",
        ...transformInfo,
      });
    }
    console.log("Data Transformations", this.dataTransformations);

    this.filteredData = this.filteredData.derive({ [column]: aq.escape(condition) });
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
      // console.log("Importing detector from:", path);
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
    // console.log("this.columnErrorMap", this.columnErrorMap);
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
  
    return result;
  }

  exportPythonScript() {
    const baseFilename = this.originalFilename.replace(/\.csv$/, '');
    const cleanedFilename = `${baseFilename}_cleaned.csv`;

    const lines = [
      "import pandas as pd",
      "",
      `# Load your dataset`,
      `df = pd.read_csv('${this.originalFilename}')`,
      "",
      "# Apply cleaning transformations"
    ];
  
    for (const step of this.dataTransformations) {
      console.log("step", step);
      const { type, ids, xCol, xVals, yCol, yVals, imputedColumn, value } = step;

      if(yCol)
      {
        // All (x, y) combinations for all selected points
        const uniqueXVals = [...new Set(xVals)];
        const uniqueYVals = [...new Set(yVals)];
        const conditions = [];
        for (const xVal of uniqueXVals) {
          for (const yVal of uniqueYVals) {
            const xCond = `df[${JSON.stringify(xCol)}] == ${JSON.stringify(xVal)}`;
            const yCond = `df[${JSON.stringify(yCol)}] == ${JSON.stringify(yVal)}`;
            conditions.push(`(${xCond} & ${yCond})`);
          }
        }

        const compoundCondition = conditions.join(" | "); // OR all the conditions

        if (type === "remove") {
          lines.push(`# Remove rows where any of ${xCol} × ${yCol} combinations match`);
          lines.push(`df = df[~(${compoundCondition})]`);
        } else if (type === "transform") {
          lines.push(`# Transform ${imputedColumn} where any of ${xCol} × ${yCol} combinations match`);
          lines.push(`df.loc[(${compoundCondition}), ${JSON.stringify(imputedColumn)}] = ${JSON.stringify(value)}`);
        }
        lines.push("");
      }
      else{
        const uniqueXVals = [...new Set(xVals)];
        const conditions = [];
        for (const xVal of uniqueXVals) {
          const xCond = `df[${JSON.stringify(xCol)}] == ${JSON.stringify(xVal)}`;
          conditions.push(`(${xCond})`);
        }
        const compoundCondition = conditions.join(" | "); 

        if (type === "remove") {
          lines.push(`# Remove rows where any of ${xCol} matches`);
          lines.push(`df = df[~(${compoundCondition})]`);
        } else if (type === "transform") {
          lines.push(`# Transform ${imputedColumn} where any of ${xCol} matches`);
          lines.push(`df.loc[(${compoundCondition}), ${JSON.stringify(imputedColumn)}] = ${JSON.stringify(value)}`);
        }
        lines.push("");
      }
    }

    lines.push("# Save cleaned dataset");
    lines.push(`df.to_csv('${cleanedFilename}', index=False)`);
  
    return {
      scriptContent: lines.join("\n"),
      filename: `${baseFilename}_cleaned.py`
    };
  }
}