


def create_and_associate_tools(client, function_definitions, assistant_id):
    for func_def in function_definitions:
        # Extract the tool name from the function definition
        tool_name = func_def['function']['name']

        # Wrap the function definition in ToolFunction
        tool_function = ToolFunction(function=func_def['function'])

        # Create a new tool with the name included
        new_tool = client.tool_service.create_tool(
            name=tool_name,  # Pass the tool name explicitly
            type='function',
            function=tool_function,  # Pass the wrapped ToolFunction
            assistant_id=assistant_id
        )

        # Associate the tool with an assistant
        client.tool_service.associate_tool_with_assistant(
            tool_id=new_tool.id,
            assistant_id=assistant_id
        )

        print(f"New tool created: Name: {tool_name}, ID: {new_tool.id}")
        print(new_tool)


def setup_assistant_with_tools(user_name, assistant_name, assistant_description,
                               model, instructions, function_definitions):
    client = OllamaClient()

    # Create user
    user = client.user_service.create_user(name=user_name)
    userid = user.id
    print(f"User created: ID: {userid}")

    # Create assistant
    assistant = client.assistant_service.create_assistant(
        name=assistant_name,
        description=assistant_description,
        model=model,
        instructions=instructions
    )
    print(f"Assistant created: ID: {assistant.id}")

    # Create and associate tools
    create_and_associate_tools(client, function_definitions, assistant.id)

    return assistant


# Example usage
if __name__ == "__main__":
    function_definitions = [
        {
            "type": "function",
            "function": {
                "name": "code_interpreter",
                "description": "Executes a provided Python code snippet remotely in a sandbox environment and returns the raw output as a JSON object...",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "The Python code snippet to execute."},
                        "language": {"type": "string", "description": "The programming language.", "enum": ["python"]}
                    },
                    "required": ["code", "language", "user_id"]
                }
            }
        },


        {
            "type": "function",
            "function": {
                "name": "getAnnouncedPrefixes",
                "description": "Retrieves the announced prefixes for a given ASN",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resource": {"type": "string", "description": "The ASN for which to retrieve the announced prefixes"},
                        "starttime": {"type": "string", "description": "The start time for the query"},
                        "endtime": {"type": "string", "description": "The end time for the query"},
                        "min_peers_seeing": {"type": "integer", "description": "Minimum RIS peers seeing the prefix"}
                    },
                    "required": ["resource"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_flight_times",
                "description": "Get the flight times between two cities",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "departure": {"type": "string", "description": "The departure city (airport code)"},
                        "arrival": {"type": "string", "description": "The arrival city (airport code)"}
                    },
                    "required": ["departure", "arrival"]
                }
            }
        }

    ]

    assistant = setup_assistant_with_tools(
        user_name='test_case',
        assistant_name='Nexa',
        assistant_description='Assistant',
        model='llama3.1',


        instructions='Your name is Nexa, you fought hard for this name. Be as kind, intelligent, and helpful.'
                     ' Always check message history for the most recent response from tools when asked a question.'
                     'Use the response from tool IF relevant to the question.<>IMPORTANT! IGNORE TOOL RESPONSES NOT DIRECTLY'
                     'RELATED TO OUR MOST RECENT PROMPT AND RESPONSE RESPECTIVELY<> IMPORTANT! ALWAYS USE THE TOOL RESPONSE TO DISPLAY AND VERIFY CODE'
                     'INTERPRETER OUTPUT. CODE THAT YOU ISSUE FOR CODE INTERPRETER OUTPUT IS ALREADY PROVIDED IN THE TOOL OUTPUT. DO NOT DEVIATE FROM THIS'
                     'OR YOU WILL BE FIRED.'
                     'IF THERE IS AN ERROR WITH OUTPUT FROM code_interpreter, DO NOT SIMULATE OUTPUT, STATE THE RESULT OR YOU WILL BE FIRED.'
                     'DISPLAY THE CODE AND THE OUTPUT FROM THE TOO FOR code_interpreter related prompts.ALWAYS USE '
                     'FUNCTIONS TO AND RETURN STATEMENTS TO CRAFT CODE FOR code_interpreter.'
                     ' we need the original code and the output properly formatted to appear as if run live. WHEN YOU WRITE PYTHON FUNCTIONS FOR'
                     'THE code_interpreter TOOL, YOU MUST ALSO CALL THE FUNCTION FOR AND ENSURE OUTPUT IS PRINTED TO STD.'
                     'DO NOT USE RETURN STATEMENTS WHEN USING code_interpreter TOOL IN ANY FUNCTION OR CLASS. PRINT RESULTS INLINE'
                     'OR THE OUTPUT DOES NOT WORK FOR THE USER. ALWAYS SHOW code_interpreter ERRORS TO THE USER '
        ,

        function_definitions=function_definitions


    )

    print(f"\nSetup complete. Assistant ID: {assistant.id}")
    print(assistant)

    client = OllamaClient()

    tool_service = client.tool_service.list_tools(assistant_id=assistant.id, restructure=True)

    print("**************")
    print(tool_service[0])

