import os
from dotenv import load_dotenv

load_dotenv()

PLATFORM_TOOLS = ["code_interpreter", "web_search", "vector_store_search", "computer"]


TOOLS_ID_MAP = {"code_interpreter": "tool_79YkQEz5cDwpJjnR7oJ80D",
             "web_search": "tool_BiIwycpLo1n5Dh6BHN01v8",
             "vector_store_search": "tool_MCaJpXJU3eW6vaMUybEf6i",
             "computer": "tool_PJQ6VcnkmRCMankObjtRcn"
             }


SPECIAL_CASE_TOOL_HANDLING = ["computer", "code_interpreter"]

ERROR_NO_CONTENT = (
    "ERROR: The Tool has failed to return any content. The current stage of the workflow is tool submission. "
    "Please inform the user."
)


DIRECT_DATABASE_URL = "mysql+pymysql://ollama:3e4Qv5uo2Cg31zC1@localhost:3307/cosmic_catalyst"


#------------------------------------------------
# Vendors sometimes have clashing model names.
# This can interfere with routing logic
#_________________________________________________
MODEL_MAP = {"deepseek-ai/deepseek-reasoner": "deepseek-reasoner",
             "deepseek-ai/deepseek-chat": "deepseek-chat",

             "together-ai/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
             "together-ai/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",

             "hyperbolic/deepseek-ai/DeepSeek-R1": "deepseek-ai/DeepSeek-R1",
             "hyperbolic/deepseek-ai/DeepSeek-V3": "deepseek-ai/DeepSeek-V3",

             }


WEB_SEARCH_BASE_URL = "http://localhost:8080/"

SUPPORTED_MIME_TYPES = {
        # C/C++
        '.c': 'text/x-c',
        '.cpp': 'text/x-c++',
        # C#
        '.cs': 'text/x-csharp',
        # CSS
        '.css': 'text/css',
        # Word documents
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        # Go
        '.go': 'text/x-golang',
        # HTML
        '.html': 'text/html',
        # Java
        '.java': 'text/x-java',
        # JavaScript
        '.js': 'text/javascript',
        # JSON
        '.json': 'application/json',
        # Markdown
        '.md': 'text/markdown',
        # PDF
        '.pdf': 'application/pdf',
        # PHP
        '.php': 'text/x-php',
        # PowerPoint
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        # Python
        '.py': 'text/x-python',
        '.pyx': 'text/x-script.python',
        # Ruby
        '.rb': 'text/x-ruby',
        # Shell script
        '.sh': 'application/x-sh',
        # TeX
        '.tex': 'text/x-tex',
        # TypeScript
        '.ts': 'application/typescript',
        # Plain text
        '.txt': 'text/plain',
    }

# For text/* MIME types, define allowed encodings
ALLOWED_TEXT_ENCODINGS = ['utf-8', 'utf-16', 'ascii']
