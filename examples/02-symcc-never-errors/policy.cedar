// Owner-may-read. The principal's name attribute is optional;
// this policy never references it, so the policy never errors.
permit (
  principal,
  action == Action::"read",
  resource
)
when {
  resource.owner == principal
};
