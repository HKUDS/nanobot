# Simplify with judgment

Use this guidance when cleaning up code, choosing between a patch and a refactor, or deciding whether a test earns its maintenance cost.

## Think before extending the code

Work out the required behavior, the facts available at the boundary, who owns each piece of state, and what actually causes the failure. Then choose the simplest coherent implementation. Do not begin by asking where another condition can be inserted into the current code.

Use your judgment. You are expected to understand the problem, not merely keep the current code limping along. If a solution needs another fallback, ask which broken contract it hides. If a helper needs more modes, ask whether it owns too many responsibilities. If the implementation is hard to explain, reconsider the design before adding another layer.

## Refactor when the structure is the problem

Refactor the owning path when it removes the cause: duplicated state, contradictory ownership, tangled control flow, or an abstraction that no longer fits its callers. Keep that refactor tied to the requested behavior and preserve unaffected contracts. A small diff is not a success if it leaves the defect embedded in the design.

Remove redundant checks inside trusted, validated paths. Validate untrusted input at its boundary and let internal code use that contract. Keep fallbacks only for supported, reachable failure modes with a defined result. Do not silently recover from broken internal invariants, retain speculative compatibility paths, or introduce frameworks for hypothetical future requirements. Preserve deliberate security checks and documented recovery contracts.

## Tests must earn their place

Prefer evidence for the supported user path and the important reachable regression. Reuse existing coverage when it already proves the contract.

- Do not add defensive cases for impossible internal states, unsupported combinations, or hypothetical failures without a reachable path and a material consequence.
- Avoid exhaustive mock permutations, assertions that mirror private implementation steps, and tests that merely prove old text or symbols disappeared.
- A prose edit, mechanical cleanup, or low-impact reversible change does not automatically need new tests. Use focused existing checks when sufficient.
- Test invalid input where a real untrusted boundary accepts it, security properties where a real capability exposes them, and recovery where the product promises it. These are supported contracts, not an invitation to test every imagined failure.

Choose each test because it could detect a meaningful contract failure. Once the relevant evidence is sufficient, stop adding cases.
