export default function imputeAverage(column, table, selectedPoints) {
    console.log("here in imputeAverage wrangler");
    console.log("Column: ", column);
  
    const selectedIds = new Set(selectedPoints.map(p => p.ID));
    const isNumeric = table.array(column).some(v => typeof v === "number" && !isNaN(v));
  
    let imputedValue;
  
    /// Calculate numeric average ///
    if (isNumeric) {
      const columnValues = table.array(column).filter((v) => !isNaN(v) && v > 0);
      console.log("Column values: ", columnValues);
      imputedValue = columnValues.length > 0
        ? parseFloat((columnValues.reduce((a, b) => a + b, 0) / columnValues.length).toFixed(1))
        : 0;
  
      console.log("Avg: ", imputedValue);
    }
    /// Calculate categorical mode ///
    else {
      const frequencyMap = table.array(column).reduce((acc, val) => {
        acc[val] = (acc[val] || 0) + 1;
        return acc;
      }, {});
  
      imputedValue = Object.keys(frequencyMap).reduce((a, b) =>
        frequencyMap[a] > frequencyMap[b] ? a : b
      );
  
      console.log("Computed Categorical Mode: ", imputedValue);
    }
  
    return (d) => selectedIds.has(d.ID) ? imputedValue : d[column];
  }