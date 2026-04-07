from app import app as flask_app

if __name__ == "__main__":
    flask_app.run(host="127.0.0.1", port=5001, debug=True, use_reloader=False)