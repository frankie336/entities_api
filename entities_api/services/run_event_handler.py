# backend/app/services/event_handlers/run_event_handler.py

import time
import threading
from typing import Optional, Dict, Any, List
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class EntitiesEventHandler:
    def __init__(self, run_service, action_service):
        """
        Enhanced event handler to monitor runs, detect triggered events, and handle callbacks.
        """
        self.run_service = run_service
        self.action_service = action_service
        self.active_monitors: Dict[str, threading.Thread] = {}
        self._current_run: Optional[Any] = None
        self._current_tool_call: Optional[Any] = None

    def start_monitoring(self, run_id: str):
        """
        Start monitoring a run in a dedicated thread.
        """
        if run_id not in self.active_monitors:
            monitor_thread = threading.Thread(
                target=self._monitor_run_status,
                args=(run_id,),
                daemon=True
            )
            self.active_monitors[run_id] = monitor_thread
            monitor_thread.start()
            logging_utility.info(f"Started monitoring run {run_id}")
        else:
            logging_utility.info(f"Run {run_id} is already being monitored")

    def _monitor_run_status(self, run_id: str):
        """
        Internal method to monitor the run status and detect triggered events.
        """
        while True:
            try:
                run = self.run_service.retrieve_run(run_id)
                logging_utility.info(f"Run {run_id} status: {run.status}")

                # Emit events based on run status
                if run.status == "action_required":
                    self._emit_event({"type": "action_required", "data": run})
                    break  # Exit after handling the event

                if run.status in ["completed", "failed", "cancelled"]:
                    self._emit_event({"type": "run_ended", "data": run})
                    break  # Exit if the run has ended

                time.sleep(2)  # Polling interval

            except Exception as e:
                logging_utility.error(f"Error monitoring run {run_id}: {str(e)}")
                self._emit_event({"type": "error", "data": str(e)})
                break

        self.active_monitors.pop(run_id, None)

    def _emit_event(self, event: Dict[str, Any]):
        """
        Process an incoming event and trigger the appropriate callback.
        """
        event_type = event["type"]
        event_data = event["data"]

        # Trigger the generic event callback
        self.on_event(event)

        # Trigger specific event callbacks
        if event_type == "action_required":
            self.on_action_required(event_data)
        elif event_type == "run_ended":
            self.on_run_ended(event_data)
        elif event_type == "error":
            self.on_error(event_data)

    def stop_monitoring(self, run_id: str):
        """
        Stop monitoring a specific run.
        """
        if run_id in self.active_monitors:
            thread = self.active_monitors.pop(run_id)
            thread.join(timeout=1)
            logging_utility.info(f"Stopped monitoring run {run_id}")

    # Event Callbacks
    def on_event(self, event: Dict[str, Any]):
        """
        Callback for every event.
        """
        logging_utility.info(f"Event received: {event['type']}")

    def on_action_required(self, run: Any):
        """
        Callback when action is required for a run.
        """
        logging_utility.info(f"Action required for run: {run.id}")
        self._current_run = run

        # Fetch and process pending actions
        pending_actions = self._get_pending_actions(run.id)
        if pending_actions:
            logging_utility.info(f"Processing {len(pending_actions)} pending actions for run {run.id}.")
            for action in pending_actions:
                self.on_tool_call_created(action)
        else:
            logging_utility.info(f"No valid pending actions found for run {run.id}.")

    def on_run_ended(self, run: Any):
        """
        Callback when a run has ended.
        """
        logging_utility.info(f"Run ended: {run.id} with status: {run.status}")
        self._current_run = None

    def on_error(self, error: str):
        """
        Callback when an error occurs during monitoring.
        """
        logging_utility.error(f"Error during monitoring: {error}")

    def on_tool_call_created(self, tool_call: Any):
        """
        Callback when a tool call is created.
        """
        logging_utility.info(f"Tool call created: {tool_call.id}")
        self._current_tool_call = tool_call

        # Log detailed information about the tool call
        try:
            action_id = tool_call.id
            tool_id = tool_call.tool_id
            function_args = tool_call.function_args
            expires_at = tool_call.expires_at
            status = tool_call.status

            logging_utility.info(
                f"Processing action with ID {action_id}: "
                f"tool_id={tool_id}, function_args={function_args}, "
                f"expires_at={expires_at}, status={status}"
            )

            # Example: Update action status to 'in_progress'
            if status == "pending":
                logging_utility.info(f"Action {action_id} marked as in_progress.")
                # Here, you would typically call a method to update the action status in the database
                # Example: self.action_service.update_action_status(action_id, "in_progress")

            # Example: Invoke a tool based on the action's function_args
            if function_args:
                logging_utility.info(f"Invoking tool with function_args: {function_args}")
                # Here, you would typically call a method to invoke the tool
                # Example: tool_result = self._invoke_tool(function_args)

            if tool_id:
                logging_utility.info(f"Invoking tool with the ID: {tool_id}")
                # Here, you would typically call a method to invoke the tool
                # Example: tool_result = self._invoke_tool(function_args)

        except Exception as e:
            logging_utility.error(f"Error processing tool call with ID {tool_call.id}: {str(e)}")

    def on_tool_call_done(self, tool_call: Any):
        """
        Callback when a tool call is completed.
        """
        logging_utility.info(f"Tool call done: {tool_call.id}")
        self._current_tool_call = None


    def _get_tool_details(self):

        pass


    def _get_pending_actions(self, run_id: str) -> List[Any]:
        """
        Fetch pending actions for a run.
        """
        pending_actions = []
        try:
            pending_action_ids = self.action_service.get_actions_by_status(run_id, status="pending")
            if pending_action_ids:
                for action_id in pending_action_ids:
                    try:
                        action = self.action_service.get_action(action_id["id"])
                        if action:  # Ensure action is not None
                            pending_actions.append(action)
                    except Exception as e:
                        logging_utility.warning(f"Failed to retrieve action {action_id['id']}: {str(e)}")
        except Exception as e:
            logging_utility.error(f"Error fetching pending actions: {str(e)}")

        return pending_actions

    def _invoke_tool(self, function_args: Dict[str, Any]):
        """
        Placeholder method to invoke a tool.
        """
        # Implement tool invocation logic here
        logging_utility.info(f"Tool invoked with function_args: {function_args}")
        return {"result": "success"}