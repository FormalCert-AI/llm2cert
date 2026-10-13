-- Close task conclusions from verified Lyapunov obligations.
import LeanBarrier.Lyapunov
import LeanBarrier.Continuous

namespace LeanBarrier.Lyapunov

open Set Filter Function

def ContinuousROAOn {n : ℕ} (initial region : Set (State n))
    (trajectories : Set (ℝ → State n)) : Prop :=
  ∀ γ ∈ trajectories, γ 0 ∈ initial →
    (∀ t, 0 ≤ t → γ t ∈ region) ∧ Tendsto γ atTop (nhds 0)

def DiscreteROAOn {n : ℕ} (step : State n → State n)
    (initial region : Set (State n)) : Prop :=
  ∀ x ∈ initial,
    (∀ k, (step^[k]) x ∈ region) ∧
      Tendsto (fun k => (step^[k]) x) atTop (nhds 0)

def sqNorm {n : ℕ} (x : State n) : ℝ := ∑ i, x i ^ 2

theorem coordinate_sq_le_sqNorm {n : ℕ} (x : State n) (i : Fin n) :
    x i ^ 2 ≤ sqNorm x := by
  exact Finset.single_le_sum (fun j _ => sq_nonneg (x j)) (Finset.mem_univ i)

theorem norm_le_abs_add_one_of_sqNorm_lt {n : ℕ} {x : State n} {R : ℝ}
    (hx : sqNorm x < R) :
    ‖x‖ ≤ |R| + 1 := by
  rw [pi_norm_le_iff_of_nonneg (by positivity)]
  intro i
  rw [Real.norm_eq_abs]
  by_contra hnot
  have hC : |R| + 1 < |x i| := lt_of_not_ge hnot
  have hCsq : (|R| + 1) ^ 2 < |x i| ^ 2 :=
    (sq_lt_sq₀ (by positivity) (abs_nonneg _)).2 hC
  rw [sq_abs] at hCsq
  have hRsq : R < (|R| + 1) ^ 2 := by
    have hRabs : R ≤ |R| := le_abs_self R
    nlinarith [sq_nonneg |R|]
  have hxi := (coordinate_sq_le_sqNorm x i).trans_lt hx
  linarith

theorem radiallyUnbounded_compact_sublevel
    {n : ℕ} {V : State n → ℝ}
    (hV : Continuous V) (hradial : RadiallyUnbounded V) (c : ℝ) :
    IsCompact {x | V x ≤ c} := by
  obtain ⟨R, hR⟩ := hradial (c + 1)
  have hclosed : IsClosed {x | V x ≤ c} :=
    isClosed_le hV continuous_const
  apply Metric.isCompact_of_isClosed_isBounded hclosed
  rw [Metric.isBounded_iff_subset_closedBall 0]
  refine ⟨|R| + 1, ?_⟩
  intro x hx
  change V x ≤ c at hx
  have hsquare : sqNorm x < R := by
    by_contra hnot
    have hlarge := hR x (le_of_not_gt hnot)
    linarith
  simpa [Metric.mem_closedBall, dist_zero_right] using
    norm_le_abs_add_one_of_sqNorm_lt hsquare

theorem compact_sublevel_of_continuous_bounded_superset
    {n : ℕ} {V : State n → ℝ} {c : ℝ} {N : Set (State n)}
    (hV : Continuous V) (hN : Bornology.IsBounded N)
    (hsubset : {x | V x ≤ c} ⊆ N) :
    IsCompact {x | V x ≤ c} := by
  apply Metric.isCompact_of_isClosed_isBounded
  · exact isClosed_le hV continuous_const
  · exact hN.subset hsubset

def ContinuousStableIn {n : ℕ} (domain : Set (State n))
    (trajectories : Set (ℝ → State n)) : Prop :=
  ∀ ε > 0, ∃ δ > 0, ∀ γ ∈ trajectories,
    dist (γ 0) 0 < δ → ∀ T, 0 ≤ T →
      (∀ t ∈ Icc 0 T, γ t ∈ domain) → dist (γ T) 0 < ε

def ContinuousAttractiveIn {n : ℕ} (domain : Set (State n))
    (trajectories : Set (ℝ → State n)) : Prop :=
  ∀ γ ∈ trajectories, (∀ t, 0 ≤ t → γ t ∈ domain) →
    Tendsto γ atTop (nhds 0)

def DiscreteStableIn {n : ℕ} (step : State n → State n)
    (domain : Set (State n)) : Prop :=
  ∀ ε > 0, ∃ δ > 0, ∀ x,
    dist x 0 < δ → ∀ k,
      (∀ j ≤ k, (step^[j]) x ∈ domain) → dist ((step^[k]) x) 0 < ε

def DiscreteAttractiveIn {n : ℕ} (step : State n → State n)
    (domain : Set (State n)) : Prop :=
  ∀ x, (∀ k, (step^[k]) x ∈ domain) →
    Tendsto (fun k => (step^[k]) x) atTop (nhds 0)

def ContinuousGloballyAsymptoticallyStable {n : ℕ}
    (flow : State n → State n) : Prop :=
  ContinuousStableIn Set.univ (LeanBarrier.ClassicalTrajectories flow) ∧
    ContinuousAttractiveIn Set.univ (LeanBarrier.ClassicalTrajectories flow)

def DiscreteGloballyAsymptoticallyStable {n : ℕ}
    (step : State n → State n) : Prop :=
  DiscreteStableIn step Set.univ ∧ DiscreteAttractiveIn step Set.univ

def ContinuousExponentiallyStableIn {n : ℕ}
    (flow : State n → State n) (domain : Set (State n)) : Prop :=
  ∃ K rate : ℝ, 0 < K ∧ 0 < rate ∧
    ∀ gamma ∈ LeanBarrier.ClassicalTrajectories flow,
      ∀ T, 0 ≤ T → (∀ t ∈ Icc 0 T, gamma t ∈ domain) →
        sqNorm (gamma T) ≤ K * Real.exp (-rate * T) * sqNorm (gamma 0)

def DiscreteExponentiallyStableIn {n : ℕ}
    (step : State n → State n) (domain : Set (State n)) : Prop :=
  ∃ K rho : ℝ, 0 < K ∧ 0 ≤ rho ∧ rho < 1 ∧
    ∀ x, (∀ k, (step^[k]) x ∈ domain) → ∀ k,
      sqNorm ((step^[k]) x) ≤ K * rho ^ k * sqNorm x

theorem uniform_negative_on_compact
    {E : Type*} [TopologicalSpace E]
    {K : Set E} (hK : IsCompact K) {V lie : E → ℝ}
    (hV : Continuous V) (hlie : Continuous lie)
    (hstrict : ∀ x ∈ K, 0 < V x → lie x < 0) :
    ∀ a, 0 < a → ∃ η, 0 < η ∧
      ∀ x ∈ K, a ≤ V x → lie x ≤ -η := by
  intro a ha
  let S : Set E := K ∩ {x | a ≤ V x}
  have hScompact : IsCompact S := by
    apply hK.inter_right
    exact isClosed_le continuous_const hV
  by_cases hSne : S.Nonempty
  · obtain ⟨z, hzS, hzmax⟩ :=
      hScompact.exists_isMaxOn hSne hlie.continuousOn
    have hzstrict : lie z < 0 :=
      hstrict z hzS.1 (ha.trans_le hzS.2)
    refine ⟨-lie z, neg_pos.mpr hzstrict, ?_⟩
    intro x hxK hax
    have hxS : x ∈ S := ⟨hxK, hax⟩
    simpa using hzmax hxS
  · refine ⟨1, by norm_num, ?_⟩
    intro x hxK hax
    exact (hSne ⟨x, hxK, hax⟩).elim

