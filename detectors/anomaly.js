export default function detectAnomaly(table) {
    console.log("here in anomaly detector");
    const result = {}; // { column: { id: errorType } }
  
    const numRows = table.numRows();
    const columns = table.columnNames().slice(1);
  
    columns.forEach(column => {
        const values = [];
        const ids = [];
    
        // Collect numeric values and their IDs
        for (let i = 0; i < numRows; i++) {
          const value = table.array(column).at(i);
          const id = table.array("ID").at(i);
          const parsed = parseFloat(value);
    
          if (!isNaN(parsed)) {
            values.push(parsed);
            ids.push(id);
          }
        }
    
        // Calculate mean and standard deviation
        const mean = d3.mean(values);
        const stdDev = d3.deviation(values);
    
        if (stdDev === 0 || stdDev === undefined) return; // avoid divide-by-zero
    
        // Check for outliers
        for (let i = 0; i < values.length; i++) {
          const val = values[i];
          const id = ids[i];
    
          if (Math.abs(val - mean) > 2 * stdDev) {
            if (!result[column]) result[column] = {};
            result[column][id] = "outlier";
            console.log(`Outlier found in column "${column}" for row ID ${id}:`, val);
          }
        }
      });
    
      return result;
  }