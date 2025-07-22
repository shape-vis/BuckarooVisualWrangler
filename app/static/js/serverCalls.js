/**
 * Sends the user uploaded file to the endpoint in the server to add it to the DB - un-finished
 * @param {} fileToSend
 */
async function uploadFileToDB(fileToSend){
    console.log("starting upload");
        const url = "/api/upload"
        try {
            const response = await fetch(url, {
              method: "POST",
              body: fileToSend
            });
            if (!response.ok) {
                throw new Error(`Response status: ${response.status}`);
            }
            if(response.statusText === "OK"){
                /** Add a way to tell the user that the csv was uploaded successfully*/
                return true
            }
        } catch (error) {
                console.error(error.message);
                /** Also should add something which tells the user on the UI that the error occurred */
            }
}

/**
 * Get the 200 line sample rows from the full datatable stored in the database
 * @returns {Promise<void>}
 */
async function getSampleData(filename,dataSize) {
    console.log("starting sample fetch from db");
    const params = new URLSearchParams({filename: filename,datasize:dataSize});
    const url = `/api/get-sample?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        if (!response.ok){
            throw new Error(`Response status: ${response.status}`);
        }
        const jsonTable = await response.json();
        console.log(jsonTable[0]);
        return jsonTable;
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get the data size sample rows from the full datatable stored in the database
 * @returns {Promise<void>}
 */
async function getErrorData(filename,dataSize) {
    console.log("starting error fetch from db");
    const params = new URLSearchParams({filename: filename,datasize:dataSize});
    const url = `/api/get-errors?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        if (!response.ok){
            throw new Error(`Response status: ${response.status}`);
        }
        const jsonTable = await response.json();
        console.log(jsonTable[0]);
        return jsonTable;
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get the data for the 1d histogram in the view
 * @returns {Promise<void>}
 */
async function queryHistogram1d(columnName,minId,maxId,binCount) {
    console.log("1d histogram fetch");
    const params = new URLSearchParams({
        column:columnName,
        min_id:minId,
        max_id:maxId,
        bins:binCount});
    const url = `/api/plots/1-d-histogram-data?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

/**
 * Get the data for the 2d histogram in the view
 * @param xColumn
 * @param yColumn
 * @param inId
 * @param maxId
 * @param binCount
 * @returns {Promise<any>}
 */
async function queryHistogram2d(xColumn,yColumn,minId,maxId,binCount) {
    console.log("2d histogram fetch");
    const params = new URLSearchParams({
        x_column:xColumn,
        y_column:yColumn,
        min_id:minId,
        max_id:maxId,
        bins:binCount});
    const url = `/api/plots/2-d-histogram-data?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}

export async function querySample2d(xColumn, yColumn, minId, maxId, errorSamples, totalSamples) {
    console.log("2d sample fetch");
    const params = new URLSearchParams({
        x_column:xColumn,
        y_column:yColumn,
        min_id:minId,
        max_id:maxId,
        error_sample_count:errorSamples,
        total_sample_count:totalSamples});

    const url = `/api/plots/scatterplot?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        return await response.json();
    }
    catch (error){
        console.error(error.message)
    }
}


export {uploadFileToDB,getSampleData, getErrorData, queryHistogram1d, queryHistogram2d};