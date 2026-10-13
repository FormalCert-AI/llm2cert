# DCB-LIT-P4-012: routed

## run-20260925T124042Z-a2b20f2d

### candidates/00/conditions/03-lie_strict/routing/calls/0000.json

Model: `openai/gpt-5.6-sol`. Status: `completed`.

<details><summary>Prompt and recorded request settings</summary>

```text
Role:
Choose the verification backend for one fixed condition after the deterministic fast check has passed.

Goal:
Choose exactly direct_lean or smt. If smt is selected, rank every eligible solver exactly once.

Success criteria:
Use only the supplied deterministic capability summary. Do not attempt the proof and do not claim that the condition is valid.

Fixed inputs:
{"condition":{"candidate_hash":"5d6eb705dd3953e4beb9c48127bc0d2903d665353aec53f57af872d73de49b19","condition_id":"5d6eb705dd39:03:lie_strict","description":"There is no point in X with B=0 and L_f B <= 0.","kind":"lie_strict","lean_theorem_name":"lie_strict","query":{"any_of":[],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-10}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x3"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-4}}},{"lhs":{"kind":"var","name":"x3"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":4}}},{"lhs":{"args":[{"kind":"var","name":"x1"},{"kind":"var","name":"x2"},{"kind":"var","name":"x3"}],"kind":"add"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"args":[{"arg":{"kind":"var","name":"x3"},"kind":"sin"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"},{"arg":{"arg":{"kind":"var","name":"x3"},"kind":"sin"},"kind":"neg"},{"kind":"const","value":{"denominator":2,"numerator":3}}],"kind":"add"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":{"lower":{"x1":{"denominator":1,"numerator":-10},"x2":{"denominator":1,"numerator":-10},"x3":{"denominator":1,"numerator":-4}},"upper":{"x1":{"denominator":1,"numerator":10},"x2":{"denominator":1,"numerator":10},"x3":{"denominator":1,"numerator":4}}},"variables":["x1","x2","x3"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["cvc5","dreal"],"formally_bounded":true,"polynomial_nra":false,"transcendental":true}}

Constraints:
Do not change the condition or solver eligibility. direct_lean must return an empty solver_order. smt must return a complete permutation of the eligible backends. SMT results are checked independently and may be rescued by Lean4. When the counterexample query includes a bounded fixed parameter, keep it as an ordinary quantified query variable: UNSAT means no violating pair (x,w) exists and therefore establishes the uniform condition. Do not treat the parameter as a state coordinate or as a certificate variable.

Output schema:
{"$defs":{"Backend":{"enum":["z3","cvc5","yices","dreal"],"title":"Backend","type":"string"},"VerificationRoute":{"enum":["direct_lean","smt"],"title":"VerificationRoute","type":"string"}},"additionalProperties":false,"description":"One Agent decision for one condition.\n\nThe Agent chooses the verification backend and, when SMT is selected,\nsupplies a complete ordering of the eligible solver backends.","properties":{"condition_id":{"title":"Condition Id","type":"string"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"},"route":{"$ref":"#/$defs/VerificationRoute"},"solver_order":{"items":{"$ref":"#/$defs/Backend"},"title":"Solver Order","type":"array"}},"required":["condition_id","route","solver_order","rationale"],"title":"VerificationRouterDecision","type":"object"}

Stop rules:
Return exactly one JSON object and no Markdown.
```
```json
{
  "call_timeout_seconds": 120.0,
  "json_object_mode": false,
  "max_tokens": 16384,
  "provider": "gpt",
  "reasoning_effort": "high",
  "structured_outputs": false,
  "thinking": true,
  "thinking_budget": 4096
}
```
Recorded conversation:

```json
2
```

</details>

Response:

```text
{"condition_id":"5d6eb705dd39:03:lie_strict","route":"smt","solver_order":["dreal","cvc5"],"rationale":"The bounded query contains transcendental sine and cosine terms and is not polynomial NRA. dReal is prioritized for bounded nonlinear transcendental reasoning, followed by cvc5; the order is a complete permutation of the eligible backends."}
```

### candidates/00/conditions/00-unsafe_separation/routing/calls/0001.json

