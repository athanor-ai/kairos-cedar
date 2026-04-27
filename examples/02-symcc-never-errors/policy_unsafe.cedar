// Same policy as policy.cedar but adds an unguarded reference to
// `principal.name`. Since `name` is declared optional in the schema,
// any request with a `User` lacking `name` will hit a runtime error
// when this policy evaluates. cedar symcc never-errors should find
// the counterexample.
permit (
  principal,
  action == Action::"read",
  resource
)
when {
  resource.owner == principal && principal.name == "alice"
};
