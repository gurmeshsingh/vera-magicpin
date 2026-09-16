Our judge harness. Deliberately a SUPERSET of the shipped judge_simulator.py, which:
  - never calls the LLM judge under its default TEST_SCENARIO="all"
  - returns True unconditionally from its three behavioural scenarios
  - ignores rationale and suppression_key
  - has no determinism / duplicate-send / suppression checks
  - never tests customer-facing conversation (customer_id is always null)
Ours covers all of the above plus the full 5-dimension rubric and the penalty terms.
