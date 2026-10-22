# Architecture Decision Records

Decision records for Pulse. Numbered, append-only; a superseding ADR points
back and the old one's status changes to Superseded. Context/Decision/
Consequences per Michael Nygard's form.

| ADR | Decision | Status |
|---|---|---|
| 0001 | Plugin boundary: read host state, never change it | Accepted |
| 0002 | Staged validation of the deep LLM judge | Accepted |
| 0003 | Corpus = Pulse-owned hashed snapshots, redacted at write | Accepted |
| 0004 | Run-frozen corpus membership via run manifests | Accepted |
| 0005 | Gate exercises two judge paths: pinned API + in-host lane | Accepted |
| 0006 | Per-signal `unscoreable` abstain verdicts | Accepted |
| 0007 | Judge model = local production model; service lifecycle is user-only | Accepted |
| 0008 | Stratified gate corpus with positives floors | Accepted |
| 0009 | Per-pair per-stratum kappa; min-over-cells gate; CI honesty | Accepted |
| 0010 | Model-derived judge prompt budget replaces the fixed 12k cap | Accepted |
| 0011 | Conversation data is private by default; aggregates only in public | Accepted |
| 0012 | Pair polarity: judge finding=yes <-> detector-present; absent = abstain | Accepted |
| 0013 | Judge budget mechanics: resolution order, /v1/models probe, explicit fallbacks | Accepted |
| 0014 | `pulse agreement` v2 consumes the run manifest; unroll-trace gate path replaced | Accepted |
| 0015 | Tri-state gate verdict; per-cell refusal rules and bootstrap CIs | Accepted |
| 0016 | Judge HTTP request timeout is an explicit operator knob | Accepted |
