-- Prove continuous barrier soundness under uncertainty.
import LeanBarrier.Continuous

namespace LeanBarrier

def RobustClassicalTrajectory {n : ℕ} {ι : Type*}
    (flow : State n → ι → State n) (uncertaintySet : Set ι)
    (γ : ℝ → State n) : Prop :=
  ∃ w : ℝ → ι, (∀ t, w t ∈ uncertaintySet) ∧
    ∀ t, HasDerivAt γ (flow (γ t) (w t)) t

def RobustClassicalTrajectories {n : ℕ} {ι : Type*}
    (flow : State n → ι → State n) (uncertaintySet : Set ι) :
    Set (ℝ → State n) :=
  {γ | RobustClassicalTrajectory flow uncertaintySet γ}

def RobustStrictLiePositiveOn {n : ℕ} {ι : Type*}
    (X : Set (State n)) (B : State n → ℝ) (gradient : State n → State n)
    (flow : State n → ι → State n) (uncertaintySet : Set ι) : Prop :=
  ∀ x ∈ X, ∀ w ∈ uncertaintySet, B x = 0 →
    0 < ∑ i, gradient x i * flow x w i

theorem robust_continuous_strict_boundary_barrier_safety
    {n : ℕ} {ι : Type*}
    (B : State n → ℝ) (gradient : State n → State n)
    (flow : State n → ι → State n) (X unsafeSet : Set (State n))
    (uncertaintySet : Set ι)
    (hgradient : IsGradient B gradient)
    (hstrict : RobustStrictLiePositiveOn X B gradient flow uncertaintySet)
    (hunsafe : UnsafeSeparatedOn X B unsafeSet) :
    ConditionalSafetyIn B X unsafeSet
      (RobustClassicalTrajectories flow uncertaintySet) := by
  intro γ hγ hinit T hT hstay hreach
  rcases hγ with ⟨w, hw, hcurve⟩
  have hd : ∀ t, HasDerivAt (fun s => B (γ s))
      (∑ i, gradient (γ t) i * flow (γ t) (w t) i) t := by
    intro t
    simpa [Function.comp_def, gradientCLM_apply] using
      (hgradient (γ t)).comp_hasDerivAt t (hcurve t)
  have hsafe := strict_boundary_scalar_preserves_nonnegative
    (g := fun t => B (γ t))
    (g' := fun t => ∑ i, gradient (γ t) i * flow (γ t) (w t) i)
    hT hd
      (fun t ht hzero =>
        hstrict (γ t) (hstay t ⟨ht.1, ht.2.le⟩) (w t) (hw t) hzero)
      hinit
  exact (not_lt_of_ge hsafe) (hunsafe (γ T) (hstay T ⟨hT, le_rfl⟩) hreach)

end LeanBarrier
