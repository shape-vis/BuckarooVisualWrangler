export default function detectAnomaly(table) {
    const result = {}; // { column: { id: errorType } }
  
    const numRows = table.numRows();
    const columns = table.columnNames().slice(1);
  
    columns.forEach(column => {
        const values = [];
        const ids = [];
    
        let numericCount = 0;
    
        for (let i = 0; i < numRows; i++) {
          const value = table.array(column).at(i);
          const id = table.array("ID").at(i);
    
          // Only accept actual numbers
          const isNumber = typeof value === "number";
          if (isNumber && !isNaN(value)) {
            values.push(value);
            ids.push(id);
            numericCount++;
          }
        }
    
        // Only treat as numeric if there are enough valid numbers
        if (numericCount < 10) return;
    
        const mean = d3.mean(values);
        const stdDev = d3.deviation(values);
    
        if (stdDev === 0 || stdDev === undefined) return; // Avoid divide by 0
    
        for (let i = 0; i < values.length; i++) {
          const val = values[i];
          const id = ids[i];
    
          if (Math.abs(val - mean) > 2 * stdDev) {
            if (!result[column]) result[column] = {};
            result[column][id] = "anomaly";
          }
        }
      });
    
      return result;
  }