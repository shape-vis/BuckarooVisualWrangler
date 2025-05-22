/**
 * The backend of the app, used for backend computation that will take longer than what the view can handle, will be integrated later on?
 */
class Backend{
    cacheController;
    dataTable;
    constructor(datafile){
        this.datafile = datafile;
    }

    /**
     * Driver for the backend functionality
     */
    async start() {
        initModelAndController().then(r => console.error("Unable to init model and controller"));
    }
}

async function initModelAndController() {
    try {
        //convert the file to a csv, and then set the object's dataTable
        populateDataTable(this.datafile);

        const detectorResponse = await fetch('detectors/detectors.json');
        const detectors = await detectorResponse.json();

        const wranglerResponse = await fetch('wranglers/wranglers.json');
        const wranglers = await wranglerResponse.json();



        //make the controller
        this.cacheController = new CacheController(this.dataTable);
        await this.cacheController.init(detectors);

    } catch (err) {
        console.error("Failed to load or run detectors:", err);
    }
}

function populateDataTable(datafile) {
    d3.csv(datafile).then(data => {
        this.dataTable = setIDColumn(aq.from(data).slice(0, 1000));
    }).catch(error => {
        console.error("Error loading the CSV:", error);
    });
}

/**
 * Adds an ID column into the first index of the table to be used throughout in selection, wrangling, etc. If an ID column already exists, it moves it to the first index in the
 * table.
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

