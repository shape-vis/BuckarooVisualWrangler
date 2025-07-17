


class TableView{
    constructor(container, model) {

        // this.matrixView = new MatrixView(container, model);

        this.container = container;
        this.model = model;

        // this.size = 180;                                                        // Size of each cell in matrix
        // this.xPadding = 175;
        // this.yPadding = 90;
        // this.labelPadding = 60;

        // this.leftMargin = 115;
        // this.topMargin = 0;
        // this.bottomMargin = 125; 
        // this.rightMargin = 0; 

        // this.xScale = d3.scaleLinear().domain([0, 100]).range([0, this.size]);  // Default xScale to be changed within plotting code
        // this.yScale = d3.scaleLinear().domain([0, 100]).range([this.size, 0]);  // Default yScale to be changed within plotting code

        // this.selectedPoints = [];                                               // The current user selection of points from interacting with the plots
        // this.predicatePoints = [];                                              // Predicate points do not meet the user's predicate condition and are outlined in red
        // this.viewGroupsButton = false;                                          // True when the user has selected an attribute to group by and the legend will update to show group colors instead of error colors

        this.errorColors = {                                                    // To be updated as new error detectors are added
            "mismatch": "hotpink",
            "missing": "saddlebrown",
            "anomaly": "red",
            "incomplete": "gray"
        };

        this.errorPriority = ["anomaly", "mismatch", "missing", "incomplete"];  // Preference given to which errors are highlighted if both are present in a row
    }

    /**
     * Populates the top 10 dirty rows table. Updates as the data is wrangled. Counts number of errors per row and displays in first column. Orders rows by most errors per row.
     * Highlights cells with the corresponding error color.
     * @param {*} data 
     * @returns 
     */
    updateDirtyRowsTable(data) {
        const columnErrors = this.model.getColumnErrors();
      
        // Count errors per row ID
        const rowErrorCounts = {};
        for (const col in columnErrors) {
          for (const id in columnErrors[col]) {
            if (!rowErrorCounts[id]) {
              rowErrorCounts[id] = { count: 0 };
            }
            rowErrorCounts[id].count += 1;          }
        }
      
        // Build full row objects with their error counts
        const fullData = data.objects().map(row => {
          const id = String(row.ID);
          return {
            ...row,
            __errorCount__: rowErrorCounts[id] ? rowErrorCounts[id].count : 0,
          };
        });
      
        // Sort by error count descending and take top 10
        const topRows = fullData
          .sort((a, b) => b.__errorCount__ - a.__errorCount__)
          .slice(0, 10);
      
        const wrapper = document.getElementById("dirty-rows-table-wrapper");
        wrapper.innerHTML = "";
      
        if (topRows.length === 0) {
          wrapper.innerHTML = "<p>No rows with errors found.</p>";
          return;
        }
      
        const table = document.createElement("table");
        table.id = "dirty-rows-table";
        table.style.borderCollapse = "collapse";
        table.style.width = "100%";
      
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
      
        const columns = ['Error Count', ...Object.keys(topRows[0]).filter(c => c !== '__errorCount__')];
      
        columns.forEach(col => {
          const th = document.createElement("th");
          th.textContent = col;
          th.style.border = "1px solid #ddd";
          th.style.padding = "6px";
          th.style.backgroundColor = "#f0f0f0";
          headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
      
        const tbody = document.createElement("tbody");
        topRows.forEach(row => {
          const tr = document.createElement("tr");
      
          columns.forEach(col => {
            const td = document.createElement("td");
      
            // Handle 'Error Count' column separately
            if (col === 'Error Count') {
              td.textContent = row.__errorCount__;
            } else {
              const cellValue = row[col];
              if (typeof cellValue === "string" && cellValue.length > 50) {
                  td.textContent = truncateText(cellValue, 50);
                  td.title = cellValue; // Show full value as tooltip
              } else {
                  td.textContent = cellValue;
              }
      
              // Color in cell if it has errors
              const errorList = columnErrors[col]?.[row.ID];
              if (errorList && errorList.length > 0) {
                const topErrorType = this.errorPriority.find(type => errorList.includes(type));
                td.style.backgroundColor = this.errorColors[topErrorType];
                td.style.color = "white";
              }
            }
      
            td.style.border = "1px solid #ddd";
            td.style.padding = "6px";
            tr.appendChild(td);
          });
      
          tbody.appendChild(tr);
        });
      
        table.appendChild(thead);
        table.appendChild(tbody);
        wrapper.appendChild(table);
    }      

}


