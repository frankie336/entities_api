import json
import threading
import time
from typing import Any, Dict, Optional

from projectdavid import Entity

from entities_api.constants.assistant import PLATFORM_TOOLS
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class EntitiesEventHandler:
    """
    Event handler to monitor AI runs, detect triggered events, and handle callbacks dynamically.
    """

    def __init__(self, run_service, action_service=None, event_callback=None):
        self.run_service = run_service
        self.action_service = action_service
        self.event_callback = event_callback  # External callback for event handling
        self.active_monitors: Dict[str, threading.Thread] = {}
        self._current_run: Optional[Any] = None
        self._current_tool_call: Optional[Any] = None

        self._client = Entity()

    def start_monitoring(self, run_id: str):
        """
        Start monitoring a run asynchronously.
        """
        if run_id in self.active_monitors:
            logging_utility.info(f"Run {run_id} is already being monitored.")
            return

        monitor_thread = threading.Thread(
            target=self._monitor_run_status, args=(run_id,), daemon=True
        )
        self.active_monitors[run_id] = monitor_thread
        monitor_thread.start()
        logging_utility.info(f"Started monitoring run {run_id}")

    def _monitor_run_status(self, run_id: str):
        """
        Monitor the run's status and trigger corresponding event handlers.
        """
        while True:
            try:
                run = self.run_service.retrieve_run(run_id)
                logging_utility.info(f"Run {run_id} status: {run.status}")

                if run.status == "action_required":
                    self._emit_event("action_required", run)
                    break

                # Check for cancellation
                if run.status == "cancelled":
                    self._emit_event("cancelled", run)
                    break

                if run.status in {"completed", "failed"}:
                    self._emit_event("run_ended", run)
                    break

                time.sleep(2)
            except Exception as e:
                logging_utility.error(f"Error monitoring run {run_id}: {str(e)}")
                self._emit_event("error", str(e))
                break

        self.active_monitors.pop(run_id, None)

    def stop_monitoring(self, run_id: str):
        """
        Stop monitoring a run.
        """
        if run_id in self.active_monitors:
            thread = self.active_monitors.pop(run_id)
            thread.join(timeout=1)
            logging_utility.info(f"Stopped monitoring run {run_id}")

    def _emit_event(self, event_type: str, event_data: Any):
        """
        Emit an event and trigger the appropriate callback.
        """
        if self.event_callback:
            self.event_callback(event_type, event_data)

        if event_type == "action_required":
            self.on_action_required(event_data)
        elif event_type == "cancelled":
            self.on_cancelled(event_data)
        elif event_type == "run_ended":
            self.on_run_ended(event_data)
        elif event_type == "error":
            self.on_error(event_data)

    def on_action_required(self, run: Any):
        """
        Handle actions required for a run.
        """
        logging_utility.info(f"Action required for run: {run.id}")
        self._current_run = run

        # Fetch pending actions by calling get_actions_by_status, then get each action.
        pending_actions = []
        pending_action_ids = self.action_service.get_actions_by_status(
            run.id, status="pending"
        )
        if pending_action_ids:
            for action_id in pending_action_ids:
                try:
                    action = self.action_service.get_action(action_id["id"])
                    if action:
                        pending_actions.append(action)
                except Exception as e:
                    logging_utility.warning(
                        f"Failed to retrieve action {action_id['id']}: {str(e)}"
                    )

        if pending_actions:
            logging_utility.info(
                f"Processing {len(pending_actions)} actions for run {run.id}."
            )
            for action in pending_actions:
                self.on_tool_call_created(action)
        else:
            logging_utility.info(f"No pending actions for run {run.id}.")

    def on_run_ended(self, run: Any):
        """
        Handle when a run ends.
        """
        logging_utility.info(f"Run {run.id} ended with status: {run.status}")
        self._current_run = None

    def on_cancelled(self, run: Any):
        """
        Handle when a run is cancelled.
        """
        self._current_run = None

    def on_error(self, error: str):
        """
        Handle errors during monitoring.
        """
        logging_utility.error(f"Monitoring error: {error}")

    def on_tool_call_created(self, tool_call: Any):
        """
        Handle tool invocation when a tool call is created.
        """
        logging_utility.info(
            f"Tool call created: {tool_call.id} (Tool: {tool_call.tool_name})"
        )
        self._current_tool_call = tool_call

        # Check if the tool is in the excluded list
        if tool_call.tool_name in PLATFORM_TOOLS:
            logging_utility.info(
                f"Skipping emission for platform tool: {tool_call.tool_name}"
            )
            return

        try:
            tool_call_result = self._invoke_tool(tool_call)
            # Construct the event payload with additional context (thread_id and assistant_id).
            tool_event = {
                "event": "tool_invoked",
                "tool_call_id": tool_call.id,
                "tool_id": tool_call.tool_id,
                "tool_name": tool_call.tool_name,
                "function_args": tool_call.function_args,
                "result": tool_call_result,
                "thread_id": (
                    self._current_run.thread_id
                    if self._current_run and hasattr(self._current_run, "thread_id")
                    else None
                ),
                "assistant_id": (
                    self._current_run.assistant_id
                    if self._current_run and hasattr(self._current_run, "assistant_id")
                    else None
                ),
            }

            logging_utility.info(
                f"Emitting tool invoked event: {json.dumps(tool_event)}"
            )
            if self.event_callback:
                self.event_callback("tool_invoked", tool_event)

            # After processing the tool event, update the run status to "in_progress"
            if self._current_run:

                run_id = self._current_run.id
                # Update the run status to "in_progress" after handling the tool call.

                self._client.run_service.update_run_status(
                    run_id=run_id, new_status="in_progress"
                )

                logging_utility.info(
                    f"Run {run_id} status updated to in_progress after tool invocation."
                )

        except Exception as e:
            logging_utility.error(f"Error invoking tool: {str(e)}")

    def _invoke_tool(self, tool_call: Any):
        """
        Perform the actual tool invocation and return the result.
        """
        logging_utility.info(f"Invoking tool: {tool_call.tool_name}")
        # Replace with actual tool invocation logic as needed.
        return {"status": "success", "result": "Tool output"}

    def _submit_tool_output(self, tool_call: Any, tool_result: Any):
        """
        Submit the tool's result to the system.
        """
        logging_utility.info(
            f"Submitting result for tool {tool_call.tool_name}: {tool_result}"
        )
        self.action_service.submit_tool_result(tool_call.id, tool_result)
