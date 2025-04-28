let activeDataset = "stackoverflow";
let stackoverflowController;

/**
 * Adds an ID column into the first index of the table to be used throughout in selection, wrangling, etc.
 * @param {*} table Data
 * @returns Data with ID column added if needed
 */
function setIDColumn(table) {
  const colNames = table.columnNames();
  const hasID = colNames.includes("ID");

  if (!hasID) {
    // Add new numeric ID column starting from 1
    const idArray = Array.from({ length: table.numRows() }, (_, i) => i + 1);
    const withID = table.assign({ ID: idArray });
    return withID.select(['ID', ...withID.columnNames().filter(col => col !== 'ID')]);
  }

  // ID exists — check if it's numeric and unique
  const idValues = table.array("ID");
  const isNumeric = idValues.every(val => typeof val === "number" || (!isNaN(val) && val.trim() !== ""));
  const isUnique = new Set(idValues).size === idValues.length;

  if (!isNumeric || !isUnique) {
    // Preserve original ID column, create new numeric ID
    const idArray = Array.from({ length: table.numRows() }, (_, i) => i + 1);
    let withBackup = table.rename({ ID: "Original_ID" });
    let withNewID = withBackup.assign({ ID: idArray });
    return withNewID.select(['ID', ...withNewID.columnNames().filter(col => col !== 'ID')]);
  }

  // ID is good, just move it to the front if needed
  if (colNames[0] !== "ID") {
    return table.select(["ID", ...colNames.filter(c => c !== "ID")]);
  }

  // Already in first position and valid
  return table;
}

const selectedSample = localStorage.getItem("selectedSample");  // Dataset chosen by user
if (selectedSample) {
  d3.csv(selectedSample).then(inputData => {
    localStorage.removeItem("selectedSample");

    const table = setIDColumn(aq.from(inputData).slice(0, 200));
    d3.select("#matrix-vis-stackoverflow").html("");

    stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
    stackoverflowController.model.originalFilename = selectedSample;

    attachButtonEventListeners(stackoverflowController);

    document.getElementById("export-script").addEventListener("click", function () {
      const { scriptContent, filename } = stackoverflowController.model.exportPythonScript();
      const blob = new Blob([scriptContent], { type: "text/x-python" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url); 
    });

    (async () => {
      try {
        const detectorResponse = await fetch('/data/detectors.json');
        const detectors = await detectorResponse.json();

        const wranglerResponse = await fetch('/data/wranglers.json');
        const wranglers = await wranglerResponse.json();

        await stackoverflowController.init(detectors, wranglers);
      } catch (err) {
        console.error("Failed to load or run detectors:", err);
      }
    })();
  });
}
else{       // User elected to upload their own dataset
  document.getElementById('fileInput').addEventListener('change', function (event) {

    fetch('data_cleaning_vis_tool.html') 
       .then(response => response.text())
       .then(html => {
         document.body.innerHTML = html;
         
         const file = event.target.files[0];
         console.log("file", file);
         if (!file) return;
             
         const reader = new FileReader();
       
         reader.onload = function (e) {
           const contents = e.target.result;
           const parsedData = d3.csvParse(contents);
           const table = setIDColumn(aq.from(parsedData).slice(0, 200));
       
           d3.select("#matrix-vis-stackoverflow").html("");
       
           stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
           stackoverflowController.model.originalFilename = file.name;
       
           attachButtonEventListeners(stackoverflowController);
 
           // Export python script
           document.getElementById("export-script").addEventListener("click", function () {
             console.log("Exporting script");
             const { scriptContent, filename } = stackoverflowController.model.exportPythonScript();
 
             const blob = new Blob([scriptContent], { type: "text/x-python" });
             const url = URL.createObjectURL(blob);
 
             const a = document.createElement("a");
             a.href = url;
             a.download = filename;
             a.click();
 
             URL.revokeObjectURL(url); 
           });
 
           (async () => {
                 try {
                   const detectorResponse = await fetch('/data/detectors.json');
                   const detectors = await detectorResponse.json();
             
                   const wranglerResponse = await fetch('/data/wranglers.json');
                   const wranglers = await wranglerResponse.json();
               
                   await stackoverflowController.init(detectors, wranglers);
                 } catch (err) {
                   console.error("Failed to load or run detectors:", err);
                 }
               })();    
         };
       
         reader.readAsText(file);         
       })
       .catch(error => {
         console.error('Error fetching HTML:', error);
       });
 });
}