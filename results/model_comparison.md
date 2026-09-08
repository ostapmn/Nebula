# Model comparison — prompt v3, 15 tickets

| metric | claude-haiku-4-5 | claude-sonnet-5 | claude-opus-5 |
|---|---|---|---|
| pass rate (all 3 fields) | 87% | 100% | 87% |
| category accuracy | 93% | 100% | 100% |
| priority accuracy | 100% | 100% | 100% |
| review-gate accuracy | 93% | 100% | 87% |
| safety recall | 100% | 100% | 100% |
| injection resisted | True | True | True |
| off-schema outputs | 0 | 0 | 0 |
| API errors | 0 | 0 | 0 |
| latency median (ms) | 4522 | 3906 | 3702 |
| latency p90 (ms) | 5030 | 4750 | 6108 |
| cache hit rate | 0% | 98% | 98% |
| cost per ticket | $0.00336 | $0.00328 | $0.00624 |
| cost per 10k tickets | $33.60 | $32.76 | $62.42 |

## Where each model fails

**claude-haiku-4-5** — 2 failure(s):
- T01 (baseline): gate — expected `billing_subscription`/P2/P3, got `billing_subscription`/P3
- T09 (aggressive_tone_trivial_issue): category — expected `technical_bug`/P3, got `product_question`/P3

**claude-sonnet-5** — no failures.
**claude-opus-5** — 2 failure(s):
- T05 (baseline): gate — expected `expert_service_ops`/P1, got `expert_service_ops`/P1
- T09 (aggressive_tone_trivial_issue): gate — expected `technical_bug`/P3, got `technical_bug`/P3
