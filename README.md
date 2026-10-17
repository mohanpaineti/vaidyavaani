# VaidyaVaani

A real-time two-way voice interpreter for the consultation room: any patient, any doctor, each
heard in their own language, with every dose read back safely.

**New here, or resuming on another machine or account? Start with
[docs/00-HANDOVER.md](docs/00-HANDOVER.md).** It covers current state, what blocks progress, every
decision and why, and what we believed that turned out to be wrong.

| Doc | What it answers |
|---|---|
| [00-HANDOVER.md](docs/00-HANDOVER.md) | Read first. State, blockers, decision log, corrections, how to resume |
| [01-product-plan.md](docs/01-product-plan.md) | Product, flow, features, edge cases, demo script, judge Q&A |
| [02-technical-architecture.md](docs/02-technical-architecture.md) | Architecture, model routing, the safety gate, cost, risks |
| [03-p0-findings.md](docs/03-p0-findings.md) | The authority on anything SLNG- or unmute-specific |
| [04-interfaces.md](docs/04-interfaces.md) | The binding contract between components |

```bash
./scripts/dev-all.sh   # never start the services by hand — see 00-HANDOVER §6
```
