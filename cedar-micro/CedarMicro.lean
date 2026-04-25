-- CedarMicro. minimum-viable Cedar-shape type system wired to Palamedes.
--
-- Goal: prove Palamedes's `generator_search` tactic closes on a
-- Cedar-shape `isWellTyped` predicate, as a stepping stone to the full
-- cedar-spec `Cedar.Spec.Expr`. Lives in its own Lake project because
-- palamedes-lean is pinned to Lean 4.24.0 + Mathlib whereas cedar-spec
-- is pinned to 4.29.1 + batteries. they can't coexist in one Lake
-- project today.
--
-- Module layout follows Palamedes/Data/STLC/*.lean, per the PLDI '26
-- paper's Data/ convention. `Ty.lean` + `Expr.lean` carry the
-- companion-functor + recursion-scheme scaffolding each recursive
-- datatype needs; `WellTyped.lean` defines the predicate and the
-- generator.

import CedarMicro.Ty
import CedarMicro.Expr
import CedarMicro.WellTyped
import CedarMicro.GenLLM
import CedarMicro.Soundness
import CedarMicro.Coverage
