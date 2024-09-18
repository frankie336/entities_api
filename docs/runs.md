# Runs

## Overview

Runs track the state of nine  steps in the user prompt assistant response life cycle . 

| **Status**         | **Definition**                                                                                                                                                                                                                                                                 |
|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **queued**         | When Runs are first created or when you complete the `required_action`, they are moved to a queued status. They should almost immediately move to `in_progress`.                                                                                                                |
| **in_progress**    | While in progress, the Assistant uses the model and tools to perform steps. You can view progress being made by the Run by examining the Run Steps.                                                                                                                             |
| **completed**      | The Run successfully completed! You can now view all Messages the Assistant added to the Thread, and all the steps the Run took. You can also continue the conversation by adding more user Messages to the Thread and creating another Run.                                  |
| **requires_action**| When using the Function calling tool, the Run will move to a `requires_action` state once the model determines the names and arguments of the functions to be called. You must then run those functions and submit the outputs before the run proceeds.                           |
| **expired**        | This happens when the function calling outputs were not submitted before `expires_at` and the run expires. Additionally, if the run takes too long to execute and goes beyond the time stated in `expires_at`, the system will expire the run.                                 |
| **cancelling**     | You can attempt to cancel an `in_progress` run using the Cancel Run endpoint. Once the attempt to cancel succeeds, the status of the Run moves to `cancelled`. Cancellation is attempted but not guaranteed.                                                                    |
| **cancelled**      | Run was successfully cancelled.                                                                                                                                                                                                                                                |
| **failed**         | You can view the reason for the failure by looking at the `last_error` object in the Run. The timestamp for the failure will be recorded under `failed_at`.                                                                                                                    |
| **incomplete**     | Run ended due to `max_prompt_tokens` or `max_completion_tokens` being reached. You can view the specific reason by looking at the `incomplete_details` object in the Run.                                                                                                       |
