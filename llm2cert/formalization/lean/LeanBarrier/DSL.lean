-- Interpret certificate expressions and prove their regularity.
import Mathlib

namespace LeanBarrier.DSL

abbrev RealHasDerivAt (f : ℝ → ℝ) (f' x : ℝ) : Prop :=
  @HasDerivAt ℝ inferInstance ℝ
    Real.normedAddCommGroup.toAddCommGroup
    (NormedAlgebra.toNormedSpace ℝ).toModule
    PseudoMetricSpace.toUniformSpace.toTopologicalSpace
    inferInstance f f' x

inductive Expr (n : ℕ) where
  | const (value : ℚ)
  | pi
  | var (index : Fin n)
  | add (left right : Expr n)
  | sub (left right : Expr n)
  | mul (left right : Expr n)
  | div (left right : Expr n)
  | neg (arg : Expr n)
  | pow (base : Expr n) (exponent : ℕ)
  | sin (arg : Expr n)
  | cos (arg : Expr n)
  | exp (arg : Expr n)
  | tanh (arg : Expr n)
  | log (arg : Expr n)
  | sqrt (arg : Expr n)
  | atan (arg : Expr n)
  deriving Repr, DecidableEq

noncomputable def eval {n : ℕ} : Expr n → (Fin n → ℝ) → ℝ
  | .const value, _ => value
  | .pi, _ => Real.pi
  | .var index, x => x index
  | .add left right, x => eval left x + eval right x
  | .sub left right, x => eval left x - eval right x
  | .mul left right, x => eval left x * eval right x
  | .div left right, x => eval left x / eval right x
  | .neg arg, x => -eval arg x
  | .pow base exponent, x => eval base x ^ exponent
  | .sin arg, x => Real.sin (eval arg x)
  | .cos arg, x => Real.cos (eval arg x)
  | .exp arg, x => Real.exp (eval arg x)
  | .tanh arg, x => Real.tanh (eval arg x)
  | .log arg, x => Real.log (eval arg x)
  | .sqrt arg, x => Real.sqrt (eval arg x)
  | .atan arg, x => Real.arctan (eval arg x)

def symbolicDeriv {n : ℕ} : Expr n → Fin n → Expr n
  | .const _, _ => .const 0
  | .pi, _ => .const 0
  | .var index, coordinate => if index = coordinate then .const 1 else .const 0
  | .add left right, coordinate =>
      .add (symbolicDeriv left coordinate) (symbolicDeriv right coordinate)
  | .sub left right, coordinate =>
      .sub (symbolicDeriv left coordinate) (symbolicDeriv right coordinate)
  | .mul left right, coordinate =>
      .add (.mul (symbolicDeriv left coordinate) right)
        (.mul left (symbolicDeriv right coordinate))
  | .div left right, coordinate =>
      .div
        (.sub (.mul (symbolicDeriv left coordinate) right)
          (.mul left (symbolicDeriv right coordinate)))
        (.pow right 2)
  | .neg arg, coordinate => .neg (symbolicDeriv arg coordinate)
  | .pow base exponent, coordinate =>
      .mul (.mul (.const exponent) (.pow base (exponent - 1)))
        (symbolicDeriv base coordinate)
  | .sin arg, coordinate => .mul (.cos arg) (symbolicDeriv arg coordinate)
  | .cos arg, coordinate => .mul (.neg (.sin arg)) (symbolicDeriv arg coordinate)
  | .exp arg, coordinate => .mul (.exp arg) (symbolicDeriv arg coordinate)
  | .tanh arg, coordinate =>
      .mul (.sub (.const 1) (.pow (.tanh arg) 2)) (symbolicDeriv arg coordinate)
  | .log arg, coordinate => .div (symbolicDeriv arg coordinate) arg
  | .sqrt arg, coordinate =>
      .div (symbolicDeriv arg coordinate) (.mul (.const 2) (.sqrt arg))
  | .atan arg, coordinate =>
      .div (symbolicDeriv arg coordinate) (.add (.const 1) (.pow arg 2))

def isTotalSmooth {n : ℕ} : Expr n → Bool
  | .const _ => true
  | .pi => true
  | .var _ => true
  | .add left right => isTotalSmooth left && isTotalSmooth right
  | .sub left right => isTotalSmooth left && isTotalSmooth right
  | .mul left right => isTotalSmooth left && isTotalSmooth right
  | .div _ _ => false
  | .neg arg => isTotalSmooth arg
  | .pow base _ => isTotalSmooth base
  | .sin arg => isTotalSmooth arg
  | .cos arg => isTotalSmooth arg
  | .exp arg => isTotalSmooth arg
  | .tanh arg => isTotalSmooth arg
  | .log _ => false
  | .sqrt _ => false
  | .atan arg => isTotalSmooth arg

theorem contDiff_tanh : ContDiff ℝ ⊤ Real.tanh := by
  have hsinh : ContDiff ℝ ⊤ Real.sinh := by fun_prop
  have hcosh : ContDiff ℝ ⊤ Real.cosh := by fun_prop
  have hdiv := hsinh.div hcosh (fun x => ne_of_gt (Real.cosh_pos x))
  have function_eq : Real.tanh = Real.sinh / Real.cosh := by
    funext value
    simpa only [Pi.div_apply] using Real.tanh_eq_sinh_div_cosh value
  rw [function_eq]
  exact hdiv

private lemma totalSmooth_and {n : ℕ} {left right : Expr n}
    (h : (isTotalSmooth left && isTotalSmooth right) = true) :
    isTotalSmooth left = true ∧ isTotalSmooth right = true := by
  cases hl : isTotalSmooth left <;> cases hr : isTotalSmooth right <;> simp_all

theorem contDiff_eval {n : ℕ} (expression : Expr n)
    (h : isTotalSmooth expression = true := by decide) :
    ContDiff ℝ ⊤ (eval expression) := by
  induction expression with
  | const value =>
      simp only [eval]; fun_prop
  | pi =>
      simp only [eval]; fun_prop
  | var index =>
      simp only [eval]; fun_prop
  | add left right ihLeft ihRight =>
      obtain ⟨hl, hr⟩ := totalSmooth_and (by simpa [isTotalSmooth] using h)
      simpa [eval] using (ihLeft hl).add (ihRight hr)
  | sub left right ihLeft ihRight =>
      obtain ⟨hl, hr⟩ := totalSmooth_and (by simpa [isTotalSmooth] using h)
      simpa [eval] using (ihLeft hl).sub (ihRight hr)
  | mul left right ihLeft ihRight =>
      obtain ⟨hl, hr⟩ := totalSmooth_and (by simpa [isTotalSmooth] using h)
      simpa [eval] using (ihLeft hl).mul (ihRight hr)
  | div left right ihLeft ihRight =>
      simp [isTotalSmooth] at h
  | neg arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      simpa [eval] using (ih harg).neg
  | pow base exponent ih =>
      have hbase : isTotalSmooth base = true := by simpa [isTotalSmooth] using h
      simpa [eval] using (ih hbase).pow exponent
  | sin arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      simpa [eval, Function.comp_def] using Real.contDiff_sin.comp (ih harg)
  | cos arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      simpa [eval, Function.comp_def] using Real.contDiff_cos.comp (ih harg)
  | exp arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      simpa [eval, Function.comp_def] using Real.contDiff_exp.comp (ih harg)
  | tanh arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      simpa only [eval, Function.comp_def] using contDiff_tanh.comp (ih harg)
  | log arg ih =>
      simp [isTotalSmooth] at h
  | sqrt arg ih =>
      simp [isTotalSmooth] at h
  | atan arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      simpa [eval, Function.comp_def] using Real.contDiff_arctan.comp (ih harg)

theorem differentiable_eval {n : ℕ} (expression : Expr n)
    (h : isTotalSmooth expression = true := by decide) :
    Differentiable ℝ (eval expression) :=
  (contDiff_eval expression h).differentiable (by simp)

theorem hasDerivAt_coordinate {n : ℕ} (expression : Expr n)
    (coordinate : Fin n) (x : Fin n → ℝ)
    (h : isTotalSmooth expression = true := by decide) :
    RealHasDerivAt (fun value => eval expression (Function.update x coordinate value))
      (eval (symbolicDeriv expression coordinate) x) (x coordinate) := by
  have update_eq : Function.update x coordinate (x coordinate) = x := by
    funext index
    by_cases h : index = coordinate
    · subst index
      simp
    · simp [Function.update_of_ne h]
  induction expression with
  | const value =>
      simpa [eval, symbolicDeriv] using hasDerivAt_const (x coordinate) (value : ℝ)
  | pi =>
      simpa [eval, symbolicDeriv] using hasDerivAt_const (x coordinate) Real.pi
  | var index =>
      by_cases hindex : index = coordinate
      · subst index
        convert hasDerivAt_id (x coordinate) using 1
        · ext value
          simp [eval]
        · simp [eval, symbolicDeriv]
      · simpa [eval, symbolicDeriv, hindex, Function.update_of_ne hindex] using
          hasDerivAt_const (x coordinate) (x index)
  | add left right ihLeft ihRight =>
      obtain ⟨hl, hr⟩ := totalSmooth_and (by simpa [isTotalSmooth] using h)
      convert (ihLeft hl).add (ihRight hr) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | sub left right ihLeft ihRight =>
      obtain ⟨hl, hr⟩ := totalSmooth_and (by simpa [isTotalSmooth] using h)
      convert (ihLeft hl).sub (ihRight hr) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | mul left right ihLeft ihRight =>
      obtain ⟨hl, hr⟩ := totalSmooth_and (by simpa [isTotalSmooth] using h)
      convert (ihLeft hl).mul (ihRight hr) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | div left right ihLeft ihRight =>
      simp [isTotalSmooth] at h
  | neg arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      convert (ih harg).neg using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | pow base exponent ih =>
      have hbase : isTotalSmooth base = true := by simpa [isTotalSmooth] using h
      convert (ih hbase).pow exponent using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv, mul_assoc]
  | sin arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      have outer := Real.hasDerivAt_sin
        (eval arg (Function.update x coordinate (x coordinate)))
      convert outer.comp (x coordinate) (ih harg) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | cos arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      have outer := Real.hasDerivAt_cos
        (eval arg (Function.update x coordinate (x coordinate)))
      convert outer.comp (x coordinate) (ih harg) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | exp arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      have outer := Real.hasDerivAt_exp
        (eval arg (Function.update x coordinate (x coordinate)))
      convert outer.comp (x coordinate) (ih harg) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | tanh arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      have outer : RealHasDerivAt Real.tanh (1 - Real.tanh (eval arg x) ^ 2)
          (eval arg x) := by
        have quotient := (Real.hasDerivAt_sinh (eval arg x)).div
          (Real.hasDerivAt_cosh (eval arg x))
          (ne_of_gt (Real.cosh_pos (eval arg x)))
        have derivative_eq :
            (Real.cosh (eval arg x) * Real.cosh (eval arg x) -
                Real.sinh (eval arg x) * Real.sinh (eval arg x)) /
                Real.cosh (eval arg x) ^ 2 =
              1 - Real.tanh (eval arg x) ^ 2 := by
          rw [Real.tanh_eq_sinh_div_cosh]
          field_simp
        rw [derivative_eq] at quotient
        have function_eq : Real.tanh = Real.sinh / Real.cosh := by
          funext value
          simpa only [Pi.div_apply] using Real.tanh_eq_sinh_div_cosh value
        rw [function_eq] at quotient ⊢
        exact quotient
      have outer' : RealHasDerivAt Real.tanh
          (1 - Real.tanh (eval arg (Function.update x coordinate (x coordinate))) ^ 2)
          (eval arg (Function.update x coordinate (x coordinate))) := by
        simpa only [update_eq] using outer
      convert outer'.comp (x coordinate) (ih harg) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv]
  | log arg ih =>
      simp [isTotalSmooth] at h
  | sqrt arg ih =>
      simp [isTotalSmooth] at h
  | atan arg ih =>
      have harg : isTotalSmooth arg = true := by simpa [isTotalSmooth] using h
      have outer := Real.hasDerivAt_arctan
        (eval arg (Function.update x coordinate (x coordinate)))
      convert outer.comp (x coordinate) (ih harg) using 1
      · ext value
        rfl
      · simp [eval, symbolicDeriv, div_eq_inv_mul]

end LeanBarrier.DSL
