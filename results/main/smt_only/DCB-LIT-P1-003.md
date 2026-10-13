# DCB-LIT-P1-003: smt only

## run-20260925T140716Z-ec2d23da

### candidates/00/synthesis/calls/0000.json

Model: `openai/gpt-5.6-sol`. Status: `completed`.

<details><summary>Prompt and recorded request settings</summary>

```text
Role:
You are a control theory expert specializing in Lyapunov functions. Propose one Lyapunov certificate V for the system below.

System information:
System name: DynaCertBench System 003 · DCB-LIT-P1-003 · Table~1 row~2 (NonPoly1), \cite{abate2021fossil}
Problem id: dcb_lit_p1_003
System semantics: continuous-time
Dynamics: dx1/dt = (-(x1) + (2 * (x1)**2 * x2)); dx2/dt = -(x2)
State variables: x1, x2
Control variables: none
Formal state domain X: x1 in [0, 10], x2 in [0, 10]
FastCheck screening box: x1 in [0, 10], x2 in [0, 10]
Initial set X_i: none
Unsafe set X_u: none
Assumptions: Deterministically normalized from canonical record DCB-LIT-P1-003.; Decimal source constants are interpreted as exact rationals; no floating approximation enters Lean.
Task type: stability
Stability kind: local_asymptotic
Claimed domain: bounded N
Origin policy: exclude_point

Mathematical framework:
The certificate is a Lyapunov function V, not a barrier. This task does not choose a level constant or a smaller certified sublevel: all claimed conditions are on the fixed domain the neighborhood N.
V(x*) = 0 at the equilibrium, and V(x) > 0 for every other point of the domain.
Exclude the equilibrium by the symbol x != x*, not by deleting a ball around it.
A sublevel set may appear in a conceptual Lyapunov argument, but it must not be used to exclude a counterexample from the fixed claimed domain.
Decrease rate: D_pi V = grad V · f.
Asymptotic stability: D_pi V < 0 on the domain minus the equilibrium.

Objective:
Propose V in the certificate expression string and, only for exponential stability, the required exact decay constants. Do not introduce level_c or replace N by a candidate-chosen sublevel set. Do not change N. Never write verified, proved, certified, UNSAT, or globally valid unless that result is already in the supplied evidence.

Certificate-family discipline:
Choose the simplest certificate structure justified by the dynamics, domain, and verification conditions. Non-polynomial dynamics do not by themselves require a non-polynomial certificate. Use transcendental or rational terms only when construction_summary gives a concrete identity or inequality showing how they help close the required condition. Ensure every expression is well-defined on X. Structure examples only. Polynomial: for dx1/dt = -x1 + x1*x2 and dx2/dt = -x2 on x1**2 + x2**2 <= 1, V = x1**2 + x2**2 gives D V = -2*x1**2*(1-x2) - 2*x2**2 <= 0. Non-polynomial: for dx1/dt = -x1*(1+x1**2), V = log(1+x1**2) gives the exact identity D V = -2*x1**2, with 1+x1**2 > 0.

Constraints:
Use only declared state variables (x1, x2). Do not leave free symbols such as delta or epsilon. Every controller assignment must obey the Controller observations information pattern shown above; the pipeline rejects the candidate after parsing if an assignment reads any other state. Return certificate and controller expressions as concise strings; never emit recursive AST nodes. Numeric literals are parsed as exact rationals: 0.01 becomes 1/100, and 1/100 is also fine. The name pi denotes the exact constant Real.pi; do not replace it by a decimal approximation. Allowed function names: sin,cos,exp,tanh,log,sqrt,atan,ln,tan,sec,csc,cot,sinh,cosh,sech,csch,coth,arctan,atanh. log is the natural logarithm. sqrt(arg) requires arg >= 0 on X; atan is the two-sided inverse tangent; atanh(arg) may be used only when -1 < arg < 1 on X. Names other than sin,cos,exp,tanh,log,sqrt,atan are expanded to the stored AST before verification; for example sech(x1) becomes 2/(exp(x1)+exp(-x1)). The equivalent square-root spellings sqrt(x), x**(1/2), and x**0.5 are all accepted and normalized to the same exact AST. Division of expressions is allowed, for example x1**2/(1+x1**4); write parentheses when the denominator is a sum. Do not invent other function names and do not use Abs. The pipeline symbolically differentiates V and independently checks the continuous-time queries. construction_summary is a construction note, not a certificate; downstream Lean proof agents read it as their roadmap, so it must name the useful auxiliary quantities, give a factorised form of the Lie expression grad V dot f_cl in those quantities, and list the boundedness facts with explicit constants that close the sign inequality.

Output schema:
{"$defs":{"ControllerProposal":{"additionalProperties":false,"description":"One concise controller expression returned by the synthesis model.","properties":{"expression":{"maxLength":20000,"minLength":1,"title":"Expression","type":"string"},"variable":{"pattern":"^[A-Za-z_][A-Za-z0-9_]*$","title":"Variable","type":"string"}},"required":["variable","expression"],"title":"ControllerProposal","type":"object"}},"additionalProperties":false,"description":"P1 synthesis contract: the claimed domain is fixed, so there is no level_c.","properties":{"assumptions":{"items":{"type":"string"},"title":"Assumptions","type":"array"},"certificate":{"maxLength":20000,"minLength":1,"title":"Certificate","type":"string"},"construction_summary":{"maxLength":2000,"minLength":1,"title":"Construction Summary","type":"string"},"controllers":{"items":{"$ref":"#/$defs/ControllerProposal"},"title":"Controllers","type":"array"},"exp_c1":{"anyOf":[{"maxLength":20000,"minLength":1,"type":"string"},{"type":"null"}],"title":"Exp C1"},"exp_c2":{"anyOf":[{"maxLength":20000,"minLength":1,"type":"string"},{"type":"null"}],"title":"Exp C2"},"exp_c3":{"anyOf":[{"maxLength":20000,"minLength":1,"type":"string"},{"type":"null"}],"title":"Exp C3"}},"required":["certificate","controllers","construction_summary","assumptions","exp_c1","exp_c2","exp_c3"],"title":"StabilityCandidateProposal","type":"object"}

Stop rules:
Return exactly one JSON object matching the schema. Put B or V in the certificate string. Put each control law in controllers[].expression. Do not output certificate_ast, controller_ast, kind, left, right, args, numerator, or denominator nodes. Never replace a failed attempt with a placeholder linear form just to return something.
```
```json
{
  "call_timeout_seconds": 300.0,
  "json_object_mode": false,
  "max_tokens": 16384,
  "provider": "gpt",
  "reasoning_effort": "high",
  "structured_outputs": false,
  "thinking": true,
  "thinking_budget": 16000
}
```
Recorded conversation:

