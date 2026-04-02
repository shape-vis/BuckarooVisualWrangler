import React, { useMemo } from "react";
import { useEffect, useState } from "react";
import { queryTopErrorRows } from "../utils/serverCalls.jsx";
import CollapsiblePanel from "../elements/CollapsiblePanel";
import { truncateText } from "../utils/textUtils.js";
import { useTableName } from "../utils/TableNameContext.jsx";
import { useLoading } from "../utils/LoadingContext.jsx";
import "../styles/TablePanel.css";

function RowHeader({ columns }) {
  return (
    <thead>
      <tr>
        {columns.map(col => (
          <th key={col}>
            {col}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function TableRow({tableData, rowIndex, columns, errorData}) {

  // Priority order for determining which error drives the cell color
  const errorPriority = ["mismatch", "missing", "anomaly", "incomplete"];

  return (
    <tr key={`row${rowIndex}`}>
    {
      columns.map((col) => {
        const key = col + "_" + (tableData?.["ID"]?.[rowIndex] ?? rowIndex);
        const errors = errorData[key] ? errorData[key] : [];
        const cellValue = tableData[col][rowIndex];

        // Pick the highest-priority error for the data attribute
        const primaryError = errorPriority.find(e => errors.includes(e)) || null;

          return (
            <td
              key={`${rowIndex}-${col}`}
              data-error={primaryError}
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
export default function TablePanel({ sortedAttributes, maxRows = 10 }) {
  const { tableName: table_name } = useTableName();
  const { addLoader, removeLoader } = useLoading();

  const [tableData, setTableData] = useState(null);
  const [errorData, setErrorData] = useState(null);
  const [fetchError, setFetchError] = useState(null);

  useEffect(() => {

    async function fetchData(){
        setFetchError(null);
        addLoader();
        try {

          const response = await queryTopErrorRows(maxRows);
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
        } finally {
          removeLoader();
        }
      }

      fetchData();

  }, [table_name, maxRows]);  


  return (
    <CollapsiblePanel collapsed={`Top ${maxRows} Rows with Most Errors`} direction="down" defaultOpen={true} className="panel--table">
      <div id="table-div">
        <div className="table-title">
          Top {maxRows} Rows with Most Errors
        </div>

        <div id="table-container">
          {fetchError ? (
            <div className="table-error-message">Error: {fetchError}</div>
          ) : (!tableData || !errorData) ? (
            <div className="table-loading-message">Loading…</div>
          ) : (
            <table id="table">
              <RowHeader columns={sortedAttributes}/>
              <TableBody columns={sortedAttributes} tableData={tableData} numRows={maxRows} errorData={errorData} />
            </table>
          )}
        </div>
      </div>
    </CollapsiblePanel>

  )
}
