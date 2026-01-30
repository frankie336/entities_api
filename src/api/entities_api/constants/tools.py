from src.api.entities_api.platform_tools.definitions.code_interpreter import \
    code_interpreter
from src.api.entities_api.platform_tools.definitions.computer import computer
from src.api.entities_api.platform_tools.definitions.file_search import \
    file_search
from src.api.entities_api.platform_tools.definitions.web_search import \
    web_search

PLATFORM_TOOL_MAP = {
    "code_interpreter": code_interpreter,
    "computer": computer,
    "web_search": web_search,
    "file_search": file_search,
}
