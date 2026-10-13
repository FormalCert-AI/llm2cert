-- Prove stability and attraction from Lyapunov conditions.
import Mathlib
import LeanBarrier.Basic

namespace LeanBarrier.Lyapunov

open Set Function

def ValueAlong {α : Type*} (V : α → ℝ) (γ : ℝ → α) : ℝ → ℝ :=
  fun t => V (γ t)

def DerivativeAlong {α : Type*} (V : α → ℝ) (γ : ℝ → α)
    (lie : α → ℝ) (D : Set ℝ) : Prop :=
  ∀ t ∈ D, HasDerivAt (ValueAlong V γ) (lie (γ t)) t

theorem valueAlong_continuousOn {α : Type*}
    [NormedAddCommGroup α] [NormedSpace ℝ α]
    {V : α → ℝ} {γ : ℝ → α}
    {D : Set ℝ} (hV : ContDiff ℝ 1 V) (hγ : ContinuousOn γ D) :
    ContinuousOn (ValueAlong V γ) D := by
  exact hV.continuous.continuousOn.comp hγ (fun _ _ => Set.mem_univ _)

theorem valueAlong_differentiableOn {α : Type*} {V : α → ℝ} {γ : ℝ → α}
    {lie : α → ℝ} {D : Set ℝ}
    (hderiv : DerivativeAlong V γ lie D) :
    DifferentiableOn ℝ (ValueAlong V γ) D := by
  intro t ht
  exact (hderiv t ht).differentiableAt.differentiableWithinAt

theorem valueAlong_antitoneOn_Icc {α : Type*}
    [NormedAddCommGroup α] [NormedSpace ℝ α]
    {V : α → ℝ} {γ : ℝ → α}
    {lie : α → ℝ} {T : ℝ}
    (hV : ContDiff ℝ 1 V)
    (hγ : ContinuousOn γ (Icc 0 T))
    (hderiv : DerivativeAlong V γ lie (interior (Icc 0 T)))
    (hlie : ∀ t ∈ interior (Icc 0 T), lie (γ t) ≤ 0) :
    AntitoneOn (ValueAlong V γ) (Icc 0 T) := by
  apply antitoneOn_of_deriv_nonpos (convex_Icc 0 T)
  · exact valueAlong_continuousOn hV hγ
  · exact valueAlong_differentiableOn hderiv
  · intro t ht
    rw [(hderiv t ht).deriv]
    exact hlie t ht

theorem valueAlong_nonincreasing {α : Type*}
    [NormedAddCommGroup α] [NormedSpace ℝ α]
    {V : α → ℝ} {γ : ℝ → α}
    {lie : α → ℝ} {T : ℝ}
    (hT : 0 ≤ T)
    (hV : ContDiff ℝ 1 V)
    (hγ : ContinuousOn γ (Icc 0 T))
    (hderiv : DerivativeAlong V γ lie (interior (Icc 0 T)))
    (hlie : ∀ t ∈ interior (Icc 0 T), lie (γ t) ≤ 0) :
    V (γ T) ≤ V (γ 0) := by
  have hant := valueAlong_antitoneOn_Icc hV hγ hderiv hlie
  have h0 : (0 : ℝ) ∈ Icc 0 T := ⟨le_rfl, hT⟩
  have hTmem : T ∈ Icc 0 T := ⟨hT, le_rfl⟩
  exact hant h0 hTmem hT

theorem sublevel_preserved_on_Icc {α : Type*}
    [NormedAddCommGroup α] [NormedSpace ℝ α]
    {V : α → ℝ} {γ : ℝ → α}
    {lie : α → ℝ} {T c : ℝ}
    (hT : 0 ≤ T)
    (hV : ContDiff ℝ 1 V)
    (hγ : ContinuousOn γ (Icc 0 T))
    (hderiv : DerivativeAlong V γ lie (interior (Icc 0 T)))
    (hlie : ∀ t ∈ interior (Icc 0 T), lie (γ t) ≤ 0)
    (hinit : V (γ 0) ≤ c) :
    V (γ T) ≤ c := by
  exact (valueAlong_nonincreasing hT hV hγ hderiv hlie).trans hinit

theorem superlevel_preserved_on_Icc {α : Type*}
    [NormedAddCommGroup α] [NormedSpace ℝ α]
    {V : α → ℝ} {γ : ℝ → α}
    {lie : α → ℝ} {T c : ℝ}
    (hT : 0 ≤ T)
    (hV : ContDiff ℝ 1 V)
    (hγ : ContinuousOn γ (Icc 0 T))
    (hderiv : DerivativeAlong V γ lie (interior (Icc 0 T)))
    (hlie : ∀ t ∈ interior (Icc 0 T), lie (γ t) ≤ 0)
    (hinit : V (γ 0) ≤ c) :
    V (γ T) ≤ c :=
  sublevel_preserved_on_Icc hT hV hγ hderiv hlie hinit

def RadiallyUnbounded {n : ℕ} (V : LeanBarrier.State n → ℝ) : Prop :=
  ∀ K : ℝ, ∃ R : ℝ, ∀ x : LeanBarrier.State n,
    R ≤ (∑ i : Fin n, (x i) ^ 2) → K ≤ V x

def DiscreteDecrease {α : Type*} (V : α → ℝ) (F : α → α) : Prop :=
  ∀ x, V (F x) ≤ V x

theorem iterate_nonincreasing {α : Type*} {V : α → ℝ} {F : α → α}
    (h : DiscreteDecrease V F) (x : α) :
    ∀ n : ℕ, V (F^[n] x) ≤ V x := by
  intro n
  induction n with
  | zero => simp
  | succ n ih =>
    calc
      V (F^[n + 1] x) = V (F (F^[n] x)) := by rw [iterate_succ_apply']
      _ ≤ V (F^[n] x) := h _
      _ ≤ V x := ih

theorem iterate_geometric_decay {α : Type*} {V : α → ℝ} {F : α → α} {ρ : ℝ}
    (hρ : 0 ≤ ρ) (h : ∀ x, V (F x) ≤ ρ * V x) (x : α) :
    ∀ n : ℕ, V (F^[n] x) ≤ ρ ^ n * V x := by
  intro n
  induction n with
  | zero => simp
  | succ n ih =>
    calc
      V (F^[n + 1] x) = V (F (F^[n] x)) := by rw [iterate_succ_apply']
      _ ≤ ρ * V (F^[n] x) := h _
      _ ≤ ρ * (ρ ^ n * V x) := mul_le_mul_of_nonneg_left ih hρ
      _ = ρ ^ (n + 1) * V x := by rw [← mul_assoc, ← pow_succ']

end LeanBarrier.Lyapunov
