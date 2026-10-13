-- Prove continuous safety with constant uncertain parameters.
import LeanBarrier.Continuous

namespace LeanBarrier

def FixedParameterConditionalSafetyIn {n : ℕ} {ι : Type*}
    (B : State n → ℝ) (flow : State n → ι → State n)
    (parameterSet : Set ι) (X unsafeSet : Set (State n)) : Prop :=
  ∀ w ∈ parameterSet,
    ConditionalSafetyIn B X unsafeSet
      (ClassicalTrajectories (fun x => flow x w))

def FixedParameterStrictLiePositiveOn {n : ℕ} {ι : Type*}
    (X : Set (State n)) (B : State n → ℝ)
    (gradient : State n → State n) (flow : State n → ι → State n)
    (parameterSet : Set ι) : Prop :=
  ∀ x ∈ X, ∀ w ∈ parameterSet, B x = 0 →
    0 < ∑ i, gradient x i * flow x w i

theorem fixed_parameter_continuous_strict_boundary_barrier_safety
    {n : ℕ} {ι : Type*}
    (B : State n → ℝ) (gradient : State n → State n)
    (flow : State n → ι → State n) (parameterSet : Set ι)
    (X unsafeSet : Set (State n))
    (hgradient : IsGradient B gradient)
    (hstrict : FixedParameterStrictLiePositiveOn
      X B gradient flow parameterSet)
    (hunsafe : UnsafeSeparatedOn X B unsafeSet) :
    FixedParameterConditionalSafetyIn B flow parameterSet X unsafeSet := by
  intro w hw
  exact continuous_strict_boundary_barrier_safety
    B gradient (fun x => flow x w) X unsafeSet hgradient
      (fun x hx hzero => hstrict x hx w hw hzero) hunsafe

end LeanBarrier
