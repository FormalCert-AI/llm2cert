# DCB-OURS-P1-001: smt only

## run-20260925T152937Z-03441894

### candidates/00/synthesis/calls/0000.json

Model: `openai/gpt-5.6-sol`. Status: `completed`.

<details><summary>Prompt and recorded request settings</summary>

```text
Role:
You are a control theory expert specializing in Lyapunov functions. Propose one Lyapunov certificate V for the system below.

System information:
System name: DynaCertBench System 092 · DCB-OURS-P1-001 · 8D Rational-Cosine Ring
Problem id: dcb_ours_p1_001
System semantics: continuous-time
Dynamics: dx1/dt = ((-3 * x1) + ((x2 * cos(x1)) / ((x8)**2 + 1))); dx2/dt = ((-3 * x2) + ((x3 * cos(x2)) / ((x1)**2 + 1))); dx3/dt = ((-3 * x3) + ((x4 * cos(x3)) / ((x2)**2 + 1))); dx4/dt = ((-3 * x4) + ((x5 * cos(x4)) / ((x3)**2 + 1))); dx5/dt = ((-3 * x5) + ((x6 * cos(x1)) / ((x4)**2 + 1))); dx6/dt = ((-3 * x6) + ((x7 * cos(x2)) / ((x5)**2 + 1))); dx7/dt = ((-3 * x7) + ((x8 * cos(x3)) / ((x6)**2 + 1))); dx8/dt = ((-3 * x8) + ((x1 * cos(x4)) / ((x7)**2 + 1)))
State variables: x1, x2, x3, x4, x5, x6, x7, x8
Control variables: none
Formal state domain X: x1 in [-3, 3], x2 in [-3, 3], x3 in [-3, 3], x4 in [-3, 3], x5 in [-3, 3], x6 in [-3, 3], x7 in [-3, 3], x8 in [-3, 3]
FastCheck screening box: x1 in [-3, 3], x2 in [-3, 3], x3 in [-3, 3], x4 in [-3, 3], x5 in [-3, 3], x6 in [-3, 3], x7 in [-3, 3], x8 in [-3, 3]
Initial set X_i: none
Unsafe set X_u: none
Assumptions: Transcribed from active LaTeX System 92.; Decimal source constants are interpreted as exact rationals; no floating approximation enters Lean.
Task type: stability
Stability kind: global_exponential
Claimed domain: R^n
Origin policy: exclude_point

Mathematical framework:
The certificate is a Lyapunov function V, not a barrier. This task does not choose a level constant or a smaller certified sublevel: all claimed conditions are on the fixed domain R^n.
V(x*) = 0 at the equilibrium, and V(x) > 0 for every other point of the domain.
Exclude the equilibrium by the symbol x != x*, not by deleting a ball around it.
A sublevel set may appear in a conceptual Lyapunov argument, but it must not be used to exclude a counterexample from the fixed claimed domain.
Decrease rate: D_pi V = grad V · f.
Exponential stability: give positive rationals exp_c1, exp_c2, exp_c3 such that c1 ||x||^2 <= V(x) <= c2 ||x||^2 and D_pi V + c3 V <= 0 on R^n.
A finite-box dReal unsat is not a global theorem. Global positive conclusions must come from Lean 4 or unbounded polynomial SMT.

Objective:
Propose V in the certificate expression string and, only for exponential stability, the required exact decay constants. Do not introduce level_c or replace N by a candidate-chosen sublevel set. Do not change N. Never write verified, proved, certified, UNSAT, or globally valid unless that result is already in the supplied evidence.

Certificate-family discipline:
Choose the simplest certificate structure justified by the dynamics, domain, and verification conditions. Non-polynomial dynamics do not by themselves require a non-polynomial certificate. Use transcendental or rational terms only when construction_summary gives a concrete identity or inequality showing how they help close the required condition. Ensure every expression is well-defined on X. Structure examples only. Polynomial: for dx1/dt = -x1 + x1*x2 and dx2/dt = -x2 on x1**2 + x2**2 <= 1, V = x1**2 + x2**2 gives D V = -2*x1**2*(1-x2) - 2*x2**2 <= 0. Non-polynomial: for dx1/dt = -x1*(1+x1**2), V = log(1+x1**2) gives the exact identity D V = -2*x1**2, with 1+x1**2 > 0.

Constraints:
Use only declared state variables (x1, x2, x3, x4, x5, x6, x7, x8). Do not leave free symbols such as delta or epsilon. Every controller assignment must obey the Controller observations information pattern shown above; the pipeline rejects the candidate after parsing if an assignment reads any other state. Return certificate and controller expressions as concise strings; never emit recursive AST nodes. Numeric literals are parsed as exact rationals: 0.01 becomes 1/100, and 1/100 is also fine. The name pi denotes the exact constant Real.pi; do not replace it by a decimal approximation. Allowed function names: sin,cos,exp,tanh,log,sqrt,atan,ln,tan,sec,csc,cot,sinh,cosh,sech,csch,coth,arctan,atanh. log is the natural logarithm. sqrt(arg) requires arg >= 0 on X; atan is the two-sided inverse tangent; atanh(arg) may be used only when -1 < arg < 1 on X. Names other than sin,cos,exp,tanh,log,sqrt,atan are expanded to the stored AST before verification; for example sech(x1) becomes 2/(exp(x1)+exp(-x1)). The equivalent square-root spellings sqrt(x), x**(1/2), and x**0.5 are all accepted and normalized to the same exact AST. Division of expressions is allowed, for example x1**2/(1+x1**4); write parentheses when the denominator is a sum. Do not invent other function names and do not use Abs. The pipeline symbolically differentiates V and independently checks the continuous-time queries. construction_summary is a construction note, not a certificate; downstream Lean proof agents read it as their roadmap, so it must name the useful auxiliary quantities, give a factorised form of the Lie expression grad V dot f_cl in those quantities, and list the boundedness facts with explicit constants that close the sign inequality.

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
{"certificate":"x1**2 + x2**2 + x3**2 + x4**2 + x5**2 + x6**2 + x7**2 + x8**2","controllers":[],"construction_summary":"Let S=x1^2+x2^2+x3^2+x4^2+x5^2+x6^2+x7^2+x8^2 and define g1=cos(x1)/(1+x8^2), g2=cos(x2)/(1+x1^2), g3=cos(x3)/(1+x2^2), g4=cos(x4)/(1+x3^2), g5=cos(x1)/(1+x4^2), g6=cos(x2)/(1+x5^2), g7=cos(x3)/(1+x6^2), g8=cos(x4)/(1+x7^2). Then V=S and grad(V)·f=-6*S+2*(x1*x2*g1+x2*x3*g2+x3*x4*g3+x4*x5*g4+x5*x6*g5+x6*x7*g6+x7*x8*g7+x8*x1*g8). Since 1+xj^2>=1 and |cos(z)|<=1, each |gi|<=1. Thus 2*xi*xj*gi<=xi^2+xj^2 for every ring edge; summing the eight bounds gives the coupling sum at most 2*S, so grad(V)·f<=-4*S. Also V=S=||x||^2, hence c1=c2=1 and grad(V)·f+4*V<=0.","assumptions":[],"exp_c1":"1","exp_c2":"1","exp_c3":"4"}
```

