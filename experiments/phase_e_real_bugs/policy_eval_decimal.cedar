// Equality-on-decimal: does '1.2300' == '1.23'?
permit(principal, action, resource)
when {
  resource.balance == decimal("1.2300")
};
