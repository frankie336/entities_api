import time

import entities_api




client = entities_api.OllamaClient()
user = client.user_service.create_user(name='test_case')

userid = user.id


assistant = client.assistant_service.create_assistant(
    user_id=userid,
    name='Nexa',
    description='Assistant',
    model='llama3.1',
    instructions='Your name is Nexa, you fought hard for this name. Be as kind, intelligent, and helpful.'
                 ' Always check message history for the most recent response from tools when asked a question.'
                 'Use the response from tool IF relevant to the question.<>IMPORTANT! IGNORE TOOL RESPONSES NOT DIRECTLY'
                 'RELATED TO OUR MOST RECENT PROMPT AND RESPONSE RESPECTIVELY<> ',

)

print(assistant.id)