class CacheModel {
  constructor(initialData) {
    this.originalData = initialData;                // Maintain a copy of the original dataset
    this.data = this.preprocessData(initialData);   // Preprocessed data should contain all string values in string-majority columns
    this.columnErrorMap = {};                       // Mapping of every error in the dataset with its corresponding column and row ID
    this.nonColumnErrorMap = {};                    // Mapping of all the columns and rows without error
  }

  /**
   * 
   * @returns The full original dataset.
   */
  getFullData() {
    return this.data;
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
   * Loads and runs the detectors to build a column error map that contains all the error types and their associated IDs.
   * @param {*} detectors 
   */
  async runDetectors(detectors) {
    this.columnErrorMap = {};

    for (const detector of detectors) {
      const path = detector.code.startsWith("/") ? detector.code : `/${detector.code}`;
      const module = await import(path);
      const result = module.default(this.data);
  
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
    const totalRows = this.data.numRows();
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

  selectRandomNonErrorSubset(populationSize) {

    for (let i = 0;i<populationSize;i++) {
      let randomIndex = Math.floor(Math.random() * populationSize);

    }
  }

  createEmptyDataTable(data) {
    let columns = Object.keys(data[0]);
    let emptyRows = [];
    emptyRows.columns = columns;

  }
}