#!/usr/bin/env python
import os

from dotenv import load_dotenv
from fastapi.routing import APIRoute
from tabulate import tabulate

from entities_api.app import \
    create_app  # Import your app factory, not the app instance

load_dotenv()

# Prevent DB initialization (optional if handled in app factory)
os.environ["DISABLE_DB_INIT"] = "1"

# Create the app without DB bootstrapping
app = create_app(init_db=False)

# Collect route information
routes_data = []

for route in app.routes:
    if isinstance(route, APIRoute):
        method_list = ", ".join(route.methods - {"HEAD", "OPTIONS"})
        routes_data.append(
            [
                route.path,
                method_list,
                route.name or "",
                route.summary or "",
            ]
        )

# Format as Markdown table
headers = ["Path", "Method(s)", "Name", "Summary"]
markdown_table = tabulate(routes_data, headers, tablefmt="github")

# Output the table
print("# 📌 FastAPI Routes (Markdown View)\n")
print(markdown_table)
