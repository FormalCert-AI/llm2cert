-- Prove soundness of continuous-time barrier conditions.
import Mathlib.Analysis.Calculus.LocalExtr.Basic
import Mathlib.Topology.Order.IntermediateValue
import LeanBarrier.Basic

namespace LeanBarrier

def ClassicalTrajectory {n : ℕ} (flow : State n → State n)
    (γ : ℝ → State n) : Prop :=
  ∀ t, HasDerivAt γ (flow (γ t)) t

def ClassicalTrajectories {n : ℕ} (flow : State n → State n) :
    Set (ℝ → State n) :=
  {γ | ClassicalTrajectory flow γ}

def ForwardInvariantAlong {n : ℕ} (trajectories : Set (ℝ → State n))
    (set : Set (State n)) : Prop :=
  ∀ γ ∈ trajectories, γ 0 ∈ set → ∀ t, 0 ≤ t → γ t ∈ set

noncomputable def gradientCLM {n : ℕ} (g : State n) : State n →L[ℝ] ℝ :=
  ∑ i, (g i) • ContinuousLinearMap.proj i

@[simp]
theorem gradientCLM_apply {n : ℕ} (g v : State n) :
    gradientCLM g v = ∑ i, g i * v i := by
  simp [gradientCLM]

def IsGradient {n : ℕ} (B : State n → ℝ)
    (gradient : State n → State n) : Prop :=
  ∀ x, HasFDerivAt B (gradientCLM (gradient x)) x

def StrictLiePositiveOn {n : ℕ} (X : Set (State n)) (B : State n → ℝ)
    (gradient flow : State n → State n) : Prop :=
  ∀ x ∈ X, B x = 0 → 0 < ∑ i, gradient x i * flow x i

def UnsafeSeparatedOn {n : ℕ} (X : Set (State n)) (B : State n → ℝ)
    (unsafeSet : Set (State n)) : Prop :=
  ∀ x ∈ X, x ∈ unsafeSet → B x < 0

def ConditionalSafetyIn {n : ℕ} (B : State n → ℝ) (X unsafeSet : Set (State n))
    (trajectories : Set (ℝ → State n)) : Prop :=
  ∀ γ ∈ trajectories, γ 0 ∈ Superlevel B → ∀ T, 0 ≤ T →
    (∀ t ∈ Set.Icc 0 T, γ t ∈ X) → γ T ∉ unsafeSet

