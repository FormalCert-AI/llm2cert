-- Instantiate Lyapunov theorems on explicit systems.
import LeanBarrier.Lyapunov

open Function
open LeanBarrier.Lyapunov

namespace LeanBarrier.Lyapunov.Examples

example {T c : ℝ} (hT : 0 ≤ T) (hc : 1 ≤ c) :
    (fun x : ℝ => x) ((fun _ : ℝ => (1 : ℝ)) T) ≤ c := by
  let γ : ℝ → ℝ := fun _ => 1
  let lie : ℝ → ℝ := fun _ => 0
  have hγ : ContinuousOn γ (Set.Icc 0 T) := by
    fun_prop
  have hderiv : DerivativeAlong (fun x : ℝ => x) γ lie
      (interior (Set.Icc 0 T)) := by
    intro t ht
    change HasDerivAt (fun _ : ℝ => (1 : ℝ)) 0 t
    exact hasDerivAt_const t (1 : ℝ)
  have hlie : ∀ t ∈ interior (Set.Icc 0 T), lie (γ t) ≤ 0 := by
    intro t ht
    norm_num
  have hV : ContDiff ℝ 1 (fun x : ℝ => x) := contDiff_id
  exact superlevel_preserved_on_Icc hT hV hγ hderiv hlie hc

theorem discreteDecrease_sq_half :
    DiscreteDecrease (fun x : ℝ => x ^ 2) (fun x => x / 2) := by
  intro x
  nlinarith

theorem iterate_nonincreasing_sq_half (x : ℝ) (n : ℕ) :
    ((fun y : ℝ => y / 2)^[n] x) ^ 2 ≤ x ^ 2 :=
  iterate_nonincreasing discreteDecrease_sq_half x n

theorem iterate_geometric_sq_half (x : ℝ) (n : ℕ) :
    ((fun y : ℝ => y / 2)^[n] x) ^ 2 ≤ ((1 : ℝ) / 4) ^ n * x ^ 2 :=
  iterate_geometric_decay
    (V := fun z : ℝ => z ^ 2)
    (F := fun y : ℝ => y / 2)
    (ρ := (1 : ℝ) / 4)
    (by norm_num)
    (fun y => (by ring : (y / 2) ^ 2 = (1 / 4 : ℝ) * y ^ 2).le)
    x n

end LeanBarrier.Lyapunov.Examples
