// Policy uses an action UID with namespace "Foo" rather than "Action".
// Rust's cedar-policy-core/src/parser/cst_to_ast.rs::action_constraint_contains_only_action_types
// (https://github.com/cedar-policy/cedar/blob/main/cedar-policy-core/src/parser/cst_to_ast.rs#L717)
// rejects any action UID whose last namespace component is not exactly "Action".
permit (
    principal,
    action == Foo::"viewAll",
    resource
);
