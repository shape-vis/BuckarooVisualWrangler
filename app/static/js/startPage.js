let activeDataset = "stackoverflow";
let stackoverflowController;
let cacheController;

import {getSampleData, uploadFileToDB} from './serverCalls.js';
import setIDColumn from "./tableFunction.js";

const selectedSample = localStorage.getItem("selectedSample");  // Dataset chosen by user
console.log("This is the selected ",selectedSample)

// User selected one of the 3 available datasets
if (selectedSample){
    userChoseProvidedDataset(selectedSample);
}
// User elected to upload their own dataset
else{
    userUploadedDataset();

}

function userChoseProvidedDataset(selectedDatasetPath){
    d3.csv(selectedSample).then(inputData => {
    localStorage.removeItem("selectedSample");

    const table = setIDColumn(aq.from(inputData).slice(0, 200));    // Select only the first 200 rows to work with to speed up rendering time

    const fullTable = setIDColumn(aq.from(inputData).slice(0,1000)); // Run on full dataset, right now it's just 1k for dev time speedup
        initController(false,table,selectedSample);
  });
}

function startDBFileUpload(uploadEvent){
    /**
     * Sends the uploaded file to the server to be added to the DB
     */
    const file = uploadEvent.target.files[0];
    console.log("file", file);
    if (!file) return;
    const fileToSend = new FormData();
    fileToSend.append("file",file);

    uploadFileToDB(fileToSend);
}

function userUploadedDataset(){
    document.getElementById('fileInput').addEventListener('change', function (event) {

        startDBFileUpload(event);

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
           initController(true, table, file.name);
         };

         reader.readAsText(file);
       })
       .catch(error => {
         console.error('Error fetching HTML:', error);
       });
 });
}

function initController(userUploadedFile, table, fileName){
    d3.select("#matrix-vis-stackoverflow").html("");
    stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");

    if(userUploadedFile) {
        stackoverflowController.model.originalFilename = fileName;
    }
    attachButtonEventListeners(stackoverflowController);
    exportPythonScriptListener(stackoverflowController);
    initWranglersDetectors(stackoverflowController);
}

/**
 * Loads the detectors and wranglers into the controller
 * @param controller
 */
function initWranglersDetectors(controller){
    (async () => {
        try {
            const detectorResponse = await fetch('/static/detectors/detectors.json');
            const detectors = await detectorResponse.json();

            const wranglerResponse = await fetch('/static/wranglers/wranglers.json');
            const wranglers = await wranglerResponse.json();

            await controller.init(detectors, wranglers);
                } catch (err) {
                    console.error("Failed to load or run detectors:", err);
                }
        })();
}

/**
 * Exports into a python script
 * @param controller
 */
function exportPythonScriptListener(controller){
    // Export python script listener
    document.getElementById("export-script").addEventListener("click", function () {
      const { scriptContent, filename } = controller.model.exportPythonScript();
      const blob = new Blob([scriptContent], { type: "text/x-python" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    });
}

