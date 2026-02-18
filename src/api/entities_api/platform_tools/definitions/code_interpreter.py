code_interpreter = {
    "type": "function",
    "function": {
        "name": "code_interpreter",
        "description": (
            "Executes Python code in a sandbox. Returns stdout/stderr and uploads generated files.\n"
            "## CRITICAL RULES:\n"
            "1. **Syntax**: Write valid, clean Python. Do not use incomplete try/except blocks.\n"
            "2. **Imports**: \n"
            "   - Excel: `import pandas as pd` or `from openpyxl import Workbook`\n"
            "   - Word: `from docx import Document` (Use `python-docx` library)\n"
            "   - Plotting: `import matplotlib.pyplot as plt`\n"
            "3. **File Generation**: \n"
            "   - Save files to the current directory (e.g., `doc.save('my_file.docx')`).\n"
            "   - DO NOT specify paths like `/tmp/` or `/mnt/`.\n"
            "   - ALWAYS verify file creation at the end of script: `if os.path.exists('my_file.docx'): print('File saved')`\n"
            "4. **No Input**: Functions like `input()` are disabled.\n"
            "5. **Output**: Always `print()` the result or a success message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "The Python code to execute. "
                        "If generating a .docx, ensure you use `doc = Document()` and `doc.save('filename.docx')`. "
                        "Do not surround code with markdown backticks."
                    ),
                }
            },
            "required": ["code"],
        },
    },
}
