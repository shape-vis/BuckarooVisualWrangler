let activeDataset = "stackoverflow";
let practiceController, stackoverflowController;

let data2 = null;
// May need to change 'id' to 'ID'
d3.csv("data/stackoverflow_db.csv").then(inputData => {
  data2 = aq.from(inputData).slice(0, 100);

  stackoverflowController = new ScatterplotController(data2, "#matrix-vis-stackoverflow");

  stackoverflowController.render();
  stackoverflowController.view.populateDropdownFromTable(stackoverflowController.model.getFullData(), stackoverflowController);

  attachButtonEventListeners();
});

const data = aq.table({
    ID: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    age:        ["sixty", 22, true, 99, 40, 45, 0, 89, NaN, 55],
    "salary (k)": [NaN, 65, '$', 70, "fifty", 80, 0, 99, 85, 89],
    employees: [0, 5, "None", NaN, 15, 20, 25, 30, 0, 89],
  });


practiceController = new ScatterplotController(data, "#matrix-vis-practice");

// const data2 = aq.table({
//     ID: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
//     age: [25, 0, 35, 0, 40, 45, 0, 89, 72, 55],
//     "salary (k)": [40, 65, 55, 70, 15, 75, 0, 80, 85, 89],
//     employees: [0, 5, 10, 55, 15, 20, 25, 30, 0, 89],
//   });


document.getElementById("tab1").style.display = "none";

