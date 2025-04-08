export default function detectDataTypeMismatch(table) {
    const result = {}; // { column: { id: errorType } }
  
    const numRows = table.numRows();
    const columns = table.columnNames();
  
    columns.forEach(column => {
      const typesCount = {};
  
      for (let i = 0; i < numRows; i++) {
        const value = table.get(i, column);
        const type = typeof value;
        typesCount[type] = (typesCount[type] || 0) + 1;
      }
  
      let majorityType = null;
      let maxCount = 0;
      for (const [type, count] of Object.entries(typesCount)) {
        if (count > maxCount) {
          majorityType = type;
          maxCount = count;
        }
      }
  
      for (let i = 0; i < numRows; i++) {
        const value = table.get(i, column);
        const valueType = typeof value;
        const rowId = table.get(i, 'ID');
  
        if (valueType !== majorityType) {
          if (!result[column]) result[column] = {};
          result[column][rowId] = "mismatch";
        }

        // result[column][table.get(i, 'ID')] = "mismatch"
      }
    });
  
    return result;
  }