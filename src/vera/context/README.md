Versioned context store + diff engine.
  store.py   (scope, context_id) -> {version, payload}; higher version replaces atomically
  diff.py    version-bump diffing -> "what is NEW since last version" (powers Phase-3 adaptation)
  index.py   derived indices: merchant->category, merchant->customers, active-offers-only view
