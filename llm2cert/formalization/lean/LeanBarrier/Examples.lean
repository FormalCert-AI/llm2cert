-- Instantiate certificate theorems on discrete and continuous examples.
import LeanBarrier.Basic
import LeanBarrier.Continuous

namespace LeanBarrier.Examples

def discreteBarrier (x : State 1) : ℝ := x 0
def discreteStep (x : State 1) : State 1 := ![x 0 + 1]

example : DiscreteForwardInvariant discreteStep (Superlevel discreteBarrier) := by
  apply discrete_superlevel_invariant
  intro x hx
  change 0 ≤ x 0 at hx
  change 0 ≤ x 0 + 1
  linarith

end LeanBarrier.Examples
