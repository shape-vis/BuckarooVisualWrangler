import csv

data = [
            {"id": 1, "name": "Alex Smith", "age": 29, "city": "Salt Lake City"},
            {"id": 2, "name": "Jordan Lee", "age": 34, "city": "New York"},
            {"id": 3, "name": "Taylor Kim", "age": "one", "city": "Chicago"},
            {"id": 4, "name": "Lenny Kim", "age": 29, "city": "Portland"},
            {"id": 5, "name": "John Doe", "age": 32, "city": "Vancouver"},
            {"id": 6, "name": "Mari Martinez", "age": 20, "city": "Chicago"},
        ]

with open("mari_dataset.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
