let activeDataset = "stackoverflow";
let practiceController, stackoverflowController;

let data2 = null;

// d3.csv("data/stackoverflow_db_uncleaned.csv").then(inputData => {
//   data2 = aq.from(inputData).slice(0, 200);

//   d3.select("#matrix-vis-stackoverflow").html("");

//   stackoverflowController = new ScatterplotController(data2, "#matrix-vis-stackoverflow");

//   // stackoverflowController.render();

//   attachButtonEventListeners(stackoverflowController);

//   (async () => {
//     try {
//       const detectorResponse = await fetch('/data/detectors.json');
//       const detectors = await detectorResponse.json();

//       const wranglerResponse = await fetch('/data/wranglers.json');
//       const wranglers = await wranglerResponse.json();
  
//       await stackoverflowController.init(detectors, wranglers);
//     } catch (err) {
//       console.error("Failed to load or run detectors:", err);
//     }
//   })();
  
// });

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
          const table = aq.from(parsedData).slice(0,200);
      
          d3.select("#matrix-vis-stackoverflow").html("");
      
          stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
          stackoverflowController.model.originalFilename = file.name;

          // stackoverflowController.updateSelectedAttributes(table.columnNames().slice(1).sort().slice(0, 3));
          // stackoverflowController.view.populateDropdownFromTable(stackoverflowController.model.getFullData(), stackoverflowController);
      
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