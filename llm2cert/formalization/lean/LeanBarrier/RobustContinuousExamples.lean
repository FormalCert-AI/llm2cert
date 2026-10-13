-- Instantiate robust continuous certificate theorems.
import LeanBarrier.RobustContinuous

namespace LeanBarrier.RobustContinuous.Examples

open scoped BigOperators Matrix

abbrev HiOrd8Uncertainty := ℝ × ℝ

def hiOrd8UncertaintySet : Set HiOrd8Uncertainty :=
  {w | 1 / 2 ≤ w.1 ∧ w.1 ≤ 2 ∧ -(1 / 5) ≤ w.2 ∧ w.2 ≤ 1 / 5}

noncomputable def hiOrd8Barrier (x : State 8) : ℝ :=
  576 * x 0 + 1824 * x 1 + 2356 * x 2 + 1624 * x 3 +
    649 * x 4 + 151 * x 5 + 19 * x 6 + x 7 + 12959

noncomputable def hiOrd8Gradient (_x : State 8) : State 8 :=
  ![576, 1824, 2356, 1624, 649, 151, 19, 1]

noncomputable def hiOrd8Flow (x : State 8) (w : HiOrd8Uncertainty) : State 8 :=
  ![x 1, x 2, x 3, x 4, x 5, x 6, x 7,
    -(20 * x 7 + 170 * x 6 + 800 * x 5 + 2273 * x 4 +
      3980 * x 3 + 4180 * x 2 + 2400 * x 1 + 576 * x 0 +
      Real.sin (w.1 * x 0) + w.2)]

def hiOrd8Domain : Set (State 8) :=
  {x | -(11 / 5) ≤ x 0 ∧ x 0 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 1 ∧ x 1 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 2 ∧ x 2 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 3 ∧ x 3 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 4 ∧ x 4 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 5 ∧ x 5 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 6 ∧ x 6 ≤ 11 / 5 ∧
    -(11 / 5) ≤ x 7 ∧ x 7 ≤ 11 / 5}

def hiOrd8InitialSet : Set (State 8) :=
  {x | 9 / 10 ≤ x 0 ∧ x 0 ≤ 11 / 10 ∧
    9 / 10 ≤ x 1 ∧ x 1 ≤ 11 / 10 ∧
    9 / 10 ≤ x 2 ∧ x 2 ≤ 11 / 10 ∧
    9 / 10 ≤ x 3 ∧ x 3 ≤ 11 / 10 ∧
    9 / 10 ≤ x 4 ∧ x 4 ≤ 11 / 10 ∧
    9 / 10 ≤ x 5 ∧ x 5 ≤ 11 / 10 ∧
    9 / 10 ≤ x 6 ∧ x 6 ≤ 11 / 10 ∧
    9 / 10 ≤ x 7 ∧ x 7 ≤ 11 / 10}

def hiOrd8UnsafeSet : Set (State 8) :=
  {x | -(11 / 5) ≤ x 0 ∧ x 0 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 1 ∧ x 1 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 2 ∧ x 2 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 3 ∧ x 3 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 4 ∧ x 4 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 5 ∧ x 5 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 6 ∧ x 6 ≤ -(9 / 5) ∧
    -(11 / 5) ≤ x 7 ∧ x 7 ≤ -(9 / 5)}

theorem hiOrd8Barrier_isGradient :
    IsGradient hiOrd8Barrier hiOrd8Gradient := by
  intro x
  have h0 : HasFDerivAt (fun y : State 8 => y 0)
      (ContinuousLinearMap.proj (R := ℝ) 0) x := hasFDerivAt_apply (𝕜 := ℝ) 0 x
  have h1 : HasFDerivAt (fun y : State 8 => y 1)
      (ContinuousLinearMap.proj (R := ℝ) 1) x := hasFDerivAt_apply (𝕜 := ℝ) 1 x
  have h2 : HasFDerivAt (fun y : State 8 => y 2)
      (ContinuousLinearMap.proj (R := ℝ) 2) x := hasFDerivAt_apply (𝕜 := ℝ) 2 x
  have h3 : HasFDerivAt (fun y : State 8 => y 3)
      (ContinuousLinearMap.proj (R := ℝ) 3) x := hasFDerivAt_apply (𝕜 := ℝ) 3 x
  have h4 : HasFDerivAt (fun y : State 8 => y 4)
      (ContinuousLinearMap.proj (R := ℝ) 4) x := hasFDerivAt_apply (𝕜 := ℝ) 4 x
  have h5 : HasFDerivAt (fun y : State 8 => y 5)
      (ContinuousLinearMap.proj (R := ℝ) 5) x := hasFDerivAt_apply (𝕜 := ℝ) 5 x
  have h6 : HasFDerivAt (fun y : State 8 => y 6)
      (ContinuousLinearMap.proj (R := ℝ) 6) x := hasFDerivAt_apply (𝕜 := ℝ) 6 x
  have h7 : HasFDerivAt (fun y : State 8 => y 7)
      (ContinuousLinearMap.proj (R := ℝ) 7) x := hasFDerivAt_apply (𝕜 := ℝ) 7 x
  have h := (((((((h0.const_mul 576).add (h1.const_mul 1824)).add
    (h2.const_mul 2356)).add (h3.const_mul 1624)).add
    (h4.const_mul 649)).add (h5.const_mul 151)).add
    (h6.const_mul 19)).add h7 |>.add_const 12959
  change HasFDerivAt hiOrd8Barrier (gradientCLM (hiOrd8Gradient x)) x
  apply h.congr_fderiv
  ext v
  simp [hiOrd8Gradient, Fin.sum_univ_succ]
  ring

