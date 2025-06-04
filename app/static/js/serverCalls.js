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
async function getSampleData(filename) {
    console.log("starting sample fetch from db");
    let justTheFilename = filename.substring(13,filename.length);
    const params = new URLSearchParams({filename: justTheFilename});
    const url = `/api/get-sample?${params}`
    try{
        const response = await fetch(url, {method: "GET"});
        if (!response.ok){
            throw new Error(`Response status: ${response.status}`);
        }
        const jsonTable = await response.json();
        return jsonTable;
    }
    catch (error){
        console.error(error.message)
    }
}

export {uploadFileToDB,getSampleData};