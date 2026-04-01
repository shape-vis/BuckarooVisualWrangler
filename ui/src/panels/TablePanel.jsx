import React, { useMemo } from "react";
import { useEffect, useState } from "react";
import { queryTopErrorRows } from "../utils/serverCalls.jsx";
import CollapsiblePanel from "../elements/CollapsiblePanel";
import { truncateText } from "../utils/textUtils.js";

function RowHeader({ columns }) {
  return (
    <thead>
      <tr>
        {columns.map(col => (
          <th
            key={col}
            style={{ border: "1px solid #ddd", padding: 6, backgroundColor: "#f0f0f0", textAlign: "left" }}
          >
            {col}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function TableRow({tableData, rowIndex, columns, errorData}) {

  // error colors / priority copied from original
  const errorColors = {
    mismatch: ["black", "hotpink"],
    missing: ["white", "saddlebrown"],
    anomaly: ["white", "red"],
    incomplete: ["white", "gray"],
  };  

  return (
    <tr key={`row${rowIndex}`}>
    {
      columns.map((col) => {
        // const key = col + "_" + tableData["ID"][rowIndex];
        const key = col + "_" + (tableData?.["ID"]?.[rowIndex] ?? rowIndex);
        const errors = errorData[key] ? errorData[key] : [];
        const cellValue = tableData[col][rowIndex];

        let bg_color = "white";
        let fg_color = "black";

        errors.forEach( errorType => {
          if (errorColors[errorType]) {
            fg_color = errorColors[errorType][0];
            bg_color = errorColors[errorType][1];
          }
        });

          return (
            <td
              key={`${rowIndex}-${col}`}
              style={{ border: "1px solid #ddd", padding: 6, backgroundColor: bg_color, color: fg_color }}
              title={cellValue}
            >
              {truncateText(cellValue, 25)}
            </td>       
          );
      }) 
    } 
    </tr>
  )

}

function TableBody({ columns, tableData, numRows, errorData}) {

  const rowIndices = Array.from({ length: numRows }, (_, i) => i);
  
  return (
        <tbody>
          {
            rowIndices.map( rowIdx => { 
              return (<TableRow tableData={tableData} rowIndex={rowIdx} columns={columns} errorData={errorData} />)
            })
          }
        </tbody>    
  );
}

/**
 * TableView React component
 * Props:
 *  - model: an object exposing getColumnErrors() and dataSource with objects() method (same expectations as original TableView)
 *  - maxRows (optional): number of top rows to show (default 10)
 */
export default function TablePanel({ table_name, sortedAttributes, maxRows = 10 }) {

  const [tableData, setTableData] = useState(null);
  const [errorData, setErrorData] = useState(null);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {

    async function fetchData(){
        setFetchError(null);
        try {

          const response = await queryTopErrorRows(table_name, maxRows);
          console.log("[TablePanel] Response:", response);

          if (!response || !response.success) {
            throw new Error(`[TablePanel] API call failed: ${response?.error || "Unknown error"}`);
          }

          setTableData(response.table);

          let errorDict = {};
          const errorKeys = Object.keys(response.errors.row_id || response.errors.index || {});
          for( let idx of errorKeys ){
            const key = response.errors.column_id[idx] + "_" + response.errors.row_id[idx];

            if (!errorDict[key]) {
              errorDict[key] = [];
            }

            errorDict[key].push(response.errors.error_type[idx]);
          }
          setErrorData(errorDict);

        } catch (err) {
          console.error(err?.message || err);
          setFetchError(err?.message || String(err));
        }
      }

      fetchData();

  }, [table_name, maxRows]);  


  return (
    <CollapsiblePanel collapsed={`Top ${maxRows} Rows with Most Errors`} direction="down" defaultOpen={true} style={{width: "100%"}}>
      <div id="table-div">
        <div style={{ fontWeight: "bold", textAlign: "center" }}>
          Top {maxRows} Rows with Most Errors
        </div>
        
        <div id="table-container">
          {fetchError ? (
            <div style={{ padding: 12, color: "red", fontSize: 12 }}>Error: {fetchError}</div>
          ) : (!tableData || !errorData) ? (
            <div style={{ padding: 12, color: "#888", fontSize: 12 }}>Loading…</div>
          ) : (
            <table id="table" style={{ borderCollapse: "collapse", width: "100%" }}>
              <RowHeader columns={sortedAttributes}/>
              <TableBody columns={sortedAttributes} tableData={tableData} numRows={maxRows} errorData={errorData} />
            </table>
          )}
        </div>
      </div>
    </CollapsiblePanel>

  )
}
