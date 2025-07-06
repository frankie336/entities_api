from src.api.entities_api.ptool_definitions.code_interpreter import \
    code_interpreter
from src.api.entities_api.ptool_definitions.computer import computer
from src.api.entities_api.ptool_definitions.file_search import file_search
from src.api.entities_api.ptool_definitions.web_search import web_search


def assemble_tools():
    """
    Aggregates all core function-call tools into a list for registration.

    This function returns the full set of supported assistant tools—each
    defined using an OpenAI-style tool schema—for use in structured function
    calling. These include:

    - code_interpreter : Executes Python code in a secure sandbox.
    - file_search      : Performs semantic search over vectorized documents.
    - computer         : Simulates a Linux terminal for executing shell commands.
    - web_search       : Queries the web using advanced search operators.

    Returns:
        List[Dict[str, Any]]: A list of OpenAI-compatible tool schema dictionaries.
    """
    tools = [code_interpreter, file_search, computer, web_search]
    return tools
