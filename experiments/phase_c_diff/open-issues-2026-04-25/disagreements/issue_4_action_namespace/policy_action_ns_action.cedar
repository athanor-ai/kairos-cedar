// Same shape, but with the canonical "Action::" namespace.
// Both Rust and cedar-go should accept this.
permit (
    principal,
    action == Action::"view",
    resource
);
