export default function detectMissingValue(table) {
    const result = {}; // { column: { id: errorType } }
  
    const numRows = table.numRows();
    const columns = table.columnNames().slice(1);
  
    columns.forEach(column => {
        for (let i = 0; i < numRows; i++) {
          const value = table.array(column).at(i);
          const rowId = table.array("ID").at(i);
    
          const isMissing =
            value === null ||
            value === undefined ||
            (typeof value === "string" && value.trim() === "") ||
            (typeof value === "string" && ["null", "undefined"].includes(value.trim().toLowerCase()));
    
          if (isMissing) {
            if (!result[column]) result[column] = {};
            result[column][rowId] = "missing";
          }
        }
      });
    
      return result;
  }