### candidates/00/conditions/01-equilibrium_fixed/routing/calls/0000.json

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
{"condition":{"candidate_hash":"78600498afbde77a28b01bd300c84bb6934b9ecdd205346260f5162ab2440fdd","condition_id":"78600498afbd:01:equilibrium_fixed","description":"The closed-loop vector field must vanish at the equilibrium.","kind":"equilibrium_fixed","lean_theorem_name":"equilibrium_fixed","query":{"any_of":[{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x1"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x2"},{"arg":{"kind":"var","name":"x1"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x8"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x1"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x2"},{"arg":{"kind":"var","name":"x1"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x8"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x2"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x3"},{"arg":{"kind":"var","name":"x2"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x2"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x3"},{"arg":{"kind":"var","name":"x2"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x3"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x4"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x3"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x4"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x4"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x5"},{"arg":{"kind":"var","name":"x4"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x3"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x4"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x5"},{"arg":{"kind":"var","name":"x4"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x3"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x5"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x6"},{"arg":{"kind":"var","name":"x1"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x4"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x5"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x6"},{"arg":{"kind":"var","name":"x1"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x4"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x6"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x7"},{"arg":{"kind":"var","name":"x2"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x5"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x6"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x7"},{"arg":{"kind":"var","name":"x2"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x5"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x7"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x8"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x6"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x7"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x8"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x6"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x8"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x1"},{"arg":{"kind":"var","name":"x4"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x7"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]},{"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x8"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x1"},{"arg":{"kind":"var","name":"x4"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x7"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"},"relation":"lt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}]}],"constraints":[{"lhs":{"kind":"var","name":"x1"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x2"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x3"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x4"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x5"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x6"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x7"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}},{"lhs":{"kind":"var","name":"x8"},"relation":"eq","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":null,"variables":["x1","x2","x3","x4","x5","x6","x7","x8"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["cvc5"],"formally_bounded":false,"polynomial_nra":false,"transcendental":true}}

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
{"condition_id":"78600498afbd:01:equilibrium_fixed","route":"direct_lean","solver_order":[],"rationale":"The capability summary marks the query as transcendental, non-polynomial, and not formally bounded. Since the only eligible SMT backend is cvc5, direct Lean is preferred for this fixed-equilibrium condition."}
```

### candidates/00/conditions/06-exponential_decay/routing/calls/0001.json

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
{"condition":{"candidate_hash":"78600498afbde77a28b01bd300c84bb6934b9ecdd205346260f5162ab2440fdd","condition_id":"78600498afbd:06:exponential_decay","description":"There is no point on the claimed domain with D_pi V + c3 V > 0.","kind":"exponential_decay","lean_theorem_name":"exponential_decay","query":{"any_of":[],"constraints":[{"lhs":{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x1"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x1"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x2"},{"arg":{"kind":"var","name":"x1"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x8"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x2"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x2"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x3"},{"arg":{"kind":"var","name":"x2"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x3"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x3"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x4"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x4"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x4"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x5"},{"arg":{"kind":"var","name":"x4"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x3"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x5"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x5"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x6"},{"arg":{"kind":"var","name":"x1"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x4"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x6"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x6"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x7"},{"arg":{"kind":"var","name":"x2"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x5"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x7"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x7"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x8"},{"arg":{"kind":"var","name":"x3"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x6"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":2}},{"kind":"var","name":"x8"},{"args":[{"args":[{"kind":"const","value":{"denominator":1,"numerator":-3}},{"kind":"var","name":"x8"}],"kind":"mul"},{"kind":"div","left":{"args":[{"kind":"var","name":"x1"},{"arg":{"kind":"var","name":"x4"},"kind":"cos"}],"kind":"mul"},"right":{"args":[{"base":{"kind":"var","name":"x7"},"exponent":2,"kind":"pow"},{"kind":"const","value":{"denominator":1,"numerator":1}}],"kind":"add"}}],"kind":"add"}],"kind":"mul"},{"args":[{"kind":"const","value":{"denominator":1,"numerator":4}},{"args":[{"base":{"kind":"var","name":"x1"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x2"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x3"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x4"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x5"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x6"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x7"},"exponent":2,"kind":"pow"},{"base":{"kind":"var","name":"x8"},"exponent":2,"kind":"pow"}],"kind":"add"}],"kind":"mul"}],"kind":"add"},"relation":"gt","rhs":{"kind":"const","value":{"denominator":1,"numerator":0}}}],"formal_bounds":null,"variables":["x1","x2","x3","x4","x5","x6","x7","x8"]},"required":true,"schema_version":"lean-barrier.condition.v1"},"deterministic_capabilities":{"eligible_backends":["cvc5"],"formally_bounded":false,"polynomial_nra":false,"transcendental":true}}

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
{"condition_id":"78600498afbd:06:exponential_decay","route":"smt","solver_order":["cvc5"],"rationale":"The query is transcendental, not polynomial NRA, and lacks formal bounds. SMT is selected using the sole eligible backend; any result remains subject to independent checking and possible Lean4 rescue."}
```
