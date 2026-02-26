# Use Case Scoring Rubric

Score each candidate use case from 1 (low) to 5 (high).

## 1) Business Value (40%)
- Frequency of workflow
- Time saved per run
- Revenue/risk impact

## 2) Technical Feasibility (35%)
- Data availability for `file_search`
- Tool-call fit (`code_interpreter` needed and reliable)
- Integration complexity (systems, auth, tenancy)

## 3) Risk Profile (25%, inverse)
- Hallucination harm potential
- Compliance/privacy exposure by tenant
- Operational fallback maturity

## Weighted Score
`score = value*0.40 + feasibility*0.35 + (6-risk)*0.25`

- **4.0+**: Strong pilot candidate now
- **3.0-3.9**: Candidate with mitigations
- **<3.0**: Defer; reduce risk or increase data/tool readiness

## Recommended Tie-Breakers
- Shortest time-to-first-value
- Clearest success metric attribution
- Lowest cross-tenant data leakage risk
