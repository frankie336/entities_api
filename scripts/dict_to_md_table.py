from projectdavid_common.constants.ai_model_map import MODEL_MAP


def dict_to_md_table(data, title_case_headers=False):
    """
    Convert a dictionary to a markdown table

    Args:
        data (dict): Dictionary to convert (keys become headers)
        title_case_headers (bool): Convert header names to Title Case

    Returns:
        str: Markdown-formatted table
    """
    # Extract headers and rows
    headers = list(data.keys())
    rows = list(zip(*data.values()))

    # Clean and format headers
    if title_case_headers:
        headers = [h.title().replace("_", " ") for h in headers]

    # Create table header and separator
    table = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    # Add rows
    for row in rows:
        table.append("| " + " | ".join(str(item) for item in row) + " |")

    return "\n".join(table)


# Example usage
employee_data = {
    "id": [101, 102, 103],
    "name": ["Alice Chen", "Bob Johnson", "Carlos Rivera"],
    "department": ["Engineering", "Marketing", "Sales"],
    "salary": [85000, 72000, 68000],
}

print(dict_to_md_table(MODEL_MAP, title_case_headers=True))
