let activeDataset = "stackoverflow";
let stackoverflowController;
let cacheController;

import {getSampleData, uploadFileToDB} from './serverCalls.js';
import setIDColumn from "./tableFunction.js";


const selectedSample = localStorage.getItem("selectedSample");  // Dataset chosen by user
console.log("This is the selected ",selectedSample)
if (selectedSample){ // User selected one of the 3 available datasets

    // //add the selected file to the db first
    // console.log(selectedSample)
    // const fileToSend = new FormData();
    // fileToSend.append("file",selectedSample);
    //
    // let uploadFlag = uploadFileToDB(fileToSend);
    // // table was added to the db, now get the first 200
    // if(uploadFlag){
    //     let dataTableSample = getSampleData(selectedSample)
    //     console.log(dataTableSample);
    //     aq.table(dataTableSample);
    //     const processedTable = setIDColumn(dataTableSample);
    // }
    // OLD implementation
    d3.csv(selectedSample).then(inputData => {
    localStorage.removeItem("selectedSample");

    const table = setIDColumn(aq.from(inputData).slice(0, 200));    // Select only the first 200 rows to work with to speed up rendering time

    const fullTable = setIDColumn(aq.from(inputData).slice(0,1000)); // Run on full dataset, right now it's just 1k for dev time speedup
    d3.select("#matrix-vis-stackoverflow").html("");

    stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
    stackoverflowController.model.originalFilename = selectedSample;

    attachButtonEventListeners(stackoverflowController);

    // Export python script listener
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
        const detectorResponse = await fetch('/static/detectors/detectors.json');  // Updated path
        const detectors = await detectorResponse.json();

        const wranglerResponse = await fetch('/static/wranglers/wranglers.json');  // Updated path
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

    /**
     * Sends the uploaded file to the server to be added to the DB
     */
    const file = event.target.files[0];
    console.log("file", file);
    if (!file) return;
    const fileToSend = new FormData();
    fileToSend.append("file",file);

    uploadFileToDB(fileToSend);

    /**
     * On-browser functionality - old, but working
     */
    fetch('/data_cleaning_vis_tool') 
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

           //send the 
           const table = setIDColumn(aq.from(parsedData).slice(0, 200));
       
           d3.select("#matrix-vis-stackoverflow").html("");
       
           stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
           stackoverflowController.model.originalFilename = file.name;
       
           attachButtonEventListeners(stackoverflowController);
 
           // Export python script listener
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
                   const detectorResponse = await fetch('/static/detectors/detectors.json');
                   const detectors = await detectorResponse.json();
             
                   const wranglerResponse = await fetch('/static/wranglers/wranglers.json');
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