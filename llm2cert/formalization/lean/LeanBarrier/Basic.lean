-- Define state spaces and discrete certificate soundness theorems.
import Mathlib

namespace LeanBarrier

abbrev State (n : ℕ) := Fin n → ℝ

def Superlevel {n : ℕ} (B : State n → ℝ) : Set (State n) :=
  {x | 0 ≤ B x}

def UnsafeSeparated {n : ℕ} (B : State n → ℝ) (unsafeSet : Set (State n)) : Prop :=
  ∀ x ∈ unsafeSet, B x < 0

def InitialContained {n : ℕ} (B : State n → ℝ) (initial : Set (State n)) : Prop :=
  ∀ x ∈ initial, 0 ≤ B x

def DiscreteForwardInvariant {n : ℕ} (step : State n → State n)
    (set : Set (State n)) : Prop :=
  ∀ x ∈ set, step x ∈ set

theorem discrete_superlevel_invariant {n : ℕ} (B : State n → ℝ)
    (step : State n → State n)
    (hstep : ∀ x, 0 ≤ B x → 0 ≤ B (step x)) :
    DiscreteForwardInvariant step (Superlevel B) := by
  intro x hx
  exact hstep x hx

theorem superlevel_avoids_unsafe {n : ℕ} (B : State n → ℝ)
    (unsafeSet : Set (State n)) (hsep : UnsafeSeparated B unsafeSet) :
    Disjoint (Superlevel B) unsafeSet := by
  rw [Set.disjoint_left]
  intro x hxSafe hxUnsafe
  exact (not_lt_of_ge hxSafe) (hsep x hxUnsafe)

theorem discrete_barrier_implies_safety {n : ℕ} (B : State n → ℝ)
    (step : State n → State n) (initial unsafeSet : Set (State n))
    (hinit : InitialContained B initial)
    (hunsafe : UnsafeSeparated B unsafeSet)
    (hstep : ∀ x, 0 ≤ B x → 0 ≤ B (step x)) :
    InitialContained B initial ∧
      DiscreteForwardInvariant step (Superlevel B) ∧
      Disjoint (Superlevel B) unsafeSet := by
  exact ⟨hinit, discrete_superlevel_invariant B step hstep,
    superlevel_avoids_unsafe B unsafeSet hunsafe⟩

end LeanBarrier
