const data = aq.table({
    id: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    age: ["sixty", NaN, true, 0, 40, 45, 0, 89, 50, 55],
    "salary (k)": [NaN, 65, '$', 70, 0, 75, 0, 80, 85, 89],
    employees: [0, 5, "None", NaN, 15, 20, 25, 30, 0, 89],
  });

const controller = new ScatterplotController(data, "#matrix-vis");
