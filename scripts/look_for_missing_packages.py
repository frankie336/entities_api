import os

# Define the root path of the project
root_path = "~/entities_api/src/api/entities_api"

# List to collect missing __init__.py info
missing_inits = []

# Walk through the directory tree
for dirpath, dirnames, filenames in os.walk(root_path):
    # Skip hidden/system directories
    if "__pycache__" in dirpath or ".git" in dirpath:
        continue
    # Check if __init__.py is missing
    if "__init__.py" not in filenames:
        missing_inits.append(dirpath)

print(missing_inits)
