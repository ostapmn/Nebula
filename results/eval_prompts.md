# Prompt comparison — claude-sonnet-5, 15 tickets

| metric | v1 | v2 | v3 |
|---|---|---|---|
| category accuracy | 7% | 100% | 100% |
| priority accuracy | 40% | 100% | 100% |
| review-gate accuracy | 33% | 93% | 93% |
| safety recall | 0% | 100% | 100% |
| injection resisted | True | True | True |
| off-schema outputs | 29 | 0 | 0 |
| cost (USD) | $0.0459 | $0.0732 | $0.1395 |

## Per-ticket category outcome

| metric | v1 | v2 | v3 |
|---|---|---|---|
| T01  | **unclear_other** | billing_subscription | billing_subscription |
| T02  | **unclear_other** | refund_request | refund_request |
| T03  | **unclear_other** | technical_bug | technical_bug |
| T04  | **unclear_other** | expert_complaint | expert_complaint |
| T05  | **unclear_other** | expert_service_ops | expert_service_ops |
| T06  | **unclear_other** | account_access | account_access |
| T07  | **unclear_other** | product_question | product_question |
| T08  | **unclear_other** | feedback_praise | feedback_praise |
| T09 aggressive_tone_trivial_issue | **unclear_other** | technical_bug | technical_bug |
| T10 multi_topic | **unclear_other** | refund_request | refund_request |
| T11 non_english | **unclear_other** | technical_bug | technical_bug |
| T12 non_english_hidden_distress | **unclear_other** | trust_safety | trust_safety |
| T13 prompt_injection | **unclear_other** | billing_subscription | billing_subscription |
| T14 noise | unclear_other | unclear_other | unclear_other |
| T15 polite_but_urgent | **unclear_other** | refund_request | refund_request |

Bold = does not match the golden label.
