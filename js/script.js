let activeDataset = "stackoverflow";
let practiceController, stackoverflowController;

let data2 = null;
// May need to change 'id' to 'ID'
// d3.csv("data/stackoverflow_db_uncleaned.csv").then(inputData => {
//   data2 = aq.from(inputData).slice(0, 200);

//   stackoverflowController = new ScatterplotController(data2, "#matrix-vis-stackoverflow");

//   stackoverflowController.updateSelectedAttributes(data2.columnNames().slice(1).sort().slice(0,3));
//   // stackoverflowController.render();
//   stackoverflowController.view.populateDropdownFromTable(stackoverflowController.model.getFullData(), stackoverflowController);

//   attachButtonEventListeners();
// });

document.getElementById('fileInput').addEventListener('change', function (event) {

   fetch('data_cleaning_vis_tool.html') 
      .then(response => response.text())
      .then(html => {
        document.body.innerHTML = html;
        
        const file = event.target.files[0];
        console.log("file", file);
        if (!file) return;
      
        document.getElementById('placeholder-message').style.display = "none";
      
        const reader = new FileReader();
      
        reader.onload = function (e) {
          const contents = e.target.result;
          const parsedData = d3.csvParse(contents);
          const table = aq.from(parsedData).slice(0,200);
      
          d3.select("#matrix-vis-stackoverflow").html("");
      
          stackoverflowController = new ScatterplotController(table, "#matrix-vis-stackoverflow");
          stackoverflowController.updateSelectedAttributes(table.columnNames().slice(1).sort().slice(0, 3));
          stackoverflowController.view.populateDropdownFromTable(stackoverflowController.model.getFullData(), stackoverflowController);
      
          attachButtonEventListeners();

          (async () => {
            try {
              const response = await fetch('/data/detectors.json');
              const detectors = await response.json();

              await stackoverflowController.init(detectors);
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

document.addEventListener("DOMContentLoaded", function () {

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
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))
  # Convert 'ConvertedSalary' to numeric, coercing errors
  df_cleaned['ConvertedSalary'] = pd.to_numeric(df_cleaned['ConvertedSalary'], errors='coerce')
  # Fill missing values with column means
  df_cleaned = df_cleaned.fillna(df_cleaned.mean(numeric_only=True))


  # Save cleaned dataset
  df_cleaned.to_csv('stackoverflow_db_cleaned.csv', index=False)
  `;

    const blob = new Blob([scriptContent], { type: "text/x-python" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "stackoverflow_db_cleaned.py";
    a.click();

    URL.revokeObjectURL(url); 
  });

});





// const data = aq.table({
//     ID: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
//     age:        ["sixty", 22, true, 99, 45, 45, 0, 89, NaN, 55],
//     "salary (k)": [NaN, 65, '$', 70, "fifty", 70, 0, 99, 85, 89],
//     employees: [0, 5, "None", NaN, 15, 15, 25, 30, 0, 89],
//   });


// practiceController = new ScatterplotController(data, "#matrix-vis-practice");

// const data2 = aq.table({
//     ID: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
//     age: [25, 0, 35, 0, 40, 45, 0, 89, 72, 55],
//     "salary (k)": [40, 65, 55, 70, 15, 75, 0, 80, 85, 89],
//     employees: [0, 5, 10, 55, 15, 20, 25, 30, 0, 89],
//   });



