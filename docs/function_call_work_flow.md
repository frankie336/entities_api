<pre>
+--------------------------+
| process_function_calls   |
| (fc_state received)      |
+-----------+--------------+
            |
            | fc_state.name is NOT platform tool? -> YES
            V
+-----------+--------------+
| [Set processed = True]   |
| Call _process_tool_calls |
| (pass fc_state, run_id)  |
+-----------+--------------+
            |
            V
+--------------------------+     +-----------------+     +-----------------+
|   _process_tool_calls    |---->|  action_client  |---->| Action Storage  |
|                          |     | (create_action) |     | (Save Tool Inv.)|
+-----------+--------------+     +-----------------+     +-----------------+
            |
            V
+-----------+--------------+     +-----------------+     +-----------------+
| Update Run Status        |---->|   run_service   |---->|   Run Storage   |
| (to 'action_required')   |     | (update_status) |     | (run.status set)|
+-----------+--------------+     +-----------------+     +-----------------+
            |
            V
+-----------+--------------+
| Start Waiting Loop (poll)|<------------------------------------+
|   Check run.status       |                                     |
+-----------+--------------+                                     |
            |                                                     |
            | run.status == 'action_required'?                    |
            |   YES -> sleep(1), repeat check -------->----------->+
            |   NO  -> Break loop
            V                                      +--------------------------+
+-----------+--------------+                       | External Tool Executor   |
| Log "Wait Complete"      |                       |--------------------------|
| Return (value ignored)   |                       | 1. Detect 'action_req'   |
+--------------------------+                       | 2. Get action details    |
            |                                      | 3. RUN ACTUAL TOOL LOGIC |
            | Back in process_function_calls       | 4. Submit tool output    |
            V                                      | 5. Update run status     |
+-----------+--------------+                       |    (e.g., 'completed')   |
| Check 'if processed:'    |                       +------------+-------------+
| (True)                   |                                    | Updates
+-----------+--------------+                                    V
            |                                      +-----------------+
            V                                      |   Run Storage   |
+-----------+--------------+                       | (run.status updated) |
| Call                     |                       +-----------------+
| stream_function_call_out |
| (yields results)         |
+-----------+--------------+
            |
            V
+-----------+--------------+
| Chunks yielded to caller |
+--------------------------+
</pre>
