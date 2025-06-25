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
 * Get the 200 line sample rows from the full datatable stored in the database
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

export {uploadFileToDB,getSampleData, getErrorData};