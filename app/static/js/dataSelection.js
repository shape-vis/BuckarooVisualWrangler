/**
 * The objective of this script is to manage the flow and initialization of the view and the interactions it has with the server and the database
 *
 */

let activeDataset = "stackoverflow";
let stackoverflowController;
let cacheController;

import {getSampleData, uploadFileToDB,getErrorData} from './serverCalls.js';
import setIDColumn from "./tableFunction.js";


const userUploaded = localStorage.getItem("userUploaded");
const selectedSample = localStorage.getItem("selectedSample");  // Dataset chosen by user
const minID = parseInt(localStorage.getItem("minIDVal"));
const maxID = parseInt(localStorage.getItem("maxIDVal"));
const useDB = localStorage.getItem("useDatabase") === "true";

// User selected one of the 3 available datasets
if (userUploaded === "no"){
    console.log("This is the pre-selected dataset by the user",selectedSample)
    await userChoseProvidedDataset(selectedSample,minID,maxID,useDB);
}
// User elected to upload their own dataset
if(userUploaded === "yes"){
    await userUploadedDataset(selectedSample,minID,maxID,useDB);
}

/**
 * Handler for when the user chose one of the provided datasets on the index.html page
 * @param selectedSample the name of the file they selected
 * @param minID the smallest ID to select from the csv - these are more the min/max windows of the dataset to select
 * @param maxID the largest ID to select from the csv
 * @param useDB flag which determines whether the routes should be used that operate on the database or on dataframes
 * @returns {Promise<void>}
 */
async function userChoseProvidedDataset(selectedSample,minID,maxID,useDB) {

    let justTheFilename = selectedSample.substring(13, selectedSample.length);
    let dataSize = maxID;
    const inputData = await getSampleData(justTheFilename,dataSize);
    const errorData = await getErrorData(justTheFilename,dataSize)
    // Convert JSON to Arquero table directly
    const table = setIDColumn(aq.from(inputData));
    prepForControllerInit(false, table, selectedSample,errorData,minID,maxID,useDB);
}

/**
 * Handler for when the user uploadd a dataset on the index.html page
 * @param fileName the name of the file they uploaded
 * @param minID the smallest ID to select from the csv - these are more the min/max windows of the dataset to select
 * @param maxID the largest ID to select from the csv
 * @param useDB flag which determines whether the routes should be used that operate on the database or on dataframes
 * @returns {Promise<void>}
 */
async function userUploadedDataset(fileName,minID,maxID,useDB) {
    /**
     * On-browser functionality - old, but working
     */
    await fetch("/data_cleaning_vis_tool")
        .then(response => response.text())
        .then(async html => {
            document.body.innerHTML = html;
            console.log(html);
            let dataSize = maxID;
            const inputData = await getSampleData(fileName,dataSize);
            const errorData = await getErrorData(fileName,dataSize)
            if (!inputData) return;

            const table = setIDColumn(aq.from(inputData));
            prepForControllerInit(true, table, fileName,errorData,minID,maxID,useDB);


        })
        .catch(error => {
            console.error('Error fetching HTML:', error);
        });
    // });
}

/**
 * Takes all the user input from the index.html page and initializes the model that will be used in the controller object
 * @param userUploadedFile flag because the original file name needs to be set differently if it was uploaded
 * @param table the snippet of the dataset that will be used in the view
 * @param fileName name of the file the user uploaded or selected
 * @param errorData the dataset of the errors found from running the detectors on the dataset
 * @param minID min range window to render
 * @param maxID max range window to render
 * @param useDB whether to use db routes in the server
 */
function prepForControllerInit(userUploadedFile, table, fileName,errorData,minID,maxID,useDB){
    d3.select("#matrix-vis-stackoverflow").html("");
    stackoverflowController = new ScatterplotController(table, "#matrix-vis");
    stackoverflowController.model.setSampleIDRangeMin(minID);
    stackoverflowController.model.setSampleIDRangeMax(maxID);
    stackoverflowController.model.setUsingDB(useDB);
    stackoverflowController.model.originalFilename = fileName.split('/').pop();

    if(userUploadedFile) {
        stackoverflowController.model.originalFilename = fileName;
    }
    attachButtonEventListeners(stackoverflowController);
    exportPythonScriptListener(stackoverflowController);
    initWranglersDetectors(stackoverflowController,errorData);
}

/**
 * Loads the detectors and wranglers into the controller
 * @param controller
 * @param errorData
 */
function initWranglersDetectors(controller,errorData){
    (async () => {
        try {
            /* These are not getting used currently, they are from the old view-only branch, and haven't been deleted
            * yet (also the wranglers) */
            const detectorResponse = await fetch('/static/detectors/detectors.json');
            const detectors = await detectorResponse.json();

            const wranglerResponse = await fetch('/static/wranglers/wranglers.json');
            const wranglers = await wranglerResponse.json();

            await controller.init(detectors, wranglers,errorData);
                } catch (err) {
                    console.error("Failed to init controller:", err);
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

/**
 * exports the actions taken - this is not really set up for this branch, but can be adapted to work with it probably
 * @param controller
 */
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


