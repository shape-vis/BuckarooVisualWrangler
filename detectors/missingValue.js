export default function detectDataTypeMismatch(table) {
    console.log("here in missing value detector");
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
            console.log(`Missing value found in column "${column}" for row ID ${rowId}:`, value);
          }
        }
      });
    
      return result;
  }