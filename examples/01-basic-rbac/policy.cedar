// Small hand-crafted RBAC policy set. Three policies exercising
// the three shape classes cedar-policy + cedar-go both implement:
//   allow-by-role   — permit when principal has a specific role
//   deny-conditional — forbid when a context attribute matches
//   allow-scoped    — permit only for resources of a specific type

// 1. Admins may do anything.
@id("allow-admin")
permit(
    principal,
    action,
    resource
) when {
    principal in Role::"admin"
};

// 2. Nobody reads a resource tagged "confidential".
@id("deny-confidential-read")
forbid(
    principal,
    action == Action::"read",
    resource
) when {
    resource has tag && resource.tag == "confidential"
};

// 3. Editors may edit documents they own.
@id("allow-editor-edit-own")
permit(
    principal in Role::"editor",
    action == Action::"edit",
    resource is Document
) when {
    resource.owner == principal
};
