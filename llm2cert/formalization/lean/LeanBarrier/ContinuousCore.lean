-- Prove continuous invariance and safety from Lie conditions.
import Mathlib.Analysis.ODE.Basic
import Mathlib.Analysis.Calculus.Deriv.MeanValue
import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import LeanBarrier.Continuous
import LeanBarrier.Lyapunov

namespace LeanBarrier.ContinuousCore

open Set

def IntegralCurve {n : ℕ} (flow : State n → State n)
    (γ : ℝ → State n) : Prop :=
  IsIntegralCurve γ (fun _ x => flow x)

def LieAlong {n : ℕ} (B : State n → ℝ)
    (γ : ℝ → State n) (lie : State n → ℝ) (D : Set ℝ) : Prop :=
  ∀ t ∈ D, HasDerivAt (fun s => B (γ s)) (lie (γ t)) t

theorem integralCurve_continuous {n : ℕ} {flow : State n → State n}
    {γ : ℝ → State n} (hγ : IntegralCurve flow γ) : Continuous γ := by
  exact hγ.continuous

theorem global_lie_nonnegative_preserves_superlevel
    {n : ℕ} {B : State n → ℝ} {flow : State n → State n} {γ : ℝ → State n}
    {lie : State n → ℝ} {T : ℝ}
    (hT : 0 ≤ T)
    (hγ : IntegralCurve flow γ)
    (hB : ContDiff ℝ 1 B)
    (hlie : LieAlong B γ lie (interior (Icc 0 T)))
    (hnonneg : ∀ t ∈ interior (Icc 0 T), 0 ≤ lie (γ t))
    (hinit : 0 ≤ B (γ 0)) :
    0 ≤ B (γ T) := by
  have hneg : ∀ t ∈ interior (Icc 0 T), -lie (γ t) ≤ 0 := by
    intro t ht
    linarith [hnonneg t ht]
  have hmono := LeanBarrier.Lyapunov.valueAlong_nonincreasing
    (V := fun x : State n => -B x) (γ := γ) (lie := fun x => -lie x)
    hT hB.neg hγ.continuous.continuousOn
    (by
      intro t ht
      convert (hlie t ht).neg using 1 <;> rfl)
    hneg
  linarith

theorem global_lie_nonnegative_barrier_safety
    {n : ℕ} {B : State n → ℝ} {flow : State n → State n} {γ : ℝ → State n}
    {lie : State n → ℝ} {unsafeSet : Set (State n)} {T : ℝ}
    (hT : 0 ≤ T)
    (hγ : IntegralCurve flow γ)
    (hB : ContDiff ℝ 1 B)
    (hlie : LieAlong B γ lie (interior (Icc 0 T)))
    (hnonneg : ∀ t ∈ interior (Icc 0 T), 0 ≤ lie (γ t))
    (hinit : 0 ≤ B (γ 0))
    (hunsafe : ∀ x ∈ unsafeSet, B x < 0)
    (hreach : γ T ∈ unsafeSet) :
    False := by
  have hsafe := global_lie_nonnegative_preserves_superlevel
    hT hγ hB hlie hnonneg hinit
  exact (not_lt_of_ge hsafe) (hunsafe (γ T) hreach)

def LinearClassKLieBound {n : ℕ} (B : State n → ℝ)
    (gradient flow : State n → State n) (L : ℝ) : Prop :=
  ∀ x, -L * B x ≤ ∑ i, gradient x i * flow x i

theorem linear_classK_scalar_preserves_nonnegative
    {g g' : ℝ → ℝ} {L : ℝ}
    (hd : ∀ t, HasDerivAt g (g' t) t)
    (hbound : ∀ t, -L * g t ≤ g' t)
    (h0 : 0 ≤ g 0) :
    ∀ T, 0 ≤ T → 0 ≤ g T := by
  intro T hT
  let z : ℝ → ℝ := fun t => g t * Real.exp (L * t)
  have hzd : ∀ t, HasDerivAt z
      ((g' t + L * g t) * Real.exp (L * t)) t := by
    intro t
    have he : HasDerivAt (fun s => Real.exp (L * s))
        (Real.exp (L * t) * L) t := by
      simpa using (((hasDerivAt_id t).const_mul L)).exp
    change HasDerivAt (fun s => g s * Real.exp (L * s))
      ((g' t + L * g t) * Real.exp (L * t)) t
    rw [show (g' t + L * g t) * Real.exp (L * t) =
      g' t * Real.exp (L * t) + g t * (Real.exp (L * t) * L) by ring]
    exact (hd t).mul he
  have hzcont : Continuous z := by
    have hgcont : Continuous g := by
      rw [continuous_iff_continuousAt]
      exact fun t => (hd t).continuousAt
    exact hgcont.mul
      (Real.continuous_exp.comp (continuous_const.mul continuous_id))
  have hmono : MonotoneOn z (Icc 0 T) := by
    refine monotoneOn_of_deriv_nonneg (convex_Icc 0 T) hzcont.continuousOn
      (fun t _ => (hzd t).differentiableAt.differentiableWithinAt) (fun t _ => ?_)
    rw [(hzd t).deriv]
    exact mul_nonneg (by linarith [hbound t]) (Real.exp_pos _).le
  have hz0T : z 0 ≤ z T :=
    hmono ⟨le_rfl, hT⟩ ⟨hT, le_rfl⟩ hT
  have hproduct : 0 ≤ g T * Real.exp (L * T) := by
    dsimp [z] at hz0T
    simp only [mul_zero, Real.exp_zero, mul_one] at hz0T
    exact h0.trans hz0T
  nlinarith [Real.exp_pos (L * T)]

theorem continuous_linear_classK_nagumo {n : ℕ}
    (B : State n → ℝ) (gradient flow : State n → State n) (L : ℝ)
    (hgradient : IsGradient B gradient)
    (hbound : LinearClassKLieBound B gradient flow L) :
    ForwardInvariantAlong (ClassicalTrajectories flow) (Superlevel B) := by
  intro γ hγ h0 T hT
  apply linear_classK_scalar_preserves_nonnegative
      (g := fun t => B (γ t))
      (g' := fun t => ∑ i, gradient (γ t) i * flow (γ t) i)
      (L := L) _ _ h0 T hT
  · intro t
    simpa [Function.comp_def, gradientCLM_apply] using
      (hgradient (γ t)).comp_hasDerivAt t (hγ t)
  · intro t
    exact hbound (γ t)

theorem continuous_global_lie_nagumo {n : ℕ}
    (B : State n → ℝ) (gradient flow : State n → State n)
    (hgradient : IsGradient B gradient)
    (hlie : ∀ x, 0 ≤ ∑ i, gradient x i * flow x i) :
    ForwardInvariantAlong (ClassicalTrajectories flow) (Superlevel B) := by
  apply continuous_linear_classK_nagumo B gradient flow 0 hgradient
  intro x
  simpa using hlie x

end LeanBarrier.ContinuousCore
