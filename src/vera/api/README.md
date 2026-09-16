Endpoint layer only. Five endpoints, thin: parse -> delegate -> serialize.
Every handler MUST return a schema-valid response within its deadline budget.
No business logic here.
  POST /v1/context   idempotent on (scope, context_id, version)
  POST /v1/tick      <=20 actions, hard deadline, may return []
  POST /v1/reply     send | wait | end
  GET  /v1/healthz   reports real contexts_loaded counts (255-context warmup gate)
  GET  /v1/metadata  bot identity
