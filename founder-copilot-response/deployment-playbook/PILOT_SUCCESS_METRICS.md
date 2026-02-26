# Pilot Success Metrics

Use these metrics for a 4-8 week pilot of routed workflow automation.

## Primary Metrics
- **p95 Latency (ms)**  
  - Definition: end-to-end `/chat_text` response time at p95.
  - Target: stable under agreed SLO by tenant tier.

- **Cost per Request (USD)**  
  - Definition: average and p95 from token usage-based estimate.
  - Target: stays within pilot budget envelope.

- **Task Success Rate (%)**  
  - Definition: share of requests that complete intended workflow output without manual rewrite.
  - Target: improve versus baseline human-only process.

- **Hallucination Rate (%)**  
  - Definition: sampled responses with unverifiable or incorrect claims.
  - Target: downward trend week-over-week with guardrail tuning.

- **Refusal Accuracy (%)**  
  - Definition: correct refuse/allow decisions on safety policy test set.
  - Target: high precision for refusal and low false refusal on valid business tasks.

## Supporting Breakdowns
- By route (`tech`, `marketing`, `investor`)
- By strategy (`winner_take_all`, `consult_then_decide`, `parallel_ensemble`, `data_analysis_flow`)
- By tenant (to verify isolation and fairness)

## Weekly Review Questions
- Which route has the highest cost or error concentration?
- Are reviewer-call failures causing fallback spikes?
- Which tenant cohorts need custom knowledge/tool configuration?