Model: `openai/gpt-5.6-sol`. Status: `completed`.

<details><summary>Prompt and recorded request settings</summary>

```text
Role:
Choose the verification backend for one fixed condition after the deterministic fast check has passed.

Goal:
Choose exactly direct_lean or smt. If smt is selected, rank every eligible solver exactly once.

Success criteria:
Use only the supplied deterministic capability summary. Do not attempt the proof and do not claim that the condition is valid.

Fixed inputs:
{"condition":{"candidate_hash":"5d6eb705dd3953e4beb9c48127bc0d2903d665353aec53f57af872d73de49b19","condition_id":"5d6eb705dd39:00:unsafe_separation","description":"No unsafe state in X may satisfy B(x) >= 0.","kind":"unsafe_separation","lean_theorem_name":"unsafe_separation","query":{"any_of":[],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-10}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x3"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-4}}},{"lhs":{"kind":"var","name":"x3"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":4}}},{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-9}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":-7}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-9}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":-6}}},{"lhs":{"kind":"var","name":"x3"},"relation":"ge","rhs":{"args":[{"kind":"const","value":{"denominator":2,"numerator":1}},{"arg":{"kind":"pi"},"kind":"neg"}],"kind":"mul"}},{"lhs":{"kind":"var","name":"x3"},"relation":"le","rhs":{"args":[{"kind":"const","value":{"denominator":2,"numerator":1}},{"kind":"pi"}],"kind":"mul"}},{"lhs":{"args":[{"kind":"var","name":"x1"},{"kind":"var","name":"x2"},{"kind":"var","name":"x3"}],"kind":"add"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":{"lower":{"x1":{"denominator":1,"numerator":-10},"x2":{"denominator":1,"numerator":-10},"x3":{"denominator":1,"numerator":-4}},"upper":{"x1":{"denominator":1,"numerator":10},"x2":{"denominator":1,"numerator":10},"x3":{"denominator":1,"numerator":4}}},"variables":["x1","x2","x3"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["cvc5","dreal"],"formally_bounded":true,"polynomial_nra":false,"transcendental":true}}

Constraints:
Do not change the condition or solver eligibility. direct_lean must return an empty solver_order. smt must return a complete permutation of the eligible backends. SMT results are checked independently and may be rescued by Lean4. When the counterexample query includes a bounded fixed parameter, keep it as an ordinary quantified query variable: UNSAT means no violating pair (x,w) exists and therefore establishes the uniform condition. Do not treat the parameter as a state coordinate or as a certificate variable.

Output schema:
{"$defs":{"Backend":{"enum":["z3","cvc5","yices","dreal"],"title":"Backend","type":"string"},"VerificationRoute":{"enum":["direct_lean","smt"],"title":"VerificationRoute","type":"string"}},"additionalProperties":false,"description":"One Agent decision for one condition.\n\nThe Agent chooses the verification backend and, when SMT is selected,\nsupplies a complete ordering of the eligible solver backends.","properties":{"condition_id":{"title":"Condition Id","type":"string"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"},"route":{"$ref":"#/$defs/VerificationRoute"},"solver_order":{"items":{"$ref":"#/$defs/Backend"},"title":"Solver Order","type":"array"}},"required":["condition_id","route","solver_order","rationale"],"title":"VerificationRouterDecision","type":"object"}

Stop rules:
Return exactly one JSON object and no Markdown.
```
```json
{
  "call_timeout_seconds": 120.0,
  "json_object_mode": false,
  "max_tokens": 16384,
  "provider": "gpt",
  "reasoning_effort": "high",
  "structured_outputs": false,
  "thinking": true,
  "thinking_budget": 4096
}
```
Recorded conversation:

```json
2
```

</details>

Response:

```text
{"condition_id":"5d6eb705dd39:00:unsafe_separation","route":"smt","solver_order":["dreal","cvc5"],"rationale":"The query is formally bounded but transcendental and not polynomial NRA. Use SMT, prioritizing dReal for bounded transcendental reasoning, followed by cvc5 as the remaining eligible backend."}
```

### candidates/00/conditions/01-initial_containment/routing/calls/0002.json

