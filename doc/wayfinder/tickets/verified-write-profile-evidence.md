# Define Evidence for a Verified Write Profile

**Type:** Research  
**Status:** Closed  
**Blocks:** Enabling any additional schema profile for live writes

## Question

What minimal automated database evidence and manual MoneyWiz application
evidence must be recorded before a recognized schema profile is promoted to a
verified write profile?

## Resolution

The unit of approval is a verified write capability: one profile and one writer
operation. The evidence is a sanitized profile fixture with automated
postconditions, followed by a controlled app-created test-store run that proves
the operation, reopen, new-transaction, sync, and inverse-operation paths.
The detailed rationale and lifecycle are in
[Compatibility Strategies Research](../research/compatibility-strategies.md).
