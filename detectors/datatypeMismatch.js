export default function detectDataTypeMismatch(table) {
    console.log("here in mismatch detector");
    const result = {}; // { column: { id: errorType } }
  
    const numRows = table.numRows();
    const columns = table.columnNames().slice(1);
  
    columns.forEach(column => {
      const typesCount = {};
  
      for (let i = 0; i < numRows; i++) {
        const value = table.array(column).at(i);
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
        const value = table.array(column).at(i);
        const valueType = typeof value;
        const rowId = table.array('ID').at(i);

        const isNumeric = typeof value === "string" && /^\d+(\.\d+)?$/.test(value.trim());
  
        if (valueType !== majorityType || (majorityType !== "number" && isNumeric)) {
          if (!result[column]) result[column] = {};
          result[column][rowId] = "mismatch";
          console.log("mismatch found", value);
        }

      }
    });
    return result;
  }