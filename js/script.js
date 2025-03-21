let activeDataset = "stackoverflow";
let practiceController, stackoverflowController;

let data2 = null;
// May need to change 'id' to 'ID'
d3.csv("data/stackoverflow_db_uncleaned.csv").then(inputData => {
  data2 = aq.from(inputData).slice(0, 100);

  stackoverflowController = new ScatterplotController(data2, "#matrix-vis-stackoverflow");

  stackoverflowController.updateSelectedAttributes(data2.columnNames().slice(1).sort().slice(0,3));
  // stackoverflowController.render();
  stackoverflowController.view.populateDropdownFromTable(stackoverflowController.model.getFullData(), stackoverflowController);

  attachButtonEventListeners();
});

// document.getElementById('fileInput').addEventListener('change', function (event) {
//   const file = event.target.files[0];
//   console.log("file", file);
//   if (!file) return;

//   const reader = new FileReader();

//   reader.onload = function (e) {
//     const contents = e.target.result;

//     // Parse CSV using d3.csvParse
//     const parsedData = d3.csvParse(contents);
//     const table = aq.from(parsedData).slice(0,100);

//     // Clear the existing visualization container
//     d3.select("#matrix-vis-stackoverflow").html("");

//     // Reinitialize controller with new data
//     stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
//     stackoverflowController.updateSelectedAttributes(table.columnNames().slice(1).sort().slice(0, 3));
//     stackoverflowController.view.populateDropdownFromTable(stackoverflowController.model.getFullData(), stackoverflowController);

//     attachButtonEventListeners();

//   };

//   reader.readAsText(file);
// });

document.getElementById("export-script").addEventListener("click", function () {
  const scriptContent = `
import pandas as pd

# Load your dataset
df = pd.read_csv('stackoverflow_db_uncleaned.csv')

# Example cleaning steps:
# Drop rows with missing values
df_cleaned = df.dropna()

# Convert 'ConvertedSalary' to numeric, coercing errors
df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')

# Fill missing values with column means
df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))

# Save cleaned dataset
df_cleaned.to_cs