theorem hiOrd8_lie_identity (x : State 8) (w : HiOrd8Uncertainty) :
    ∑ i, hiOrd8Gradient x i * hiOrd8Flow x w i =
      -(576 * x 0 + 1824 * x 1 + 2356 * x 2 + 1624 * x 3 +
        649 * x 4 + 151 * x 5 + 19 * x 6 + x 7) -
        Real.sin (w.1 * x 0) - w.2 := by
  simp [hiOrd8Gradient, hiOrd8Flow, Fin.sum_univ_succ]
  ring

theorem hiOrd8_initial_contained :
    InitialContained hiOrd8Barrier hiOrd8InitialSet := by
  intro x hx
  rcases hx with ⟨h0l, _h0u, h1l, _h1u, h2l, _h2u, h3l, _h3u,
    h4l, _h4u, h5l, _h5u, h6l, _h6u, h7l, _h7u⟩
  unfold hiOrd8Barrier
  linarith

theorem hiOrd8_unsafe_separated :
    UnsafeSeparated hiOrd8Barrier hiOrd8UnsafeSet := by
  intro x hx
  rcases hx with ⟨_h0l, h0u, _h1l, h1u, _h2l, h2u, _h3l, h3u,
    _h4l, h4u, _h5l, h5u, _h6l, h6u, _h7l, h7u⟩
  unfold hiOrd8Barrier
  linarith

theorem hiOrd8_robust_strict :
    RobustStrictLiePositiveOn hiOrd8Domain hiOrd8Barrier hiOrd8Gradient
      hiOrd8Flow hiOrd8UncertaintySet := by
  intro x _hx w hw hzero
  rcases hw with ⟨_homegaLower, _homegaUpper, _hdLower, hdUpper⟩
  rw [hiOrd8_lie_identity]
  have hsin : Real.sin (w.1 * x 0) ≤ 1 := Real.sin_le_one _
  unfold hiOrd8Barrier at hzero
  linarith

theorem hiOrd8_unsafe_separated_on :
    UnsafeSeparatedOn hiOrd8Domain hiOrd8Barrier hiOrd8UnsafeSet := by
  intro x _hx hunsafe
  exact hiOrd8_unsafe_separated x hunsafe

theorem hiOrd8_robust_safety :
    InitialContained hiOrd8Barrier hiOrd8InitialSet ∧
      ConditionalSafetyIn hiOrd8Barrier hiOrd8Domain hiOrd8UnsafeSet
        (RobustClassicalTrajectories hiOrd8Flow hiOrd8UncertaintySet) := by
  refine ⟨hiOrd8_initial_contained, ?_⟩
  exact robust_continuous_strict_boundary_barrier_safety
    hiOrd8Barrier hiOrd8Gradient hiOrd8Flow hiOrd8Domain hiOrd8UnsafeSet
    hiOrd8UncertaintySet hiOrd8Barrier_isGradient hiOrd8_robust_strict
    hiOrd8_unsafe_separated_on

def obstacleUncertaintySet : Set ℝ :=
  {d | -(1 / 2) ≤ d ∧ d ≤ 1 / 2}

noncomputable def obstacleBarrier (x : State 3) : ℝ :=
  x 0 + x 1 + x 2

noncomputable def obstacleGradient (_x : State 3) : State 3 :=
  ![1, 1, 1]

noncomputable def obstacleFlow (x : State 3) (d : ℝ) : State 3 :=
  ![Real.sin (x 2), Real.cos (x 2),
    1 - Real.sin (x 2) - Real.cos (x 2) + d]

