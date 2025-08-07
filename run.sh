#!/bin/bash

if [ -d "venv" ]; then
    echo "Virtual environment already exists."
    source venv/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    # pip install flask psycopg2 dotenv sqlalchemy numpy pandas
    pip install -r requirements.txt
fi

echo "Running the application..."
flask run