theorem strict_boundary_scalar_preserves_nonnegative
    {g g' : ℝ → ℝ} {T : ℝ}
    (hT : 0 ≤ T)
    (hd : ∀ t, HasDerivAt g (g' t) t)
    (hstrict : ∀ t ∈ Set.Ico 0 T, g t = 0 → 0 < g' t)
    (h0 : 0 ≤ g 0) :
    0 ≤ g T := by
  by_contra hfinal
  have hgT : g T < 0 := lt_of_not_ge hfinal
  have hgcont : Continuous g := by
    rw [continuous_iff_continuousAt]
    exact fun t => (hd t).continuousAt
  let Z : Set ℝ := Set.Icc 0 T ∩ g ⁻¹' {0}
  have hZcompact : IsCompact Z := by
    exact isCompact_Icc.inter_right (isClosed_singleton.preimage hgcont)
  have hZne : Z.Nonempty := by
    have hzero : (0 : ℝ) ∈ Set.Icc (g T) (g 0) := ⟨hgT.le, h0⟩
    obtain ⟨c, hc, hgc⟩ :=
      (Set.mem_image g (Set.Icc 0 T) 0).mp
        (intermediate_value_Icc' hT hgcont.continuousOn hzero)
    exact ⟨c, hc, by simp [hgc]⟩
  obtain ⟨c, hcZ, hcmax⟩ := hZcompact.exists_isGreatest hZne
  have hcIcc : c ∈ Set.Icc 0 T := hcZ.1
  have hgc : g c = 0 := by simpa using hcZ.2
  have hcT : c < T := by
    exact lt_of_le_of_ne hcIcc.2 (fun h => by subst T; linarith)
  have hmax : IsMaxOn g (Set.Icc c T) c := by
    intro y hy
    rw [hgc]
    by_cases hyc : y = c
    · subst y
      exact hgc.le
    have hcy : c < y := lt_of_le_of_ne hy.1 (Ne.symm hyc)
    by_cases hgy0 : 0 ≤ g y
    swap
    · exact (lt_of_not_ge hgy0).le
    have hyT : y < T := by
      exact lt_of_le_of_ne hy.2 (fun h => by subst y; linarith)
    have hzero : (0 : ℝ) ∈ Set.Icc (g T) (g y) := ⟨hgT.le, hgy0⟩
    obtain ⟨z, hz, hgz⟩ :=
      (Set.mem_image g (Set.Icc y T) 0).mp
        (intermediate_value_Icc' hyT.le hgcont.continuousOn hzero)
    have hzZ : z ∈ Z := by
      refine ⟨⟨hcIcc.1.trans (hcy.le.trans hz.1), hz.2⟩, ?_⟩
      simpa using hgz
    have hzc := hcmax hzZ
    have hyz : y ≤ z := hz.1
    exact ((not_lt_of_ge (hyz.trans hzc)) hcy).elim
  have hpositive := hstrict c ⟨hcIcc.1, hcT⟩ hgc
  have htan : T - c ∈ posTangentConeAt (Set.Icc c T) c := by
    apply sub_mem_posTangentConeAt_of_segment_subset
    simp [segment_eq_Icc hcT.le]
  have hnonpos := hmax.localize.hasFDerivWithinAt_nonpos
    (hd c).hasFDerivAt.hasFDerivWithinAt htan
  have hnonpos' : g' c * (T - c) ≤ 0 := by
    simpa [smul_eq_mul, mul_comm] using hnonpos
  nlinarith

theorem continuous_strict_boundary_barrier_safety {n : ℕ}
    (B : State n → ℝ) (gradient flow : State n → State n)
    (X unsafeSet : Set (State n))
    (hgradient : IsGradient B gradient)
    (hstrict : StrictLiePositiveOn X B gradient flow)
    (hunsafe : UnsafeSeparatedOn X B unsafeSet) :
    ConditionalSafetyIn B X unsafeSet (ClassicalTrajectories flow) := by
  intro γ hγ hinit T hT hstay hreach
  have hd : ∀ t, HasDerivAt (fun s => B (γ s))
      (∑ i, gradient (γ t) i * flow (γ t) i) t := by
    intro t
    simpa [Function.comp_def, gradientCLM_apply] using
      (hgradient (γ t)).comp_hasDerivAt t (hγ t)
  have hsafe := strict_boundary_scalar_preserves_nonnegative
    (g := fun t => B (γ t))
    (g' := fun t => ∑ i, gradient (γ t) i * flow (γ t) i)
    hT hd
      (fun t ht hzero => hstrict (γ t) (hstay t ⟨ht.1, ht.2.le⟩) hzero)
      hinit
  exact (not_lt_of_ge hsafe) (hunsafe (γ T) (hstay T ⟨hT, le_rfl⟩) hreach)

theorem continuous_barrier_implies_safety {n : ℕ} (B : State n → ℝ)
    (unsafeSet : Set (State n)) (trajectories : Set (ℝ → State n))
    (hinvariant : ForwardInvariantAlong trajectories (Superlevel B))
    (hunsafe : UnsafeSeparated B unsafeSet) :
    ForwardInvariantAlong trajectories (Superlevel B) ∧
      Disjoint (Superlevel B) unsafeSet := by
  exact ⟨hinvariant, superlevel_avoids_unsafe B unsafeSet hunsafe⟩

end LeanBarrier
