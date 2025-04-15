export default function detectIncompleteData(table) {
    const result = {}; // { column: { id: errorType } }
  
    const numRows = table.numRows();
    const columns = table.columnNames().slice(1);
  
    columns.forEach(column => {
        const valueCounts = {};
        const valueToIds = {};
    
        for (let i = 0; i < numRows; i++) {
          const value = table.array(column).at(i);
          const id = table.array("ID").at(i);
    
          // Skip null/undefined/empty
          if (value === null || value === undefined || value === "") continue;
    
          // Only process non-numeric values 
          if (typeof value === "number") continue;
    
          const category = String(value).trim();
    
          valueCounts[category] = (valueCounts[category] || 0) + 1;
          if (!valueToIds[category]) valueToIds[category] = [];
          valueToIds[category].push(id);
        }
    
        // Flag categories that appear fewer times than threshold
        for (const [category, count] of Object.entries(valueCounts)) {
          if (count < 3) {
            for (const id of valueToIds[category]) {
              if (!result[column]) result[column] = {};
              result[column][id] = "incomplete";
            }
          }
        }
      });
    
      return result;
  }