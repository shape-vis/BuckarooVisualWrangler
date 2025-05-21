class DataModel {
  constructor(initialData) {
    this.originalData = initialData;                // Maintain a copy of the original dataset
    this.data = this.preprocessData(initialData);   // Preprocessed data should contain all string values in string-majority columns
    this.filteredData = this.data;                  // this.filtered data gets updated as the user removes and transforms the dataset
    this.selectedPoints = [];                       // The current user selection of points from interacting with the plots
    this.dataStates = [];                           // Keeps a history of each state of the data as it is transformed
    this.redoStack = [];                            // Tracks each state of the data for the undo/redo button
    this.dataTransformations = [];                  // Tracks each transformation/repair on the data to be used in the exported python script
    this.transformationPoints = [];                 // Tracks each selection of points the user applies a data transformation to
    this.selectedGroups = [];                       // Selected groups by the user from the box plots pop-up
    this.groupByAttribute = null;                   // Contains the attribute to group by if the user selects one
    this.previewData = this.data;                   // Keep a separate dataset for the preview plots
    this.fullFilteredData = this.data;              // Same as this.filtered data, except this holds all the columns, not just the 1-3 selected attributes
    this.columnErrorMap = {};                       // Mapping of every error in the dataset with its corresponding column and row ID
    this.originalFilename = null;                   // File name of the input data to be used in the exported python script
  }

  /**
   * Update the selected groups from the box and whisker plot.
   * @param {*} groups The selected groups to view.
   * @param {*} selectedAttributes The columns currently plotted.
   */
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

  /**
   * 
   * @returns The selected groups.
   */
  getSelectedGroups() {
    return this.selectedGroups;
  }

  /**
   * 
   * @returns The current dataset used for plotting.
   */
  getData() {
    return this.filteredData;
  }

  /**
   * 
   * @returns The full original dataset.
   */
  getFullData() {
    return this.data;
  }
  /**
   * 
   * @returns The filtered dataset but with all columns, not just the selected columns.
   */
  getFullFilteredData(){
    return this.fullFilteredData;
  }

  /**
   * Update the current dataset being plotted.
   * @param {*} filteredData 
   */
  setFilteredData(filteredData) {
    this.filteredData = filteredData;  
  } 
  
  /**
   * Set the user selected attribute to group data by.
   * @param {*} attribute 
   */
  setGroupByAttribute(attribute) {
    console.log("Grouping by:", attribute);
    this.groupByAttribute = attribute && attribute !== "None" ? attribute : null;
  }

  /**
   * 
   * @returns The user selected group by attribute.
   */
  getGroupByAttribute() {
    return this.groupByAttribute;
  }

  /**
   * Preprocess the data by finding the majority type of each column and converting numeric vals to strings in non-numeric columns
   * @param {*} table 
   * @returns The preprocessed Arquero table.
   */
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

    // Initial parsing
    let tempArr = rawData.map(row => {
      let newRow = {};
      for (let key of columns) {
        newRow[key] = parseValue(row[key]);
      }
      return newRow;
    });

    // Determine majority type for each column
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

    // Convert numeric values to strings in non-numeric columns
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
  
  /**
   * Removes data from this.filteredData according to user selection and removal of data.
   * @param {*} condition The Arquero filtering condition.
   * @param {*} filterInfo Info to be passed to the export script function.
   */
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

    this.filteredData = this.filteredData.filter(aq.escape(condition));

    // Filter the data but keep all the columns in this dataset
    this.fullFilteredData = this.fullFilteredData.filter(aq.escape(condition));
  }

  /**
   * Transforms the data such as imputing average, etc.
   * @param {*} column The column where the values are being imputed.
   * @param {*} condition The Arquero condition.
   * @param {*} transformInfo Info to be passed to the export script function.
   */
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

    this.filteredData = this.filteredData.derive({ [column]: aq.escape(condition) });
  }

  /**
   * Returns a preview of the dataset if a user takes a specific wrangling action.
   * @param {*} condition 
   * @returns Preview dataset
   */
  getPreviewData(condition) {
    return this.filteredData.filter(aq.escape(condition));
  }

  /**
   * Method behind the undo button. Restores the previous state of the dataset.
   */
  undoLastTransformation() {
    if (this.dataStates.length > 0) {
        this.redoStack.push(this.filteredData); 
        this.filteredData = this.dataStates.pop(); 
        console.log("Undo works:", this.filteredData);
    } else {
        console.log("Nothing to undo.");
    }
  } 

  /**
   * Method behind the redo button. Restores the previous state of the data.
   */
  redoLastTransformation() {
    if (this.redoStack.length > 0) {
        this.dataStates.push(this.filteredData);

        this.filteredData = this.redoStack.pop();
        console.log("Redo works:", this.filteredData.objects());
    } else {
        console.log("Nothing to redo.");
    }
  }

  /**
   * Calculates averages for the preview plots.
   * @param {*} column 
   * @returns The preview dataset with the imputations.
   */
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

  /**
   * Sets selected points as a result of the user's selection.
   * @param {*} points 
   */
  setSelectedPoints(points) {
    this.selectedPoints = points;
  }

  /**
   * 
   * @returns The user selected points.
   */
  getSelectedPoints() {
    return this.selectedPoints;
  }

  /**
   * Loads and runs the detectors to build a column error map that contains all the error types and their associated IDs.
   * @param {*} detectors 
   */
  async runDetectors(detectors) {
    this.columnErrorMap = {};
  
    for (const detector of detectors) {
      const path = detector.code.startsWith("/") ? detector.code : `/${detector.code}`;
      const loc = window.location.href;
      const dir = loc.substring(0, loc.lastIndexOf('/'));
      console.log("detector path", loc, dir, path);
      const module = await import(dir + path);
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
  }

  /**
   * 
   * @returns The error mapping.
   */
  getColumnErrors() {
    return this.columnErrorMap;
  }

  /**
   * Creates a column error summary to be used for the attribute summaries.
   * @returns 
   */
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

  /**
   * Convert data transformations from Arquero to Python and writes a Python script to export.
   * @returns The written script and its filename.
   */
  exportPythonScript() {
    const baseFilename = this.originalFilename.replace(/\.csv$/, '');
    const cleanedFilename = `${baseFilename}_cleaned.csv`;

    const lines = [
      "import pandas as pd",
      "",
      `# Load your dataset`,
      `df = pd.read_csv('${this.originalFilename}')`,
      `df = df.head(200)  # Select only the first 200 rows`,    // This can be adjusted as needed. Currenly, the script only takes the first 200 rows to visualize, 
                                                                // so if that changes in the script, it should also be changed here for consistency.
      "",
      "# Apply cleaning transformations"
    ];
  
    for (const step of this.dataTransformations) {
      console.log("step", step);
      const { type, ids, xCol, xVals, yCol, yVals, imputedColumn, value, idErrors } = step;

      const error = Object.values(idErrors).flat()[0]; // The first item should be the error type

      if(yCol)
      {
        // All (x, y) combinations for all selected points on a HEATMAP
        const uniqueXVals = [...new Set(xVals)];
        const uniqueYVals = [...new Set(yVals)];
        const conditions = [];
        for (const xVal of uniqueXVals) {
          for (const yVal of uniqueYVals) {
            const xCond = `df[${JSON.stringify(xCol)}] == ${JSON.stringify(xVal)}`;
            const yCond = `df[${JSON.stringify(yCol)}] == ${JSON.stringify(yVal)}`;
            conditions.push(`((${xCond}) & (${yCond}))`);
          }
        }

        const compoundCondition = `(\n  ${conditions.join(" |\n  ")}\n)`;   // OR conditions

        if (type === "remove") {
          lines.push(`# Remove rows where any of ${xCol} x ${yCol} combinations match ${xVals[0]} x ${yVals[0]}`);
          lines.push(`df = df[~(${compoundCondition})]    # Error Type: ${error}`);
        } else if (type === "transform") {
          lines.push(`# Transform ${imputedColumn} with ${value} where ${xCol} = ${xVals[0]} and ${yCol} = ${yVals[0]}`);
          lines.push(`df.loc[(${compoundCondition}), ${JSON.stringify(imputedColumn)}] = ${JSON.stringify(value)}   # Error Type: ${error}`);
        }
        lines.push("");
      }
      else{
        // Selected points were on a HISTOGRAM (no yCol or yVals)
        const uniqueXVals = [...new Set(xVals)];
        const conditions = [];
        for (const xVal of uniqueXVals) {
          const xCond = `df[${JSON.stringify(xCol)}] == ${JSON.stringify(xVal)}`;
          conditions.push(`(${xCond})`);
        }
        const compoundCondition = `(\n  ${conditions.join(" |\n  ")}\n)`;

        if (type === "remove") {
          lines.push(`# Remove rows where any of ${xCol} = ${xVals[0]}`);
          lines.push(`df = df[~(${compoundCondition})]   # Error Type: ${error}`);
        } else if (type === "transform") {
          lines.push(`# Transform ${imputedColumn} with ${value} where ${xCol} = ${xVals[0]}`);
          lines.push(`df.loc[(${compoundCondition}), ${JSON.stringify(imputedColumn)}] = ${JSON.stringify(value)}   # Error Type: ${error}`);
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