```json
2
```

</details>

Response:

```text
{"certificate":"x1**2/(1+x1**2) + x2**2","controllers":[],"construction_summary":"Let d = 1+x1**2 and q = x1*x2. Then V = x1**2/d+x2**2, and grad(V)·f = -2*(x2**2*(1+2*x1**2)+x1**2*(q-1)**2)/d**2. On N, 0 <= x1**2 <= 100, 0 <= x2**2 <= 100, 0 <= q <= 100, and 1 <= d <= 101, hence 1 <= d**2 <= 10201. Both numerator terms are nonnegative. Their sum can vanish only if x2=0 and then x1**2*(q-1)**2=x1**2=0, so only at the origin. Also V=0 only at the origin and V>0 elsewhere.","assumptions":["0 <= x1 <= 10","0 <= x2 <= 10","The equilibrium is (0,0); strict positivity and decrease are required for (x1,x2) != (0,0)."],"exp_c1":null,"exp_c2":null,"exp_c3":null}
```

### candidates/00/conditions/02-v_at_equilibrium/routing/calls/0000.json

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
{"condition":{"candidate_hash":"3a0efae08c406cac6b13c8c1eaddf86b4f6132d6428434e42f866497452d1a9a","condition_id":"3a0efae08c40:02:v_at_equilibrium","description":"V must vanish at the equilibrium.","kind":"v_at_equilibrium","lean_theorem_name":"v_at_equilibrium","query":{"any_of":[{"constraints":[{"lhs":{"args":[{"kind":"div","left":{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},"right":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"kind":"div","left":{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},"right":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]}],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x2"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":null,"variables":["x1","x2"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["z3","cvc5","yices"],"formally_bounded":false,"polynomial_nra":false,"transcendental":false}}

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
{"condition_id":"3a0efae08c40:02:v_at_equilibrium","route":"direct_lean","solver_order":[],"rationale":"The capability summary marks the query as unbounded and non-polynomial, making direct Lean the preferred verification route over the eligible SMT backends."}
```

### candidates/00/conditions/03-positive_definite/routing/calls/0001.json

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
{"condition":{"candidate_hash":"3a0efae08c406cac6b13c8c1eaddf86b4f6132d6428434e42f866497452d1a9a","condition_id":"3a0efae08c40:03:positive_definite","description":"V must be positive away from the equilibrium on the claimed domain.","kind":"positive_definite","lean_theorem_name":"positive_definite","query":{"any_of":[],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":100}}},{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"args":[{"kind":"div","left":{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},"right":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":{"lower":{"x1":{"denominator":1,"numerator":0},"x2":{"denominator":1,"numerator":0}},"upper":{"x1":{"denominator":1,"numerator":10},"x2":{"denominator":1,"numerator":10}}},"variables":["x1","x2"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["z3","cvc5","yices","dreal"],"formally_bounded":true,"polynomial_nra":false,"transcendental":false}}

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
{"condition_id":"3a0efae08c40:03:positive_definite","route":"smt","solver_order":["dreal","cvc5","z3","yices"],"rationale":"The query is formally bounded and non-transcendental but is not polynomial NRA, so bounded nonlinear SMT is preferred over direct Lean. dReal is ranked first for bounded nonlinear real arithmetic, followed by cvc5, z3, and yices."}
```

### candidates/00/conditions/04-lie_negative/routing/calls/0002.json

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
{"condition":{"candidate_hash":"3a0efae08c406cac6b13c8c1eaddf86b4f6132d6428434e42f866497452d1a9a","condition_id":"3a0efae08c40:04:lie_negative","description":"There is no point away from the equilibrium with D_pi V >= 0.","kind":"lie_negative","lean_theorem_name":"lie_negative","query":{"any_of":[],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x1"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x2"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":10}}},{"lhs":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"le","rhs":{"kind":"const","value":{"denominator":1,"numerator":100}}},{"lhs":{"kind":"var","name":"x1"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x2"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"args":[{"args":[{"kind":"div","left":{"kind":"sub","left":{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x1"},{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}],"kind":"mul"},"right":{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"var","name":"x1"}],"kind":"mul"}},"right":{"base":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"},"exponent":2,"kind":"pow"}},{"args":[{"arg":{"kind":"var","name":"x1"},"kind":"neg"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"var","name":"x2"}],"kind":"mul"}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x2"},{"arg":{"kind":"var","name":"x2"},"kind":"neg"}],"kind":"mul"}],"kind":"add"},"relation":"ge","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":{"lower":{"x1":{"denominator":1,"numerator":0},"x2":{"denominator":1,"numerator":0}},"upper":{"x1":{"denominator":1,"numerator":10},"x2":{"denominator":1,"numerator":10}}},"variables":["x1","x2"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["z3","cvc5","yices","dreal"],"formally_bounded":true,"polynomial_nra":false,"transcendental":false}}

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
{"condition_id":"3a0efae08c40:04:lie_negative","route":"smt","solver_order":["dreal","cvc5","z3","yices"],"rationale":"The query is formally bounded and non-transcendental, but it is not polynomial NRA because it contains division. SMT is therefore preferred over direct Lean, with dReal ranked first for bounded nonlinear real arithmetic, followed by cvc5, z3, and yices."}
```