Model: `openai/gpt-5.6-sol`. Status: `completed`.

<details><summary>Prompt and recorded request settings</summary>

```text
Role:
Choose the verification backend for one fixed condition after the deterministic fast check has passed.

Goal:
Choose exactly direct_lean or smt. If smt is selected, rank every eligible solver exactly once.

Success criteria:
Use only the supplied deterministic capability summary. Do not attempt the proof and do not claim that the condition is valid.

Fixed inputs:
{"condition":{"candidate_hash":"5d6eb705dd3953e4beb9c48127bc0d2903d665353aec53f57af872d73de49b19","condition_id":"5d6eb705dd39:01:initial_containment","description":"No initial state in X may satisfy B(x) < 0.","kind":"initial_containment","lean_theorem_name":"initial_containment","query":{"any_of":[],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-10}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x3"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":-4}}},{"lhs":{"kind":"var","name":"x3"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":4}}},{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":4}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":6}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":4}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":6}}},{"lhs":{"kind":"var","name":"x3"},"relation":"ge","rhs":{"args":[{"kind":"const","value":{"denominator":2,"numerator":1}},{"arg":{"kind":"pi"},"kind":"neg"}],"kind":"mul"}},{"lhs":{"kind":"var","name":"x3"},"relation":"le","rhs":{"args":[{"kind":"const","value":{"denominator":2,"numerator":1}},{"kind":"pi"}],"kind":"mul"}},{"lhs":{"args":[{"kind":"var","name":"x1"},{"kind":"var","name":"x2"},{"kind":"var","name":"x3"}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":{"lower":{"x1":{"denominator":1,"numerator":-10},"x2":{"denominator":1,"numerator":-10},"x3":{"denominator":1,"numerator":-4}},"upper":{"x1":{"denominator":1,"numerator":10},"x2":{"denominator":1,"numerator":10},"x3":{"denominator":1,"numerator":4}}},"variables":["x1","x2","x3"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["cvc5","dreal"],"formally_bounded":true,"polynomial_nra":false,"transcendental":true}}

Constraints:
Do not change the condition or solver eligibility. direct_lean must return an empty solver_order. smt must return a complete permutation of the eligible backends. SMT results are checked independently and may be rescued by Lean4. When the counterexample query includes a bounded fixed parameter, keep it as an ordinary quantified query variable: UNSAT means no violating pair (x,w) exists and therefore establishes the uniform condition. Do not treat the parameter as a state coordinate or as a certificate variable.

Output schema:
{"$defs":{"Backend":{"enum":["z3","cvc5","yices","dreal"],"title":"Backend","type":"string"},"VerificationRoute":{"enum":["direct_lean","smt"],"title":"VerificationRoute","type":"string"}},"additionalProperties":false,"description":"One Agent decision for one condition.\n\nThe Agent chooses the verification backend and, when SMT is selected,\nsupplies a complete ordering of the eligible solver backends.","properties":{"condition_id":{"title":"Condition Id","type":"string"},"rationale":{"maxLength":1000,"minLength":1,"title":"Rationale","type":"string"},"route":{"$ref":"#/$defs/VerificationRoute"},"solver_order":{"items":{"$ref":"#/$defs/Backend"},"title":"Solver Order","type":"array"}},"required":["condition_id","route","solver_order","rationale"],"title":"VerificationRouterDecision","type":"object"}

Stop rules:
Return exactly one JSON object and no Markdown.
```
```json
{
  "call_timeout_seconds": 120.0,
  "json_object_mode": false,
  "max_tokens": 16384,
  "provider": "gpt",
  "reasoning_effort": "high",
  "structured_outputs": false,
  "thinking": true,
  "thinking_budget": 4096
}
```
Recorded conversation:

```json
2
```

</details>

Response:

```text
{"condition_id":"5d6eb705dd39:01:initial_containment","route":"smt","solver_order":["dreal","cvc5"],"rationale":"The capability summary marks the query as transcendental and non-polynomial NRA, so SMT is preferred, with dReal ranked first for transcendental real arithmetic and cvc5 retained as the other eligible backend."}
```