theorem strict_upper_boundary_scalar_preserves
    {g g' : ℝ → ℝ} {T c : ℝ}
    (hT : 0 ≤ T)
    (hd : ∀ t, HasDerivAt g (g' t) t)
    (hstrict : ∀ t ∈ Ico 0 T, g t = c → g' t < 0)
    (h0 : g 0 ≤ c) :
    g T ≤ c := by
  by_contra hfinal
  have hgT : c < g T := lt_of_not_ge hfinal
  have hgcont : Continuous g := by
    rw [continuous_iff_continuousAt]
    exact fun t => (hd t).continuousAt
  let Z : Set ℝ := Icc 0 T ∩ g ⁻¹' {c}
  have hZcompact : IsCompact Z := by
    exact isCompact_Icc.inter_right (isClosed_singleton.preimage hgcont)
  have hZne : Z.Nonempty := by
    have hcbetween : c ∈ Icc (g 0) (g T) := ⟨h0, hgT.le⟩
    obtain ⟨z, hz, hgz⟩ :=
      (Set.mem_image g (Icc 0 T) c).mp
        (intermediate_value_Icc hT hgcont.continuousOn hcbetween)
    exact ⟨z, hz, by simp [hgz]⟩
  obtain ⟨z, hzZ, hzmax⟩ := hZcompact.exists_isGreatest hZne
  have hzIcc : z ∈ Icc 0 T := hzZ.1
  have hgz : g z = c := by simpa using hzZ.2
  have hzT : z < T := by
    exact lt_of_le_of_ne hzIcc.2 (fun h => by subst T; linarith)
  have hmin : IsMinOn g (Icc z T) z := by
    intro y hy
    rw [hgz]
    by_cases hzy : y = z
    · subst y
      simpa [hgz]
    have hzylt : z < y := lt_of_le_of_ne hy.1 (Ne.symm hzy)
    by_cases hcy : c ≤ g y
    · exact hcy
    have hyT : y < T := by
      exact lt_of_le_of_ne hy.2 (fun h => by subst y; linarith)
    have hcbetween : c ∈ Icc (g y) (g T) := ⟨(le_of_not_ge hcy), hgT.le⟩
    obtain ⟨w, hw, hgw⟩ :=
      (Set.mem_image g (Icc y T) c).mp
        (intermediate_value_Icc hyT.le hgcont.continuousOn hcbetween)
    have hwZ : w ∈ Z := by
      refine ⟨⟨hzIcc.1.trans (hzylt.le.trans hw.1), hw.2⟩, ?_⟩
      simpa using hgw
    have hwz := hzmax hwZ
    exact ((not_lt_of_ge (hw.1.trans hwz)) hzylt).elim
  have hnegative := hstrict z ⟨hzIcc.1, hzT⟩ hgz
  have htan : T - z ∈ posTangentConeAt (Icc z T) z := by
    apply sub_mem_posTangentConeAt_of_segment_subset
    simp [segment_eq_Icc hzT.le]
  have hnonneg := hmin.localize.hasFDerivWithinAt_nonneg
    (hd z).hasFDerivAt.hasFDerivWithinAt htan
  have hnonneg' : 0 ≤ g' z * (T - z) := by
    simpa [smul_eq_mul, mul_comm] using hnonneg
  nlinarith

theorem continuous_value_tendsto_zero_of_uniform_decay
    {g g' : ℝ → ℝ}
    (hd : ∀ t, HasDerivAt g (g' t) t)
    (hnonneg : ∀ t, 0 ≤ t → 0 ≤ g t)
    (hnonpos : ∀ t, 0 ≤ t → g' t ≤ 0)
    (huniform : ∀ a, 0 < a → ∃ η, 0 < η ∧
      ∀ t, 0 ≤ t → a ≤ g t → g' t ≤ -η) :
    Tendsto g atTop (nhds 0) := by
  have hanti : ∀ {s t : ℝ}, 0 ≤ s → s ≤ t → g t ≤ g s := by
    intro s t hs hst
    have hant : AntitoneOn g (Icc s t) := by
      apply antitoneOn_of_deriv_nonpos (convex_Icc s t)
      · have hgcont : Continuous g := by
          rw [continuous_iff_continuousAt]
          exact fun x => (hd x).continuousAt
        exact hgcont.continuousOn
      · intro x hx
        exact (hd x).differentiableAt.differentiableWithinAt
      · intro x hx
        rw [(hd x).deriv]
        have hxin : x ∈ Icc s t := interior_subset hx
        exact hnonpos x (hs.trans hxin.1)
    exact hant ⟨le_rfl, hst⟩ ⟨hst, le_rfl⟩ hst
  rw [Metric.tendsto_atTop]
  intro ε hε
  have hbelow : ∃ T : ℝ, 0 ≤ T ∧ g T < ε := by
    by_contra hnone
    push_neg at hnone
    obtain ⟨η, hη, hdecay⟩ := huniform ε hε
    let T : ℝ := (g 0 + 1) / η
    have hTpos : 0 < T := by
      dsimp [T]
      have hg0 := hnonneg 0 le_rfl
      positivity
    have hgcont : ContinuousOn g (Icc 0 T) := by
      have hall : Continuous g := by
        rw [continuous_iff_continuousAt]
        exact fun t => (hd t).continuousAt
      exact hall.continuousOn
    obtain ⟨c, hc, hslope⟩ := exists_hasDerivAt_eq_slope
      (f := g) (f' := g') hTpos hgcont (fun t _ => hd t)
    have hc0 : 0 ≤ c := hc.1.le
    have hcdecay := hdecay c hc0 (hnone c hc0)
    have hT : 0 ≤ T := hTpos.le
    have hquot : (g T - g 0) / T ≤ -η := by
      simpa using hslope.symm.trans_le hcdecay
    have hdrop : g T ≤ g 0 - η * T := by
      apply (div_le_iff₀ hTpos).mp at hquot
      nlinarith
    have hcancel : η * T = g 0 + 1 := by
      dsimp [T]
      field_simp
    rw [hcancel] at hdrop
    linarith [hnonneg T hT]
  obtain ⟨T, hT, hsmall⟩ := hbelow
  refine ⟨T, ?_⟩
  intro t ht
  rw [Real.dist_eq, sub_zero, abs_of_nonneg (hnonneg t (hT.trans ht))]
  exact (hanti hT ht).trans_lt hsmall

theorem continuous_exponential_value_bound
    {g g' : ℝ → ℝ} {c T : ℝ}
    (hT : 0 ≤ T)
    (hd : ∀ t, HasDerivAt g (g' t) t)
    (hdecay : ∀ t ∈ Icc 0 T, g' t ≤ -c * g t) :
    g T ≤ Real.exp (-c * T) * g 0 := by
  let z : ℝ → ℝ := fun t => g t * Real.exp (c * t)
  have hzd : ∀ t, HasDerivAt z
      ((g' t + c * g t) * Real.exp (c * t)) t := by
    intro t
    have he : HasDerivAt (fun s => Real.exp (c * s))
        (Real.exp (c * t) * c) t := by
      simpa using (((hasDerivAt_id t).const_mul c)).exp
    change HasDerivAt (fun s => g s * Real.exp (c * s))
      ((g' t + c * g t) * Real.exp (c * t)) t
    rw [show (g' t + c * g t) * Real.exp (c * t) =
      g' t * Real.exp (c * t) + g t * (Real.exp (c * t) * c) by ring]
    exact (hd t).mul he
  have hzcont : Continuous z := by
    have hgcont : Continuous g := by
      rw [continuous_iff_continuousAt]
      exact fun t => (hd t).continuousAt
    exact hgcont.mul
      (Real.continuous_exp.comp (continuous_const.mul continuous_id))
  have hanti : AntitoneOn z (Icc 0 T) := by
    apply antitoneOn_of_deriv_nonpos (convex_Icc 0 T) hzcont.continuousOn
      (fun t _ => (hzd t).differentiableAt.differentiableWithinAt)
    intro t ht
    rw [(hzd t).deriv]
    have htin : t ∈ Icc 0 T := interior_subset ht
    exact mul_nonpos_of_nonpos_of_nonneg
      (by linarith [hdecay t htin]) (Real.exp_pos _).le
  have hzT0 : z T ≤ z 0 := hanti ⟨le_rfl, hT⟩ ⟨hT, le_rfl⟩ hT
  dsimp [z] at hzT0
  simp only [mul_zero, Real.exp_zero, mul_one] at hzT0
  have hdiv : g T ≤ g 0 / Real.exp (c * T) :=
    (le_div_iff₀ (Real.exp_pos (c * T))).2 hzT0
  rw [div_eq_mul_inv, ← Real.exp_neg] at hdiv
  convert hdiv using 1 <;> ring

theorem discrete_value_tendsto_zero_of_uniform_decay
    {g : ℕ → ℝ}
    (hnonneg : ∀ k, 0 ≤ g k)
    (hstep : ∀ k, g (k + 1) ≤ g k)
    (huniform : ∀ a, 0 < a → ∃ η, 0 < η ∧
      ∀ k, a ≤ g k → g (k + 1) ≤ g k - η) :
    Tendsto g atTop (nhds 0) := by
  have hanti : Antitone g := antitone_nat_of_succ_le hstep
  rw [Metric.tendsto_atTop]
  intro ε hε
  have hbelow : ∃ N : ℕ, g N < ε := by
    by_contra hnone
    push Not at hnone
    obtain ⟨η, hη, hdecay⟩ := huniform ε hε
    have hbound : ∀ k : ℕ, g k ≤ g 0 - (k : ℝ) * η := by
      intro k
      induction k with
      | zero => simp
      | succ k ih =>
          have hdrop := hdecay k (hnone k)
          rw [Nat.cast_succ]
          linarith
    obtain ⟨N, hN⟩ := exists_nat_gt (g 0 / η)
    have hmul : g 0 < (N : ℝ) * η := by
      apply (div_lt_iff₀ hη).mp at hN
      simpa [mul_comm] using hN
    linarith [hbound N, hnonneg N]
  obtain ⟨N, hsmall⟩ := hbelow
  refine ⟨N, ?_⟩
  intro k hk
  rw [Real.dist_eq, sub_zero, abs_of_nonneg (hnonneg k)]
  exact (hanti hk).trans_lt hsmall

theorem state_tendsto_zero_of_compact_of_value_tendsto_zero
    {E : Type*} [NormedAddCommGroup E]
    {K : Set E} (hK : IsCompact K) {V : E → ℝ} {trajectory : ℝ → E}
    (hV : Continuous V) (hVzero : V 0 = 0)
    (hpositive : ∀ x ∈ K, x ≠ 0 → 0 < V x)
    (htrajectory : ∀ t, 0 ≤ t → trajectory t ∈ K)
    (hvalue : Tendsto (fun t => V (trajectory t)) atTop (nhds 0)) :
    Tendsto trajectory atTop (nhds 0) := by
  rw [Metric.tendsto_atTop]
  intro ε hε
  let S : Set E := K ∩ {x | ε ≤ dist x 0}
  have hScompact : IsCompact S := by
    apply hK.inter_right
    exact isClosed_le continuous_const (continuous_id.dist continuous_const)
  by_cases hSne : S.Nonempty
  · obtain ⟨z, hzS, hzmin⟩ :=
      hScompact.exists_isMinOn hSne hV.continuousOn
    have hz0 : z ≠ 0 := by
      intro hz
      subst z
      have hbad : ε ≤ 0 := by simpa using hzS.2
      exact (not_le_of_gt hε) hbad
    have hm : 0 < V z := hpositive z hzS.1 hz0
    obtain ⟨T, hT⟩ := (Metric.tendsto_atTop.mp hvalue) (V z) hm
    refine ⟨max T 0, ?_⟩
    intro t ht
    have htT : T ≤ t := (le_max_left T 0).trans ht
    have ht0 : 0 ≤ t := (le_max_right T 0).trans ht
    have hsmall := hT t htT
    by_contra hnot
    have hdist : ε ≤ dist (trajectory t) 0 := le_of_not_gt hnot
    have htS : trajectory t ∈ S := ⟨htrajectory t ht0, hdist⟩
    have hnonneg : 0 ≤ V (trajectory t) := by
      by_cases hzero : trajectory t = 0
      · simpa [hzero, hVzero]
      · exact (hpositive (trajectory t) htS.1 hzero).le
    rw [Real.dist_eq, sub_zero, abs_of_nonneg hnonneg] at hsmall
    exact (not_lt_of_ge (hzmin htS)) hsmall
  · refine ⟨0, ?_⟩
    intro t ht
    have ht0 : 0 ≤ t := ht
    by_contra hnot
    exact hSne ⟨trajectory t, htrajectory t ht0, le_of_not_gt hnot⟩

theorem sequence_tendsto_zero_of_compact_of_value_tendsto_zero
    {E : Type*} [NormedAddCommGroup E]
    {K : Set E} (hK : IsCompact K) {V : E → ℝ} {trajectory : ℕ → E}
    (hV : Continuous V) (hVzero : V 0 = 0)
    (hpositive : ∀ x ∈ K, x ≠ 0 → 0 < V x)
    (htrajectory : ∀ k, trajectory k ∈ K)
    (hvalue : Tendsto (fun k => V (trajectory k)) atTop (nhds 0)) :
    Tendsto trajectory atTop (nhds 0) := by
  rw [Metric.tendsto_atTop]
  intro ε hε
  let S : Set E := K ∩ {x | ε ≤ dist x 0}
  have hScompact : IsCompact S := by
    apply hK.inter_right
    exact isClosed_le continuous_const (continuous_id.dist continuous_const)
  by_cases hSne : S.Nonempty
  · obtain ⟨z, hzS, hzmin⟩ :=
      hScompact.exists_isMinOn hSne hV.continuousOn
    have hz0 : z ≠ 0 := by
      intro hz
      subst z
      have hbad : ε ≤ 0 := by simpa using hzS.2
      exact (not_le_of_gt hε) hbad
    have hm : 0 < V z := hpositive z hzS.1 hz0
    obtain ⟨N, hN⟩ := (Metric.tendsto_atTop.mp hvalue) (V z) hm
    refine ⟨N, ?_⟩
    intro k hk
    have hsmall := hN k hk
    by_contra hnot
    have hkS : trajectory k ∈ S :=
      ⟨htrajectory k, le_of_not_gt hnot⟩
    have hnonneg : 0 ≤ V (trajectory k) := by
      by_cases hzero : trajectory k = 0
      · simp [hzero, hVzero]
      · exact (hpositive (trajectory k) hkS.1 hzero).le
    rw [Real.dist_eq, sub_zero, abs_of_nonneg hnonneg] at hsmall
    exact (not_lt_of_ge (hzmin hkS)) hsmall
  · refine ⟨0, ?_⟩
    intro k _
    by_contra hnot
    exact hSne ⟨trajectory k, htrajectory k, le_of_not_gt hnot⟩

theorem continuous_compact_sublevel_attracts
    {n : ℕ} {V lie : State n → ℝ} {γ : ℝ → State n} {c : ℝ}
    (hc : 0 < c)
    (hV : Continuous V) (hlie : Continuous lie) (hVzero : V 0 = 0)
    (hcompact : IsCompact {x | V x ≤ c})
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hlieZero : lie 0 = 0)
    (hlieNegative : ∀ x, V x ≤ c → x ≠ 0 → lie x < 0)
    (hderiv : ∀ t, HasDerivAt (fun s => V (γ s)) (lie (γ t)) t)
    (hinit : V (γ 0) ≤ c) :
    (∀ t, 0 ≤ t → V (γ t) ≤ c) ∧ Tendsto γ atTop (nhds 0) := by
  let K : Set (State n) := {x | V x ≤ c}
  have hstay : ∀ t, 0 ≤ t → V (γ t) ≤ c := by
    intro T hT
    apply strict_upper_boundary_scalar_preserves hT hderiv
      (fun t _ hlevel => by
        have hne : γ t ≠ 0 := by
          intro hzero
          rw [hzero, hVzero] at hlevel
          linarith
        exact hlieNegative (γ t) hlevel.le hne)
      hinit
  have htrajK : ∀ t, 0 ≤ t → γ t ∈ K := fun t ht => hstay t ht
  have hvalueNonneg : ∀ t, 0 ≤ t → 0 ≤ V (γ t) := by
    intro t ht
    by_cases hzero : γ t = 0
    · simp [hzero, hVzero]
    · exact (hpositive (γ t) (hstay t ht) hzero).le
  have hlieNonpos : ∀ t, 0 ≤ t → lie (γ t) ≤ 0 := by
    intro t ht
    by_cases hzero : γ t = 0
    · simp [hzero, hlieZero]
    · exact (hlieNegative (γ t) (hstay t ht) hzero).le
  have huniformState : ∀ a, 0 < a → ∃ η, 0 < η ∧
      ∀ x ∈ K, a ≤ V x → lie x ≤ -η := by
    apply uniform_negative_on_compact hcompact hV hlie
    intro x hx hVx
    have hne : x ≠ 0 := by
      intro hzero
      subst x
      simp [hVzero] at hVx
    exact hlieNegative x hx hne
  have hvalueTendsto : Tendsto (fun t => V (γ t)) atTop (nhds 0) := by
    apply continuous_value_tendsto_zero_of_uniform_decay
      hderiv hvalueNonneg hlieNonpos
    intro a ha
    obtain ⟨η, hη, hu⟩ := huniformState a ha
    exact ⟨η, hη, fun t ht hat => hu (γ t) (htrajK t ht) hat⟩
  refine ⟨hstay, ?_⟩
  apply state_tendsto_zero_of_compact_of_value_tendsto_zero
    hcompact hV hVzero
  · intro x hx hne
    exact hpositive x hx hne
  · exact htrajK
  · exact hvalueTendsto

theorem discrete_compact_sublevel_attracts
    {n : ℕ} {V : State n → ℝ} {step : State n → State n} {c : ℝ}
    (hc : 0 < c)
    (hV : Continuous V) (hstepContinuous : Continuous step) (hVzero : V 0 = 0)
    (hcompact : IsCompact {x | V x ≤ c})
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hfixed : step 0 = 0)
    (hdecrease : ∀ x, V x ≤ c → x ≠ 0 → V (step x) - V x < 0)
    {x₀ : State n} (hinit : V x₀ ≤ c) :
    (∀ k, V ((step^[k]) x₀) ≤ c) ∧
      Tendsto (fun k => (step^[k]) x₀) atTop (nhds 0) := by
  let K : Set (State n) := {x | V x ≤ c}
  let trajectory : ℕ → State n := fun k => (step^[k]) x₀
  have hnext (k : ℕ) : trajectory (k + 1) = step (trajectory k) := by
    simp [trajectory, Function.iterate_succ_apply']
  have hstay : ∀ k, V (trajectory k) ≤ c := by
    intro k
    induction k with
    | zero => simpa [trajectory] using hinit
    | succ k ih =>
        rw [show trajectory (k + 1) = step (trajectory k) from hnext k]
        by_cases hzero : trajectory k = 0
        · simp [hzero, hfixed, hVzero, hc.le]
        · linarith [hdecrease (trajectory k) ih hzero]
  have htrajK : ∀ k, trajectory k ∈ K := fun k => hstay k
  have hvalueNonneg : ∀ k, 0 ≤ V (trajectory k) := by
    intro k
    by_cases hzero : trajectory k = 0
    · simp [hzero, hVzero]
    · exact (hpositive (trajectory k) (hstay k) hzero).le
  let delta : State n → ℝ := fun x => V (step x) - V x
  have hdeltaContinuous : Continuous delta :=
    (hV.comp hstepContinuous).sub hV
  have huniformState : ∀ a, 0 < a → ∃ η, 0 < η ∧
      ∀ x ∈ K, a ≤ V x → delta x ≤ -η := by
    apply uniform_negative_on_compact hcompact hV hdeltaContinuous
    intro x hx hVx
    have hne : x ≠ 0 := by
      intro hzero
      subst x
      simp [hVzero] at hVx
    exact hdecrease x hx hne
  have hvalueTendsto : Tendsto (fun k => V (trajectory k)) atTop (nhds 0) := by
    apply discrete_value_tendsto_zero_of_uniform_decay hvalueNonneg
    · intro k
      rw [hnext]
      by_cases hzero : trajectory k = 0
      · simp [hzero, hfixed]
      · exact (sub_nonpos.mp (hdecrease (trajectory k) (hstay k) hzero).le)
    · intro a ha
      obtain ⟨η, hη, hu⟩ := huniformState a ha
      refine ⟨η, hη, ?_⟩
      intro k hak
      have hdelta := hu (trajectory k) (htrajK k) hak
      dsimp [delta] at hdelta
      rw [hnext]
      linarith
  refine ⟨?_, ?_⟩
  · intro k
    exact hstay k
  · apply sequence_tendsto_zero_of_compact_of_value_tendsto_zero
      hcompact hV hVzero
    · intro x hx hne
      exact hpositive x hx hne
    · exact htrajK
    · exact hvalueTendsto

theorem continuous_lyapunov_implies_roa
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n)
    (initial : Set (State n)) (c : ℝ)
    (hc : 0 < c)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlieContinuous : Continuous (fun x => ∑ i, gradient x i * flow x i))
    (hVzero : V 0 = 0)
    (hcompact : IsCompact {x | V x ≤ c})
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hflowZero : flow 0 = 0)
    (hlieNegative : ∀ x, V x ≤ c → x ≠ 0 →
      (∑ i, gradient x i * flow x i) < 0)
    (hinitial : ∀ x ∈ initial, V x ≤ c) :
    ContinuousROAOn initial {x | V x ≤ c}
      (LeanBarrier.ClassicalTrajectories flow) := by
  intro γ hγ hγ0
  have hVContinuous : Continuous V := by
    rw [continuous_iff_continuousAt]
    exact fun x => (hgradient x).continuousAt
  apply continuous_compact_sublevel_attracts
    hc hVContinuous hlieContinuous hVzero hcompact hpositive
  · simp [hflowZero]
  · exact hlieNegative
  · intro t
    simpa [Function.comp_def, LeanBarrier.gradientCLM_apply] using
      (hgradient (γ t)).comp_hasDerivAt t (hγ t)
  · exact hinitial (γ 0) hγ0

theorem discrete_lyapunov_implies_roa
    {n : ℕ} (V : State n → ℝ) (step : State n → State n)
    (initial : Set (State n)) (c : ℝ)
    (hc : 0 < c)
    (hV : Continuous V) (hstepContinuous : Continuous step)
    (hVzero : V 0 = 0)
    (hcompact : IsCompact {x | V x ≤ c})
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hfixed : step 0 = 0)
    (hdecrease : ∀ x, V x ≤ c → x ≠ 0 → V (step x) - V x < 0)
    (hinitial : ∀ x ∈ initial, V x ≤ c) :
    DiscreteROAOn step initial {x | V x ≤ c} := by
  intro x hx
  exact discrete_compact_sublevel_attracts hc hV hstepContinuous hVzero
    hcompact hpositive hfixed hdecrease (hinitial x hx)

theorem continuous_lyapunov_sublevel_is_roa
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n) (c : ℝ)
    (hc : 0 < c)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlieContinuous : Continuous (fun x => ∑ i, gradient x i * flow x i))
    (hVzero : V 0 = 0)
    (hcompact : IsCompact {x | V x ≤ c})
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hflowZero : flow 0 = 0)
    (hlieNegative : ∀ x, V x ≤ c → x ≠ 0 →
      (∑ i, gradient x i * flow x i) < 0) :
    ContinuousROAOn {x | V x ≤ c} {x | V x ≤ c}
      (LeanBarrier.ClassicalTrajectories flow) := by
  apply continuous_lyapunov_implies_roa V gradient flow {x | V x ≤ c} c
    hc hgradient hlieContinuous hVzero hcompact hpositive hflowZero hlieNegative
  intro x hx
  exact hx

theorem continuous_lyapunov_sublevel_is_roa_of_subset_coordinateBox
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n) (c : ℝ)
    (lower upper : ℝ)
    (hc : 0 < c)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlieContinuous : Continuous (fun x ↦ ∑ i, gradient x i * flow x i))
    (hVzero : V 0 = 0)
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hflowZero : flow 0 = 0)
    (hlieNegative : ∀ x, V x ≤ c → x ≠ 0 →
      (∑ i, gradient x i * flow x i) < 0)
    (hsubset : {x | V x ≤ c} ⊆
      {x | ∀ i, lower ≤ x i ∧ x i ≤ upper}) :
    ContinuousROAOn {x | V x ≤ c} {x | V x ≤ c}
      (LeanBarrier.ClassicalTrajectories flow) := by
  have hVContinuous : Continuous V := by
    rw [continuous_iff_continuousAt]
    exact fun x ↦ (hgradient x).continuousAt
  have hboxCompact : IsCompact
      ({x : State n | ∀ i, lower ≤ x i ∧ x i ≤ upper}) := by
    have hboxEq : {x : State n | ∀ i, lower ≤ x i ∧ x i ≤ upper} =
        Set.Icc (fun _ ↦ lower) (fun _ ↦ upper) := by
      ext x
      constructor
      · intro hx
        exact ⟨fun i ↦ (hx i).1, fun i ↦ (hx i).2⟩
      · rintro ⟨hlower, hupper⟩ i
        exact ⟨hlower i, hupper i⟩
    rw [hboxEq]
    exact isCompact_Icc
  have hcompact : IsCompact {x | V x ≤ c} :=
    compact_sublevel_of_continuous_bounded_superset
      hVContinuous hboxCompact.isBounded hsubset
  exact continuous_lyapunov_sublevel_is_roa V gradient flow c
    hc hgradient hlieContinuous hVzero hcompact hpositive hflowZero hlieNegative

theorem discrete_lyapunov_sublevel_is_roa
    {n : ℕ} (V : State n → ℝ) (step : State n → State n) (c : ℝ)
    (hc : 0 < c)
    (hV : Continuous V) (hstepContinuous : Continuous step)
    (hVzero : V 0 = 0)
    (hcompact : IsCompact {x | V x ≤ c})
    (hpositive : ∀ x, V x ≤ c → x ≠ 0 → 0 < V x)
    (hfixed : step 0 = 0)
    (hdecrease : ∀ x, V x ≤ c → x ≠ 0 → V (step x) - V x < 0) :
    DiscreteROAOn step {x | V x ≤ c} {x | V x ≤ c} := by
  apply discrete_lyapunov_implies_roa V step {x | V x ≤ c} c
    hc hV hstepContinuous hVzero hcompact hpositive hfixed hdecrease
  intro x hx
  exact hx

theorem continuous_lyapunov_implies_stable_in
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n)
    (domain : Set (State n))
    (hcompact : IsCompact domain)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hVzero : V 0 = 0)
    (hpositive : ∀ x ∈ domain, x ≠ 0 → 0 < V x)
    (hlieNonpositive : ∀ x ∈ domain,
      (∑ i, gradient x i * flow x i) ≤ 0) :
    ContinuousStableIn domain (LeanBarrier.ClassicalTrajectories flow) := by
  have hVContinuous : Continuous V := by
    rw [continuous_iff_continuousAt]
    exact fun x => (hgradient x).continuousAt
  intro ε hε
  let S : Set (State n) := domain ∩ {x | ε ≤ dist x 0}
  have hScompact : IsCompact S := by
    apply hcompact.inter_right
    exact isClosed_le continuous_const (continuous_id.dist continuous_const)
  by_cases hSne : S.Nonempty
  · obtain ⟨z, hzS, hzmin⟩ :=
      hScompact.exists_isMinOn hSne hVContinuous.continuousOn
    have hz0 : z ≠ 0 := by
      intro hz
      subst z
      have hbad : ε ≤ 0 := by simpa using hzS.2
      exact (not_le_of_gt hε) hbad
    have hm : 0 < V z := hpositive z hzS.1 hz0
    obtain ⟨δ, hδ, hnear⟩ :=
      (Metric.continuousAt_iff.mp hVContinuous.continuousAt) (V z) hm
    refine ⟨δ, hδ, ?_⟩
    intro γ hγ hγ0 T hT hstay
    have hderiv : ∀ t, HasDerivAt (fun s => V (γ s))
        (∑ i, gradient (γ t) i * flow (γ t) i) t := by
      intro t
      simpa [Function.comp_def, LeanBarrier.gradientCLM_apply] using
        (hgradient (γ t)).comp_hasDerivAt t (hγ t)
    have hanti : AntitoneOn (fun t => V (γ t)) (Icc 0 T) := by
      apply antitoneOn_of_deriv_nonpos (convex_Icc 0 T)
      · exact (hVContinuous.comp (by
          rw [continuous_iff_continuousAt]
          exact fun t => (hγ t).continuousAt)).continuousOn
      · intro t _
        exact (hderiv t).differentiableAt.differentiableWithinAt
      · intro t ht
        rw [(hderiv t).deriv]
        exact hlieNonpositive (γ t) (hstay t (interior_subset ht))
    have hvalue : V (γ T) ≤ V (γ 0) :=
      hanti ⟨le_rfl, hT⟩ ⟨hT, le_rfl⟩ hT
    have h0mem : γ 0 ∈ domain := hstay 0 ⟨le_rfl, hT⟩
    have hV0nonneg : 0 ≤ V (γ 0) := by
      by_cases hzero : γ 0 = 0
      · simp [hzero, hVzero]
      · exact (hpositive (γ 0) h0mem hzero).le
    have hV0small : V (γ 0) < V z := by
      have hdist := hnear hγ0
      rw [Real.dist_eq, hVzero, sub_zero, abs_of_nonneg hV0nonneg] at hdist
      exact hdist
    by_contra hnot
    have hTS : γ T ∈ S :=
      ⟨hstay T ⟨hT, le_rfl⟩, le_of_not_gt hnot⟩
    exact (not_lt_of_ge ((hzmin hTS).trans hvalue)) hV0small
  · refine ⟨1, by norm_num, ?_⟩
    intro γ _ _ T hT hstay
    by_contra hnot
    exact hSne ⟨γ T, hstay T ⟨hT, le_rfl⟩, le_of_not_gt hnot⟩

theorem discrete_lyapunov_implies_stable_in
    {n : ℕ} (V : State n → ℝ) (step : State n → State n)
    (domain : Set (State n))
    (hcompact : IsCompact domain) (hV : Continuous V) (hVzero : V 0 = 0)
    (hpositive : ∀ x ∈ domain, x ≠ 0 → 0 < V x)
    (hdecrease : ∀ x ∈ domain, V (step x) ≤ V x) :
    DiscreteStableIn step domain := by
  intro ε hε
  let S : Set (State n) := domain ∩ {x | ε ≤ dist x 0}
  have hScompact : IsCompact S := by
    apply hcompact.inter_right
    exact isClosed_le continuous_const (continuous_id.dist continuous_const)
  by_cases hSne : S.Nonempty
  · obtain ⟨z, hzS, hzmin⟩ := hScompact.exists_isMinOn hSne hV.continuousOn
    have hz0 : z ≠ 0 := by
      intro hz
      subst z
      have hbad : ε ≤ 0 := by simpa using hzS.2
      exact (not_le_of_gt hε) hbad
    have hm : 0 < V z := hpositive z hzS.1 hz0
    obtain ⟨δ, hδ, hnear⟩ :=
      (Metric.continuousAt_iff.mp (hV.continuousAt : ContinuousAt V 0)) (V z) hm
    refine ⟨δ, hδ, ?_⟩
    intro x hx k hstay
    let trajectory : ℕ → State n := fun j => (step^[j]) x
    have hnext (j : ℕ) : trajectory (j + 1) = step (trajectory j) := by
      simp [trajectory, Function.iterate_succ_apply']
    have hvalue : V (trajectory k) ≤ V (trajectory 0) := by
      induction k with
      | zero => exact le_rfl
      | succ k ih =>
          calc
            V (trajectory (k + 1)) = V (step (trajectory k)) := by rw [hnext]
            _ ≤ V (trajectory k) :=
              hdecrease (trajectory k) (hstay k (Nat.le_succ k))
            _ ≤ V (trajectory 0) :=
              ih (fun j hj => hstay j (hj.trans (Nat.le_succ k)))
    have h0mem : trajectory 0 ∈ domain := hstay 0 (Nat.zero_le k)
    have hV0nonneg : 0 ≤ V (trajectory 0) := by
      by_cases hzero : trajectory 0 = 0
      · simp [hzero, hVzero]
      · exact (hpositive (trajectory 0) h0mem hzero).le
    have hV0small : V (trajectory 0) < V z := by
      rw [show trajectory 0 = x by simp [trajectory]]
      have hdist := hnear hx
      have hxnonneg : 0 ≤ V x := by simpa [trajectory] using hV0nonneg
      rw [Real.dist_eq, hVzero, sub_zero, abs_of_nonneg hxnonneg] at hdist
      exact hdist
    by_contra hnot
    have hkS : trajectory k ∈ S := ⟨hstay k le_rfl, le_of_not_gt hnot⟩
    exact (not_lt_of_ge ((hzmin hkS).trans hvalue)) hV0small
  · refine ⟨1, by norm_num, ?_⟩
    intro x _ k hstay
    by_contra hnot
    exact hSne ⟨(step^[k]) x, hstay k le_rfl, le_of_not_gt hnot⟩

theorem continuous_strict_lyapunov_implies_asymptotic_stable_in
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n)
    (domain : Set (State n))
    (hcompact : IsCompact domain)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlieContinuous : Continuous (fun x => ∑ i, gradient x i * flow x i))
    (hVzero : V 0 = 0)
    (hpositive : ∀ x ∈ domain, x ≠ 0 → 0 < V x)
    (hflowZero : flow 0 = 0)
    (hlieNegative : ∀ x ∈ domain, x ≠ 0 →
      (∑ i, gradient x i * flow x i) < 0) :
    ContinuousStableIn domain (LeanBarrier.ClassicalTrajectories flow) ∧
      ContinuousAttractiveIn domain (LeanBarrier.ClassicalTrajectories flow) := by
  have hlieZero : (∑ i, gradient (0 : State n) i * flow 0 i) = 0 := by
    simp [hflowZero]
  have hlieNonpositive : ∀ x ∈ domain,
      (∑ i, gradient x i * flow x i) ≤ 0 := by
    intro x hx
    by_cases hzero : x = 0
    · simpa [hzero] using hlieZero.le
    · exact (hlieNegative x hx hzero).le
  refine ⟨continuous_lyapunov_implies_stable_in V gradient flow domain
    hcompact hgradient hVzero hpositive hlieNonpositive, ?_⟩
  intro γ hγ hstay
  have hVContinuous : Continuous V := by
    rw [continuous_iff_continuousAt]
    exact fun x => (hgradient x).continuousAt
  have hderiv : ∀ t, HasDerivAt (fun s => V (γ s))
      (∑ i, gradient (γ t) i * flow (γ t) i) t := by
    intro t
    simpa [Function.comp_def, LeanBarrier.gradientCLM_apply] using
      (hgradient (γ t)).comp_hasDerivAt t (hγ t)
  have hvalueNonneg : ∀ t, 0 ≤ t → 0 ≤ V (γ t) := by
    intro t ht
    by_cases hzero : γ t = 0
    · simp [hzero, hVzero]
    · exact (hpositive (γ t) (hstay t ht) hzero).le
  have hvalueTendsto : Tendsto (fun t => V (γ t)) atTop (nhds 0) := by
    apply continuous_value_tendsto_zero_of_uniform_decay
      hderiv hvalueNonneg
      (fun t ht => hlieNonpositive (γ t) (hstay t ht))
    intro a ha
    obtain ⟨η, hη, hu⟩ := uniform_negative_on_compact
      hcompact hVContinuous hlieContinuous
      (fun x hx hVx => by
        have hne : x ≠ 0 := by
          intro hzero
          subst x
          simp [hVzero] at hVx
        exact hlieNegative x hx hne) a ha
    exact ⟨η, hη, fun t ht hat => hu (γ t) (hstay t ht) hat⟩
  exact state_tendsto_zero_of_compact_of_value_tendsto_zero
    hcompact hVContinuous hVzero hpositive hstay hvalueTendsto

theorem discrete_strict_lyapunov_implies_asymptotic_stable_in
    {n : ℕ} (V : State n → ℝ) (step : State n → State n)
    (domain : Set (State n))
    (hcompact : IsCompact domain) (hV : Continuous V)
    (hstepContinuous : Continuous step) (hVzero : V 0 = 0)
    (hpositive : ∀ x ∈ domain, x ≠ 0 → 0 < V x)
    (hfixed : step 0 = 0)
    (hdecrease : ∀ x ∈ domain, x ≠ 0 → V (step x) - V x < 0) :
    DiscreteStableIn step domain ∧ DiscreteAttractiveIn step domain := by
  have hnonincrease : ∀ x ∈ domain, V (step x) ≤ V x := by
    intro x hx
    by_cases hzero : x = 0
    · simp [hzero, hfixed]
    · exact sub_nonpos.mp (hdecrease x hx hzero).le
  refine ⟨discrete_lyapunov_implies_stable_in V step domain
    hcompact hV hVzero hpositive hnonincrease, ?_⟩
  intro x hstay
  let trajectory : ℕ → State n := fun k => (step^[k]) x
  have hnext (k : ℕ) : trajectory (k + 1) = step (trajectory k) := by
    simp [trajectory, Function.iterate_succ_apply']
  have hvalueNonneg : ∀ k, 0 ≤ V (trajectory k) := by
    intro k
    by_cases hzero : trajectory k = 0
    · simp [hzero, hVzero]
    · exact (hpositive (trajectory k) (hstay k) hzero).le
  let delta : State n → ℝ := fun y => V (step y) - V y
  have hdeltaContinuous : Continuous delta := (hV.comp hstepContinuous).sub hV
  have hvalueTendsto : Tendsto (fun k => V (trajectory k)) atTop (nhds 0) := by
    apply discrete_value_tendsto_zero_of_uniform_decay hvalueNonneg
    · intro k
      rw [hnext]
      exact hnonincrease (trajectory k) (hstay k)
    · intro a ha
      obtain ⟨η, hη, hu⟩ := uniform_negative_on_compact
        hcompact hV hdeltaContinuous
        (fun y hy hVy => by
          have hne : y ≠ 0 := by
            intro hzero
            subst y
            simp [hVzero] at hVy
          exact hdecrease y hy hne) a ha
      refine ⟨η, hη, ?_⟩
      intro k hak
      have hdelta := hu (trajectory k) (hstay k) hak
      dsimp [delta] at hdelta
      rw [hnext]
      linarith
  exact sequence_tendsto_zero_of_compact_of_value_tendsto_zero
    hcompact hV hVzero hpositive hstay hvalueTendsto

theorem continuous_lyapunov_implies_global_asymptotic_stability
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlieContinuous : Continuous (fun x => ∑ i, gradient x i * flow x i))
    (hVzero : V 0 = 0)
    (hpositive : ∀ x, x ≠ 0 → 0 < V x)
    (hflowZero : flow 0 = 0)
    (hlieNegative : ∀ x, x ≠ 0 →
      (∑ i, gradient x i * flow x i) < 0)
    (hradial : RadiallyUnbounded V) :
    ContinuousGloballyAsymptoticallyStable flow := by
  have hVContinuous : Continuous V := by
    rw [continuous_iff_continuousAt]
    exact fun x => (hgradient x).continuousAt
  have hcompact : ∀ c, IsCompact {x | V x ≤ c} :=
    radiallyUnbounded_compact_sublevel hVContinuous hradial
  have hlieZero : (∑ i, gradient (0 : State n) i * flow 0 i) = 0 := by
    simp [hflowZero]
  have hsublevelAttracts : ∀ {c : ℝ}, 0 < c →
      ∀ {gamma : ℝ → State n},
        LeanBarrier.ClassicalTrajectory flow gamma → V (gamma 0) ≤ c →
        (∀ t, 0 ≤ t → V (gamma t) ≤ c) ∧
          Tendsto gamma atTop (nhds 0) := by
    intro c hc gamma hgamma hinit
    apply continuous_compact_sublevel_attracts
      hc hVContinuous hlieContinuous hVzero (hcompact c)
      (fun x _ hx => hpositive x hx) hlieZero
      (fun x _ hx => hlieNegative x hx)
    · intro t
      simpa [Function.comp_def, LeanBarrier.gradientCLM_apply] using
        (hgradient (gamma t)).comp_hasDerivAt t (hgamma t)
    · exact hinit
  constructor
  · have hstableOne := continuous_lyapunov_implies_stable_in
      V gradient flow {x | V x ≤ 1} (hcompact 1) hgradient hVzero
      (fun x _ hx => hpositive x hx)
      (fun x _ => by
        by_cases hx : x = 0
        · simpa [hx] using hlieZero.le
        · exact (hlieNegative x hx).le)
    intro epsilon hepsilon
    obtain ⟨deltaOne, hdeltaOne, hstable⟩ := hstableOne epsilon hepsilon
    obtain ⟨deltaV, hdeltaV, hnearV⟩ :=
      (Metric.continuousAt_iff.mp hVContinuous.continuousAt) 1 zero_lt_one
    refine ⟨min deltaOne deltaV, lt_min hdeltaOne hdeltaV, ?_⟩
    intro gamma hgamma hgamma0 T hT _
    have hgamma0V : V (gamma 0) < 1 := by
      have hdist := hnearV (lt_of_lt_of_le hgamma0 (min_le_right _ _))
      have hnonneg : 0 ≤ V (gamma 0) := by
        by_cases hz : gamma 0 = 0
        · simp [hz, hVzero]
        · exact (hpositive (gamma 0) hz).le
      rw [Real.dist_eq, hVzero, sub_zero, abs_of_nonneg hnonneg] at hdist
      exact hdist
    have hstay := (hsublevelAttracts zero_lt_one hgamma hgamma0V.le).1
    exact hstable gamma hgamma
      (lt_of_lt_of_le hgamma0 (min_le_left _ _)) T hT
      (fun t ht => hstay t ht.1)
  · intro gamma hgamma _
    have hnonneg : 0 ≤ V (gamma 0) := by
      by_cases hz : gamma 0 = 0
      · simp [hz, hVzero]
      · exact (hpositive (gamma 0) hz).le
    exact (hsublevelAttracts (by linarith : 0 < V (gamma 0) + 1)
      hgamma (by linarith)).2

theorem discrete_lyapunov_implies_global_asymptotic_stability
    {n : ℕ} (V : State n → ℝ) (step : State n → State n)
    (hV : Continuous V) (hstepContinuous : Continuous step)
    (hVzero : V 0 = 0)
    (hpositive : ∀ x, x ≠ 0 → 0 < V x)
    (hfixed : step 0 = 0)
    (hdecrease : ∀ x, x ≠ 0 → V (step x) - V x < 0)
    (hradial : RadiallyUnbounded V) :
    DiscreteGloballyAsymptoticallyStable step := by
  have hcompact : ∀ c, IsCompact {x | V x ≤ c} :=
    radiallyUnbounded_compact_sublevel hV hradial
  have hsublevelAttracts : ∀ {c : ℝ}, 0 < c → ∀ {x : State n}, V x ≤ c →
      (∀ k, V ((step^[k]) x) ≤ c) ∧
        Tendsto (fun k => (step^[k]) x) atTop (nhds 0) := by
    intro c hc x hinit
    exact discrete_compact_sublevel_attracts hc hV hstepContinuous hVzero
      (hcompact c) (fun y _ hy => hpositive y hy) hfixed
      (fun y _ hy => hdecrease y hy) hinit
  constructor
  · have hstableOne := discrete_lyapunov_implies_stable_in
      V step {x | V x ≤ 1} (hcompact 1) hV hVzero
      (fun x _ hx => hpositive x hx)
      (fun x _ => by
        by_cases hx : x = 0
        · simp [hx, hfixed]
        · exact sub_nonpos.mp (hdecrease x hx).le)
    intro epsilon hepsilon
    obtain ⟨deltaOne, hdeltaOne, hstable⟩ := hstableOne epsilon hepsilon
    obtain ⟨deltaV, hdeltaV, hnearV⟩ :=
      (Metric.continuousAt_iff.mp (hV.continuousAt : ContinuousAt V 0)) 1 zero_lt_one
    refine ⟨min deltaOne deltaV, lt_min hdeltaOne hdeltaV, ?_⟩
    intro x hx k _
    have hxV : V x < 1 := by
      have hdist := hnearV (lt_of_lt_of_le hx (min_le_right _ _))
      have hnonneg : 0 ≤ V x := by
        by_cases hz : x = 0
        · simp [hz, hVzero]
        · exact (hpositive x hz).le
      rw [Real.dist_eq, hVzero, sub_zero, abs_of_nonneg hnonneg] at hdist
      exact hdist
    have hstay := (hsublevelAttracts zero_lt_one hxV.le).1
    exact hstable x (lt_of_lt_of_le hx (min_le_left _ _)) k
      (fun j _ => hstay j)
  · intro x _
    have hnonneg : 0 ≤ V x := by
      by_cases hz : x = 0
      · simp [hz, hVzero]
      · exact (hpositive x hz).le
    exact (hsublevelAttracts (by linarith : 0 < V x + 1)
      (by linarith)).2

theorem continuous_lyapunov_implies_exponential_bound
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n)
    (N : Set (State n)) (c₁ c₂ c₃ : ℝ)
    (hc₁ : 0 < c₁) (hc₂ : 0 < c₂) (hc₃ : 0 < c₃)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlower : ∀ x ∈ N, c₁ * sqNorm x ≤ V x)
    (hupper : ∀ x ∈ N, V x ≤ c₂ * sqNorm x)
    (hdecay : ∀ x ∈ N, (∑ i, gradient x i * flow x i) ≤ -c₃ * V x)
    {γ : ℝ → State n} (hγ : LeanBarrier.ClassicalTrajectory flow γ)
    {T : ℝ} (hT : 0 ≤ T) (hstay : ∀ t ∈ Icc 0 T, γ t ∈ N) :
    sqNorm (γ T) ≤
      (c₂ / c₁) * Real.exp (-c₃ * T) * sqNorm (γ 0) := by
  have hderiv : ∀ t, HasDerivAt (fun s => V (γ s))
      (∑ i, gradient (γ t) i * flow (γ t) i) t := by
    intro t
    simpa [Function.comp_def, LeanBarrier.gradientCLM_apply] using
      (hgradient (γ t)).comp_hasDerivAt t (hγ t)
  have hvalue := continuous_exponential_value_bound
    (g := fun t => V (γ t))
    (g' := fun t => ∑ i, gradient (γ t) i * flow (γ t) i)
    (c := c₃) hT hderiv
    (fun t ht => hdecay (γ t) (hstay t ht))
  have h0mem : γ 0 ∈ N := hstay 0 ⟨le_rfl, hT⟩
  have hTmem : γ T ∈ N := hstay T ⟨hT, le_rfl⟩
  have hexp : 0 ≤ Real.exp (-c₃ * T) := (Real.exp_pos _).le
  calc
    sqNorm (γ T) ≤ V (γ T) / c₁ :=
      (le_div_iff₀ hc₁).2 (by simpa [mul_comm] using hlower (γ T) hTmem)
    _ ≤ (Real.exp (-c₃ * T) * V (γ 0)) / c₁ :=
      div_le_div_of_nonneg_right hvalue hc₁.le
    _ ≤ (Real.exp (-c₃ * T) * (c₂ * sqNorm (γ 0))) / c₁ :=
      div_le_div_of_nonneg_right
        (mul_le_mul_of_nonneg_left (hupper (γ 0) h0mem) hexp) hc₁.le
    _ = (c₂ / c₁) * Real.exp (-c₃ * T) * sqNorm (γ 0) := by
      field_simp

theorem discrete_lyapunov_implies_exponential_bound
    {n : ℕ} (V : State n → ℝ) (step : State n → State n)
    (N : Set (State n)) (c₁ c₂ c₃ : ℝ)
    (hc₁ : 0 < c₁) (hc₂ : 0 < c₂) (hc₃ : 0 < c₃) (hc₃one : c₃ ≤ 1)
    (hlower : ∀ x ∈ N, c₁ * sqNorm x ≤ V x)
    (hupper : ∀ x ∈ N, V x ≤ c₂ * sqNorm x)
    (hdecay : ∀ x ∈ N, V (step x) ≤ (1 - c₃) * V x)
    {x₀ : State n} (hstay : ∀ k, (step^[k]) x₀ ∈ N) :
    ∀ k, sqNorm ((step^[k]) x₀) ≤
      (c₂ / c₁) * (1 - c₃) ^ k * sqNorm x₀ := by
  let trajectory : ℕ → State n := fun k => (step^[k]) x₀
  have hnext (k : ℕ) : trajectory (k + 1) = step (trajectory k) := by
    simp [trajectory, Function.iterate_succ_apply']
  have hvalue : ∀ k, V (trajectory k) ≤ (1 - c₃) ^ k * V x₀ := by
    intro k
    induction k with
    | zero => simp [trajectory]
    | succ k ih =>
        rw [hnext, pow_succ]
        have hfactor : 0 ≤ 1 - c₃ := sub_nonneg.mpr hc₃one
        calc
          V (step (trajectory k)) ≤ (1 - c₃) * V (trajectory k) :=
            hdecay (trajectory k) (hstay k)
          _ ≤ (1 - c₃) * ((1 - c₃) ^ k * V x₀) :=
            mul_le_mul_of_nonneg_left ih hfactor
          _ = (1 - c₃) ^ k * (1 - c₃) * V x₀ := by ring
  intro k
  have hfactor : 0 ≤ (1 - c₃) ^ k := pow_nonneg (sub_nonneg.mpr hc₃one) k
  have h0mem : x₀ ∈ N := by simpa [trajectory] using hstay 0
  have hkmem : trajectory k ∈ N := hstay k
  calc
    sqNorm (trajectory k) ≤ V (trajectory k) / c₁ :=
      (le_div_iff₀ hc₁).2 (by simpa [mul_comm] using hlower (trajectory k) hkmem)
    _ ≤ (((1 - c₃) ^ k) * V x₀) / c₁ :=
      div_le_div_of_nonneg_right (hvalue k) hc₁.le
    _ ≤ (((1 - c₃) ^ k) * (c₂ * sqNorm x₀)) / c₁ :=
      div_le_div_of_nonneg_right
        (mul_le_mul_of_nonneg_left (hupper x₀ h0mem) hfactor) hc₁.le
    _ = (c₂ / c₁) * (1 - c₃) ^ k * sqNorm x₀ := by
      field_simp

theorem continuous_lyapunov_implies_exponential_stable_in
    {n : ℕ} (V : State n → ℝ) (gradient flow : State n → State n)
    (domain : Set (State n)) (c₁ c₂ c₃ : ℝ)
    (hc₁ : 0 < c₁) (hc₂ : 0 < c₂) (hc₃ : 0 < c₃)
    (hgradient : LeanBarrier.IsGradient V gradient)
    (hlower : ∀ x ∈ domain, c₁ * sqNorm x ≤ V x)
    (hupper : ∀ x ∈ domain, V x ≤ c₂ * sqNorm x)
    (hdecay : ∀ x ∈ domain,
      (∑ i, gradient x i * flow x i) ≤ -c₃ * V x) :
    ContinuousExponentiallyStableIn flow domain := by
  refine ⟨c₂ / c₁, c₃, div_pos hc₂ hc₁, hc₃, ?_⟩
  intro gamma hgamma T hT hstay
  exact continuous_lyapunov_implies_exponential_bound
    V gradient flow domain c₁ c₂ c₃ hc₁ hc₂ hc₃ hgradient
    hlower hupper hdecay hgamma hT hstay

theorem discrete_lyapunov_implies_exponential_stable_in
    {n : ℕ} (V : State n → ℝ) (step : State n → State n)
    (domain : Set (State n)) (c₁ c₂ c₃ : ℝ)
    (hc₁ : 0 < c₁) (hc₂ : 0 < c₂) (hc₃ : 0 < c₃) (hc₃one : c₃ ≤ 1)
    (hlower : ∀ x ∈ domain, c₁ * sqNorm x ≤ V x)
    (hupper : ∀ x ∈ domain, V x ≤ c₂ * sqNorm x)
    (hdecay : ∀ x ∈ domain, V (step x) ≤ (1 - c₃) * V x) :
    DiscreteExponentiallyStableIn step domain := by
  refine ⟨c₂ / c₁, 1 - c₃, div_pos hc₂ hc₁,
    sub_nonneg.mpr hc₃one, sub_lt_self 1 hc₃, ?_⟩
  intro x hstay k
  exact discrete_lyapunov_implies_exponential_bound
    V step domain c₁ c₂ c₃ hc₁ hc₂ hc₃ hc₃one
    hlower hupper hdecay hstay k

end LeanBarrier.Lyapunov
