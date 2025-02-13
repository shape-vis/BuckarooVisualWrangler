const data = aq.table({
    id: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    age:        ["sixty", 22, true, 99, 40, 45, 0, 89, NaN, 55],
    "salary (k)": [NaN, 65, '$', 70, "fifty", 80, 0, 99, 85, 89],
    employees: [0, 5, "None", NaN, 15, 20, 25, 30, 0, 89],
  });

const data2 = aq.table({
    id: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    age: [25, 0, 35, 0, 40, 45, 0, 89, 72, 55],
    "salary (k)": [40, 65, 55, 70, 15, 75, 0, 80, 85, 89],
    employees: [0, 5, 10, 55, 15, 20, 25, 30, 0, 89],
  });

const practiceController = new ScatterplotController(data, "#matrix-vis-practice");
const stackoverflowController = new ScatterplotController(data2, "#matrix-vis-stackoverflow");

document.getElementById("tab2").style.display = "none";
let activeDataset = "practice";

attachButtonEventListeners();