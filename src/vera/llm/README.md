Provider adapter. Temperature 0, seeded, deadline-bounded, circuit-broken.
Every call site MUST have a non-LLM fallback: a timeout costs -1, a malformed
response costs -2, and a dead provider must degrade to a good templated message.