def obstacleDomain : Set (State 3) :=
  {x | -10 ≤ x 0 ∧ x 0 ≤ 10 ∧ -10 ≤ x 1 ∧ x 1 ≤ 10 ∧
    -Real.pi ≤ x 2 ∧ x 2 ≤ Real.pi}

def obstacleInitialSet : Set (State 3) :=
  {x | 4 ≤ x 0 ∧ x 0 ≤ 6 ∧ 4 ≤ x 1 ∧ x 1 ≤ 6 ∧
    -(Real.pi / 2) ≤ x 2 ∧ x 2 ≤ Real.pi / 2}

def obstacleUnsafeSet : Set (State 3) :=
  {x | -9 ≤ x 0 ∧ x 0 ≤ -7 ∧ -9 ≤ x 1 ∧ x 1 ≤ -6 ∧
    -(Real.pi / 2) ≤ x 2 ∧ x 2 ≤ Real.pi / 2}

theorem obstacleBarrier_isGradient :
    IsGradient obstacleBarrier obstacleGradient := by
  intro x
  have h0 : HasFDerivAt (fun y : State 3 => y 0)
      (ContinuousLinearMap.proj (R := ℝ) 0) x := hasFDerivAt_apply (𝕜 := ℝ) 0 x
  have h1 : HasFDerivAt (fun y : State 3 => y 1)
      (ContinuousLinearMap.proj (R := ℝ) 1) x := hasFDerivAt_apply (𝕜 := ℝ) 1 x
  have h2 : HasFDerivAt (fun y : State 3 => y 2)
      (ContinuousLinearMap.proj (R := ℝ) 2) x := hasFDerivAt_apply (𝕜 := ℝ) 2 x
  have h := (h0.add h1).add h2
  change HasFDerivAt obstacleBarrier (gradientCLM (obstacleGradient x)) x
  apply h.congr_fderiv
  ext v
  simp [obstacleGradient, Fin.sum_univ_succ]
  ring

theorem obstacle_lie_identity (x : State 3) (d : ℝ) :
    ∑ i, obstacleGradient x i * obstacleFlow x d i = 1 + d := by
  simp [obstacleGradient, obstacleFlow, Fin.sum_univ_succ]
  ring

theorem obstacle_initial_contained :
    InitialContained obstacleBarrier obstacleInitialSet := by
  intro x hx
  rcases hx with ⟨h0l, _h0u, h1l, _h1u, h2l, _h2u⟩
  have hpi : Real.pi < 4 := Real.pi_lt_four
  unfold obstacleBarrier
  linarith

theorem obstacle_unsafe_separated :
    UnsafeSeparated obstacleBarrier obstacleUnsafeSet := by
  intro x hx
  rcases hx with ⟨_h0l, h0u, _h1l, h1u, _h2l, h2u⟩
  have hpi : Real.pi < 4 := Real.pi_lt_four
  unfold obstacleBarrier
  linarith

theorem obstacle_robust_strict :
    RobustStrictLiePositiveOn obstacleDomain obstacleBarrier obstacleGradient
      obstacleFlow obstacleUncertaintySet := by
  intro x _hx d hd _hzero
  rw [obstacle_lie_identity]
  linarith [hd.1]

theorem obstacle_unsafe_separated_on :
    UnsafeSeparatedOn obstacleDomain obstacleBarrier obstacleUnsafeSet := by
  intro x _hx hunsafe
  exact obstacle_unsafe_separated x hunsafe

theorem obstacle_robust_safety :
    InitialContained obstacleBarrier obstacleInitialSet ∧
      ConditionalSafetyIn obstacleBarrier obstacleDomain obstacleUnsafeSet
        (RobustClassicalTrajectories obstacleFlow obstacleUncertaintySet) := by
  refine ⟨obstacle_initial_contained, ?_⟩
  exact robust_continuous_strict_boundary_barrier_safety
    obstacleBarrier obstacleGradient obstacleFlow obstacleDomain obstacleUnsafeSet
    obstacleUncertaintySet obstacleBarrier_isGradient obstacle_robust_strict
    obstacle_unsafe_separated_on

abbrev PeriodicUncertainty := ℝ × ℝ

def periodicUncertaintySet : Set PeriodicUncertainty :=
  {w | w.1 ^ 2 + w.2 ^ 2 ≤ 1}

noncomputable def periodicDiskBarrier (x : State 2) : ℝ :=
  1 / 4 - (x 0 ^ 2 + x 1 ^ 2)

noncomputable def periodicDiskGradient (x : State 2) : State 2 :=
  ![-2 * x 0, -2 * x 1]

