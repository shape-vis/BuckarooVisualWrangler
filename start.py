#Buckaroo Project - June 1, 2025
#This file starts the app

from app import app

if __name__ == "__main__":
    print("INSIDE GUARD")
    app.run(host="127.0.0.1", port=5001, debug=True, use_reloader=False)