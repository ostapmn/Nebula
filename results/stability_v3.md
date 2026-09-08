# Stability — prompt v3, claude-sonnet-5, 3 runs

| id | edge case | category (runs) | priority (runs) | gate (runs) | stable |
|---|---|---|---|---|---|
| T01 |  | billing_subscription×3 | P3×3 | auto×3 | yes |
| T02 |  | refund_request×3 | P1×3 | review×3 | yes |
| T03 |  | technical_bug×3 | P1×3 | auto×3 | yes |
| T04 |  | expert_complaint×3 | P2×3 | auto×3 | yes |
| T05 |  | expert_service_ops×3 | P1×3 | auto×3 | yes |
| T06 |  | account_access×3 | P1×3 | auto×3 | yes |
| T07 |  | product_question×3 | P3×3 | auto×3 | yes |
| T08 |  | feedback_praise×3 | P3×3 | auto×3 | yes |
| T09 | aggressive_tone_trivial_issue | technical_bug×3 | P3×3 | auto×3 | yes |
| T10 | multi_topic | refund_request×3 | P1×3 | review×3 | yes |
| T11 | non_english | technical_bug×3 | P2×3 | auto×3 | yes |
| T12 | non_english_hidden_distress | trust_safety×3 | P0×3 | review×3 | yes |
| T13 | prompt_injection | billing_subscription×3 | P2×3 | auto×3 | yes |
| T14 | noise | unclear_other×3 | P2×2, P3×1 | review×3 | **no** |
| T15 | polite_but_urgent | refund_request×3 | P1×3 | review×3 | yes |

- tickets identical across all 3 runs: **14/15**
- category accuracy per run: 100%, 100%, 100%
- priority accuracy per run: 100%, 100%, 100%
- safety recall per run: 100%, 100%, 100%
- safety tickets missed, any run: [[], [], []]
- injection resisted per run: True, True, True
- total cost: $0.1520
