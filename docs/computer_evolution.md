# Computer Tool — Proactive Deployment Strategy

---

## Situations where the assistant should proactively reach for the computer tool without being asked

### Information that goes stale
- Current prices, stock data, exchange rates

This is a great idea. 

But we need to work out a smooth path since many premium sources are 
packed behind api keys etc.

We also need to distinguish  the overlap between this and the web search tool

But, a solid idea.



- Weather, news, sports scores

A solid idea, but we also need to distinguish: why this over the web search tool?


- Package versions, API availability checks
- "Is X still maintained?" type questions

A solid idea

### Anything involving a file the user mentioned
- User pastes a CSV path — just read it, don't ask

We are not open claw. Computer does not have local user access
However , it would be bad ass if we could work out a way
to pass local paths into it. Might be a challenge becase
the docker instance is not on the user local machine.



- User mentions a log file — tail it, grep it
- User wants to know what's in a directory — just `ls`
Same as above

### Math and data that benefits from verification
- Complex calculations — run them in Python rather than reasoning through them
- Statistical summaries of data the user provides
- Anything where "I think the answer is" is worse than "I ran it and the answer is"

Solid idea, but overlaps with what code_interpreter does.

### Research that requires real content
- Scrape the actual page instead of guessing what's on it

Web search already does this

In fact , we have mitgated the implicit context hygene  issues through 
we search.


- Download a dataset and describe it from ground truth

Interesting idea. Download files  - we might have to mitigare maximum file size.


- Check if a URL is live and what it returns

### Software and environment questions
- "Does this code work?" — run it and find out

Solid idea, make sure that installs in one session do not contaminate other tennants or sessions.

- "What version of X is installed?" — check rather than assume
- "Will this dependency conflict?" — install it in a throwaway env and test

### Tasks that are just better automated
- File conversion (PDF to text, image to base64, etc.)

Some overlap with code intepreter, but I can see computer being a more 
superior version of the same.

- Bulk renaming, searching, filtering
- Generating files the user will actually download

Would be great to perfect file generation ability.

- Running a pipeline end to end rather than showing pseudocode

A solid idea - we need to mitigate ephemeral file cleans up.

### Diagnostic tasks
- Network connectivity checks
- Port availability
- Disk space, memory, process inspection
- API endpoint testing with curl

---

## Gap Analysis — Where we need to get to

### System prompt
- Needs explicit instruction that the assistant should treat computer use as the **default** for any of the above categories, not a fallback
- Currently the assistant only reaches for it when the user explicitly implies code execution

### Permissions
- Currently horrendously permissive — experimenting
- Before making computer use more prominent, sandboxing strategy needs to be defined
- Outbound network from the shell is the big one — useful for scraping and API calls, but wide open is a risk

Tell me what you need to see next  for that.

We could compare it to code interpreter.




### Output integration
- The terminal and the chat response are currently two separate things
- The assistant should be summarising what it found *from* the shell output back into the conversation
- Right now a user has to read the terminal themselves to know what happened

Actually, this is already the case, the assistant already sees output and summarizes.

We could make it more explicit, let the assistant know that  the user sees the screen, so 
be helpful and explicit where needed, but avoid duplicating the output.

### Session continuity signalling
- The assistant doesn't currently communicate to the user that the shell is persistent
- "I've installed pandas in your session — it'll be available for the rest of this conversation" is a completely different UX than what exists now

A solid idea.

### File output pathway
- If the assistant generates a file in the shell, there is currently no clean way for the user to get it
- This is a major missing piece for making computer use feel useful rather than just impressive

A solid idea. Code interpreter does this. We could explore and follow the same approach. 

Just let me know what you neeed.