let activeDataset = "stackoverflow";
let stackoverflowController;
let cacheController;

import {getSampleData, uploadFileToDB} from './serverCalls.js';
import setIDColumn from "./tableFunction.js";


const userUploaded = localStorage.getItem("userUploaded");
const selectedSample = localStorage.getItem("selectedSample");  // Dataset chosen by user

// User selected one of the 3 available datasets
if (userUploaded === "no"){
    console.log("This is the pre-selected dataset by the user",selectedSample)
    await userChoseProvidedDataset(selectedSample);
}
// User elected to upload their own dataset
if(userUploaded === "yes"){
    await userUploadedDataset(selectedSample);
}

async function userChoseProvidedDataset(selectedSample) {

    let justTheFilename = selectedSample.substring(13, selectedSample.length);
    let dataSize = 200;
    const inputData = await getSampleData(justTheFilename,dataSize);

    // Convert JSON to Arquero table directly
    const table = setIDColumn(aq.from(inputData));
    initController(false, table, selectedSample);
}

async function userUploadedDataset(fileName) {

    /**
     * On-browser functionality - old, but working
     */
    await fetch("/data_cleaning_vis_tool")
        .then(response => response.text())
        .then(async html => {
            document.body.innerHTML = html;
            console.log(html);
            let dataSize = 200;
            const inputData = await getSampleData(fileName,dataSize);

            console.log("view data from db:", inputData);
            if (!inputData) return;

            const table = setIDColumn(aq.from(inputData));
            initController(true, table, fileName);


        })
        .catch(error => {
            console.error('Error fetching HTML:', error);
        });
    // });
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
        const exportBtn = document.getElementById("export-script");
        if(exportBtn) {
            exportBtn.addEventListener('click', handleExport);
        }
        else console.error('Export button not found');
    }

function handleExport(controller){
    const {scriptContent, filename} = controller.model.exportPythonScript();
            const blob = new Blob([scriptContent], {type: "text/x-python"});
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
}


