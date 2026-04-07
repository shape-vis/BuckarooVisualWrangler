# This file handles all endpoints related to the pgraph - April 7, 2026
from app import app
from app.server_utils.service_helpers import get_current_pgraph

@app.get("api/routes/update_pgraph")
def update_pgraph():
    return get_current_pgraph()
    