noncomputable def periodicFlow (x : State 2) (w : PeriodicUncertainty) : State 2 :=
  ![-x 0 + x 1 + (x 0 ^ 2 + x 1 ^ 2) * w.1,
    -x 0 - x 1 + (x 0 ^ 2 + x 1 ^ 2) * w.2]

def periodicDiskInitialSet : Set (State 2) :=
  {x | x 0 ^ 2 + x 1 ^ 2 ≤ 1 / 4}

def periodicDiskUnsafeSet : Set (State 2) :=
  {x | 1 / 4 < x 0 ^ 2 + x 1 ^ 2}

theorem periodicDiskBarrier_isGradient :
    IsGradient periodicDiskBarrier periodicDiskGradient := by
  intro x
  have h0 : HasFDerivAt (fun y : State 2 => y 0)
      (ContinuousLinearMap.proj (R := ℝ) 0) x := hasFDerivAt_apply (𝕜 := ℝ) 0 x
  have h1 : HasFDerivAt (fun y : State 2 => y 1)
      (ContinuousLinearMap.proj (R := ℝ) 1) x := hasFDerivAt_apply (𝕜 := ℝ) 1 x
  have h := ((h0.pow 2).add (h1.pow 2)).const_sub (1 / 4)
  change HasFDerivAt periodicDiskBarrier (gradientCLM (periodicDiskGradient x)) x
  apply h.congr_fderiv
  ext v
  simp [periodicDiskGradient, Fin.sum_univ_succ]
  ring

theorem periodicDisk_lie_identity (x : State 2) (w : PeriodicUncertainty) :
    ∑ i, periodicDiskGradient x i * periodicFlow x w i =
      2 * (x 0 ^ 2 + x 1 ^ 2) *
        (1 - (x 0 * w.1 + x 1 * w.2)) := by
  simp [periodicDiskGradient, periodicFlow, Fin.sum_univ_succ]
  ring

theorem periodicDisk_initial_contained :
    InitialContained periodicDiskBarrier periodicDiskInitialSet := by
  intro x hx
  change x 0 ^ 2 + x 1 ^ 2 ≤ 1 / 4 at hx
  unfold periodicDiskBarrier
  linarith

theorem periodicDisk_unsafe_separated :
    UnsafeSeparated periodicDiskBarrier periodicDiskUnsafeSet := by
  intro x hx
  change 1 / 4 < x 0 ^ 2 + x 1 ^ 2 at hx
  unfold periodicDiskBarrier
  linarith

theorem periodicDisk_robust_strict :
    RobustStrictLiePositiveOn Set.univ periodicDiskBarrier periodicDiskGradient
      periodicFlow periodicUncertaintySet := by
  intro x _hx w hw hzero
  change w.1 ^ 2 + w.2 ^ 2 ≤ 1 at hw
  have hcauchy : (x 0 * w.1 + x 1 * w.2) ^ 2 ≤
      (x 0 ^ 2 + x 1 ^ 2) * (w.1 ^ 2 + w.2 ^ 2) := by
    nlinarith [sq_nonneg (x 0 * w.2 - x 1 * w.1)]
  have hradius : x 0 ^ 2 + x 1 ^ 2 = 1 / 4 := by
    unfold periodicDiskBarrier at hzero
    linarith
  have hproduct :
      (x 0 ^ 2 + x 1 ^ 2) * (w.1 ^ 2 + w.2 ^ 2) ≤ 1 / 4 := by
    rw [hradius]
    nlinarith
  have hdot : x 0 * w.1 + x 1 * w.2 ≤ 1 / 2 := by
    nlinarith [hcauchy.trans hproduct]
  rw [periodicDisk_lie_identity]
  rw [hradius]
  nlinarith

theorem periodicDisk_unsafe_separated_on :
    UnsafeSeparatedOn Set.univ periodicDiskBarrier periodicDiskUnsafeSet := by
  intro x _hx hunsafe
  exact periodicDisk_unsafe_separated x hunsafe

theorem periodicDisk_robust_safety :
    InitialContained periodicDiskBarrier periodicDiskInitialSet ∧
      ConditionalSafetyIn periodicDiskBarrier Set.univ periodicDiskUnsafeSet
        (RobustClassicalTrajectories periodicFlow periodicUncertaintySet) := by
  refine ⟨periodicDisk_initial_contained, ?_⟩
  exact robust_continuous_strict_boundary_barrier_safety
    periodicDiskBarrier periodicDiskGradient periodicFlow Set.univ
    periodicDiskUnsafeSet periodicUncertaintySet periodicDiskBarrier_isGradient
    periodicDisk_robust_strict periodicDisk_unsafe_separated_on

end LeanBarrier.RobustContinuous.Examples
