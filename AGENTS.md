# Finance Tracker Agent Directive

Before changing this repository, read and follow `STRATEGIC_PROGRAMMING.md`.

Its strategic-programming rules are binding project invariants. They are not optional style guidance and must not be bypassed to finish a feature faster.

For every milestone:

1. inspect the whole project, not only the files changed by the feature;
2. run the required compile, pytest and ruff validation;
3. perform the mandatory milestone strategic review in `STRATEGIC_PROGRAMMING.md`;
4. resolve routine architectural debt discovered by that review before declaring the milestone complete;
5. record the review outcome as `STRATEGIC`, `STRATEGIC AFTER CLEANUP`, or `BLOCKED` in the milestone/PR notes.

A milestone with green tests but without its strategic review is incomplete.
