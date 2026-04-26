// Equality-on-ip: does ip("127.0.0.1") == ip("127.0.0.1/32")?
permit(principal, action, resource)
when {
  resource.src == ip("127.0.0.1/32")
};
