## Required form: position held by the ECC

This section replaces the Structure section above and the structure of the example above. The behaviour rules are unchanged, and correct behaviour still comes first.

The block's control position must be held by the ECC itself between two REQ events, and not by a variable that is read back on the next scan:

- Each position of the state machine has its own state, where the ECC stops and waits for REQ. START, which has no actions, can be one of them. Do not return to one common state
  on every scan.
- Each waiting state has its own REQ transition or transitions. `REQ[input condition]` is the way to take a path that overrides the normal step, for example one that applies from every position.
- No state may be passed through by every scan from every position.
- No guard may read a position from a variable that still holds its value from the previous scan. A step can leave through a guard on a condition, or on a variable that its own
  algorithm has just assigned in this scan.
- No algorithm may branch on such a variable to choose what to run. If it runs from several positions, it holds only logic that those positions really share.
- If the source publishes a state number as an output, keep assigning it wherever the source does. It is an output, and the ECC does not read it to find its position.
- If the source has no explicit state variable, find the positions that its logic implies.

This example has the same source as the example above, and its positions are held by the ECC:

```
{{EXAMPLE_PERSISTENT_FBT}}
```
