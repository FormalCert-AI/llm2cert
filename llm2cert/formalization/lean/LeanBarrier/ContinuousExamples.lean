-- Verify the continuous-time running example.
import LeanBarrier.ContinuousCore

namespace LeanBarrier.ContinuousCore.Examples

open scoped BigOperators Matrix

noncomputable def paperBarrier (x : State 4) : ℝ :=
  25 - (x 0 - 9 / 2) ^ 2 - (x 1 - 3 / 2) ^ 2 - (x 2) ^ 2 - (x 3) ^ 2

noncomputable def paperGradient (x : State 4) : State 4 :=
  ![-2 * (x 0 - 9 / 2), -2 * (x 1 - 3 / 2), -2 * x 2, -2 * x 3]

noncomputable def paperFlow (x : State 4) : State 4 :=
  ![-x 0 + 9 / 2, x 0 - x 1 - 3, -(1 / 2) * x 2, -(3 / 10) * x 3]

def paperInitialSet : Set (State 4) :=
  {x | 7 / 4 ≤ x 0 ∧ x 0 ≤ 9 / 4 ∧
    7 / 4 ≤ x 1 ∧ x 1 ≤ 9 / 4 ∧
    -(1 / 10) ≤ x 2 ∧ x 2 ≤ 1 / 10 ∧
    -(1 / 10) ≤ x 3 ∧ x 3 ≤ 1 / 10}

def paperUnsafeSet : Set (State 4) :=
  {x | 9 ≤ x 0 ∧ x 0 ≤ 10 ∧ 9 ≤ x 1 ∧ x 1 ≤ 10 ∧
    -5 ≤ x 2 ∧ x 2 ≤ 5 ∧ -5 ≤ x 3 ∧ x 3 ≤ 5}

theorem paperBarrier_isGradient : IsGradient paperBarrier paperGradient := by
  intro x
  have h0 : HasFDerivAt (fun y : State 4 => y 0)
      (ContinuousLinearMap.proj (R := ℝ) 0) x := hasFDerivAt_apply (𝕜 := ℝ) 0 x
  have h1 : HasFDerivAt (fun y : State 4 => y 1)
      (ContinuousLinearMap.proj (R := ℝ) 1) x := hasFDerivAt_apply (𝕜 := ℝ) 1 x
  have h2 : HasFDerivAt (fun y : State 4 => y 2)
      (ContinuousLinearMap.proj (R := ℝ) 2) x := hasFDerivAt_apply (𝕜 := ℝ) 2 x
  have h3 : HasFDerivAt (fun y : State 4 => y 3)
      (ContinuousLinearMap.proj (R := ℝ) 3) x := hasFDerivAt_apply (𝕜 := ℝ) 3 x
  have h := (((h0.sub_const (9 / 2)).pow 2).const_sub 25).sub
    ((h1.sub_const (3 / 2)).pow 2) |>.sub (h2.pow 2) |>.sub (h3.pow 2)
  change HasFDerivAt paperBarrier (gradientCLM (paperGradient x)) x
  apply h.congr_fderiv
  ext v
  simp [paperGradient, Fin.sum_univ_succ]
  ring

theorem paper_lie_identity (x : State 4) :
    ∑ i, paperGradient x i * paperFlow x i =
      2 * (x 0 - 9 / 2) ^ 2
        - 2 * (x 0 - 9 / 2) * (x 1 - 3 / 2)
        + 2 * (x 1 - 3 / 2) ^ 2
        + (x 2) ^ 2 + (3 / 5) * (x 3) ^ 2 := by
  simp [paperGradient, paperFlow, Fin.sum_univ_succ]
  ring

theorem paper_lie_nonnegative (x : State 4) :
    0 ≤ ∑ i, paperGradient x i * paperFlow x i := by
  rw [paper_lie_identity]
  nlinarith [sq_nonneg ((x 0 - 9 / 2) - (x 1 - 3 / 2)),
    sq_nonneg (x 2), sq_nonneg (x 3)]

theorem paper_initial_contained : InitialContained paperBarrier paperInitialSet := by
  intro x hx
  rcases hx with ⟨hx0l, hx0u, hx1l, hx1u, hx2l, hx2u, hx3l, hx3u⟩
  have h0 : (x 0 - 9 / 2) ^ 2 ≤ (11 / 4 : ℝ) ^ 2 := by
    have hp : 0 ≤ ((x 0 - 9 / 2) + 11 / 4) * (11 / 4 - (x 0 - 9 / 2)) :=
      mul_nonneg (by linarith) (by linarith)
    nlinarith
  have h1 : (x 1 - 3 / 2) ^ 2 ≤ (3 / 4 : ℝ) ^ 2 := by
    have hp : 0 ≤ (3 / 4 - (x 1 - 3 / 2)) * ((x 1 - 3 / 2) + 3 / 4) :=
      mul_nonneg (by linarith) (by linarith)
    nlinarith
  have h2 : (x 2) ^ 2 ≤ (1 / 10 : ℝ) ^ 2 := by
    have hp : 0 ≤ (1 / 10 - x 2) * (x 2 + 1 / 10) :=
      mul_nonneg (by linarith) (by linarith)
    nlinarith
  have h3 : (x 3) ^ 2 ≤ (1 / 10 : ℝ) ^ 2 := by
    have hp : 0 ≤ (1 / 10 - x 3) * (x 3 + 1 / 10) :=
      mul_nonneg (by linarith) (by linarith)
    nlinarith
  unfold paperBarrier
  nlinarith

theorem paper_unsafe_separated : UnsafeSeparated paperBarrier paperUnsafeSet := by
  intro x hx
  rcases hx with ⟨hx0l, _hx0u, hx1l, _hx1u, _hx2l, _hx2u, _hx3l, _hx3u⟩
  have h0 : (9 / 2 : ℝ) ^ 2 ≤ (x 0 - 9 / 2) ^ 2 := by
    have hp : 0 ≤ ((x 0 - 9 / 2) - 9 / 2) * ((x 0 - 9 / 2) + 9 / 2) :=
      mul_nonneg (by linarith) (by linarith)
    nlinarith
  have h1 : (15 / 2 : ℝ) ^ 2 ≤ (x 1 - 3 / 2) ^ 2 := by
    have hp : 0 ≤ ((x 1 - 3 / 2) - 15 / 2) * ((x 1 - 3 / 2) + 15 / 2) :=
      mul_nonneg (by linarith) (by linarith)
    nlinarith
  unfold paperBarrier
  nlinarith [sq_nonneg (x 2), sq_nonneg (x 3)]

theorem paper_running_example_forwardInvariant :
    ForwardInvariantAlong (ClassicalTrajectories paperFlow)
      (Superlevel paperBarrier) := by
  exact continuous_global_lie_nagumo paperBarrier paperGradient paperFlow
    paperBarrier_isGradient paper_lie_nonnegative

theorem paper_running_example_safety :
    InitialContained paperBarrier paperInitialSet ∧
      ForwardInvariantAlong (ClassicalTrajectories paperFlow) (Superlevel paperBarrier) ∧
      Disjoint (Superlevel paperBarrier) paperUnsafeSet := by
  exact ⟨paper_initial_contained, paper_running_example_forwardInvariant,
    superlevel_avoids_unsafe paperBarrier paperUnsafeSet paper_unsafe_separated⟩

end LeanBarrier.ContinuousCore.Examples
