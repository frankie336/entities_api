#!/usr/bin/env python

import os
import sys

from tabulate import tabulate

# Setup path to allow module resolution
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from fastapi.routing import APIRoute

    from entities_api.routers import api_router  # Central router only
except ImportError as e:
    print(f"❌ Failed to import FastAPI components: {e}")
    sys.exit(1)


def extract_routes(router, prefix=""):
    """Recursively extract routes from a FastAPI router."""
    routes_data = []

    for route in router.routes:
        if isinstance(route, APIRoute):
            methods = ",".join(sorted(route.methods))
            path = prefix + route.path
            name = route.name
            summary = route.summary or ""
            tags = ", ".join(route.tags or [])
            routes_data.append([methods, path, name, tags, summary])

        elif hasattr(route, "include_router"):
            # It's a nested router
            sub_prefix = route.prefix or ""
            nested_routes = extract_routes(route.include_router, prefix + sub_prefix)
            routes_data.extend(nested_routes)

    return routes_data


def save_markdown_table(rows, headers, output_path):
    """Save the route table as a markdown file."""
    markdown = tabulate(rows, headers=headers, tablefmt="github")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# 📘 API Endpoint Table\n\n")
        f.write(markdown)
        f.write("\n")
    print(f"\n✅ Saved markdown table to: {output_path}")


def main():
    print("📡 Extracting FastAPI route metadata...\n")

    routes = extract_routes(api_router)
    routes.sort(key=lambda r: r[1])  # Sort by path

    headers = ["Method", "Path", "Name", "Tags", "Summary"]
    print(tabulate(routes, headers=headers, tablefmt="fancy_grid", stralign="left"))

    # Save Markdown version
    markdown_output_path = os.path.join(project_root, "docs", "routes.md")
    os.makedirs(os.path.dirname(markdown_output_path), exist_ok=True)
    save_markdown_table(routes, headers, markdown_output_path)


if __name__ == "__main__":
    main()
