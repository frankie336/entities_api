from src.api.entities_api.system_message.main_assembly import \
    assemble_instructions

instructions = assemble_instructions()
print(instructions)

from typing import Optional

from src.api.entities_api.system_message.core_instructions import \
    CORE_INSTRUCTIONS
