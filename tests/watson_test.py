# Tool creation and association functions
from entities_api.clients.client import OllamaClient
from entities_api.clients.runner import Runner
from entities_api.clients.client_thread_client import ThreadService
from utils.doc_testing import assistant
from utils.sandbox_maker import user_id

client = OllamaClient()



if __name__ == '__main__':
    """
    Test the new inference point using IBM Watson integration.
    """
    # Instantiate the Runner
    runner = Runner()

    # Set up test parameters (replace with actual values as needed)

    thread = client.thread_service.create_thread(participant_ids=['user_nBYY31ZdKJwciqiaFrTz5g']

                                                 )

    message_id = 'test_message_id'
    message = client.message_service.create_message(
        thread_id=thread.id,
        sender_id='user_nBYY31ZdKJwciqiaFrTz5g',
        content='Hello, how are you?'
    )


    run_id = 'test_run_id'
    run = client.run_service.create_run(
        assistant_id='asst_0w0KzZjR39lCR0z0RoEVoL',
        thread_id=thread.id
    )



    def save_assistant_message_chunk(self, thread_id, content, is_last_chunk):
            print(f"Message saved for thread {thread_id}: {content}")

    class MockRunService:
        def retrieve_run(self, run_id):
            return type('Run', (object,), {'status': 'running'})()

        def update_run_status(self, run_id, status):
            print(f"Run {run_id} status updated to {status}")


    # Choose the model for IBM Watson integration
    model = 'llama3.2:90b_v'

    # Process the conversation
    response_generator = runner.process_conversation(
        thread_id=thread.id,
        message_id=message['id'],
        run_id=run.id,
        assistant_id=assistant.id,
        model=model
    )

    # Print the assistant's response
    print("Assistant's response:")
    for response_chunk in response_generator:
        print(response_chunk, end='')
