# Multi-Assistant Routing System

This document describes the multi-assistant routing system that intelligently routes queries to specialized assistants.

## Overview

The system uses three specialized assistants, each with their own vector store and knowledge base:

1. **TechAdvisor** - Technical architecture, AI/ML product patterns, system design, infrastructure
2. **MarketingAdvisor** - Launch strategy, growth tactics, copywriting, messaging, customer acquisition
3. **InvestorAdvisor** - Fundraising, pitch decks, KPIs, financial metrics, valuation

## Router Architecture

### Hybrid Routing Approach

The router uses a **hybrid approach**: heuristic first, classifier if ambiguous.

1. **Heuristic Classification** (fast, keyword-based)
   - Matches keywords against predefined lists for each domain
   - Calculates confidence based on keyword dominance
   - Used for clear-cut cases

2. **Classifier Classification** (when ambiguous)
   - Uses OpenAI to classify the query when heuristic confidence is low (< 0.6)
   - Returns structured JSON with label, confidence, top2_label, and margin

### Router Output

The router returns:
```python
{
    "label": "tech" | "marketing" | "investor",
    "confidence": 0.0-1.0,
    "top2_label": "tech" | "marketing" | "investor",
    "margin": 0.0-1.0,  # Difference between top and second confidence
    "is_high_risk": bool  # True if query contains high-risk keywords
}
```

## Routing Strategies

Based on confidence and risk level, the system uses three routing strategies:

### 1. Winner-Take-All (confidence ≥ 0.8)

- **When**: High confidence in primary assistant
- **Action**: Route to primary assistant only
- **Use Case**: Clear-cut questions like "How do I design a scalable API?"

### 2. Consult-Then-Decide (0.5 ≤ confidence < 0.8 OR high-risk)

- **When**: Moderate confidence OR query contains high-risk keywords (fundraising, legal, etc.)
- **Action**: 
  1. Run primary assistant first
  2. Run reviewer (top2) assistant
  3. Compose both perspectives
- **Use Case**: "How should I structure my pitch deck?" (high-risk, needs investor + marketing input)

### 3. Parallel Ensemble (confidence < 0.5 OR margin < 0.15)

- **When**: Low confidence OR labels are very close
- **Action**: Run both top-2 assistants in parallel, compose perspectives
- **Use Case**: Ambiguous questions that could benefit from multiple viewpoints

### 4. Clarifying Question (both assistants retrieve nothing)

- **When**: Both assistants in ensemble mode return no grounded content
- **Action**: Ask user to clarify their question
- **Use Case**: Vague or unclear queries

## Data Isolation

### Per-Assistant Vector Stores

Each assistant has its own vector store to:
- Keep knowledge bases separate
- Avoid irrelevant retrievals
- Maintain meaningful citations
- Enable focused expertise

### Directory Structure

```
data/
├── tech/          # Technical documentation, architecture patterns
├── marketing/     # Growth strategies, launch guides, copywriting
└── investor/      # Fundraising guides, KPI templates, financial models
```

## Scope Enforcement

Each assistant has specialized instructions that:
- Define their domain expertise
- Instruct to defer to other assistants for out-of-scope questions
- Maintain focus on their specialty

### Example Instructions

**TechAdvisor**:
- "If asked about fundraising, briefly defer to InvestorAdvisor"
- "For marketing questions, defer to MarketingAdvisor"

**MarketingAdvisor**:
- "If asked about technical architecture, defer to TechAdvisor"
- "If asked about fundraising, defer to InvestorAdvisor"

**InvestorAdvisor**:
- "If asked about technical architecture, defer to TechAdvisor"
- "If asked about marketing (unless related to pitch), defer to MarketingAdvisor"

## Tool Scopes

Different assistants have different tools enabled:

- **TechAdvisor**: `file_search` + `code_interpreter` (for quick technical calculations)
- **MarketingAdvisor**: `file_search` only
- **InvestorAdvisor**: `file_search` + `code_interpreter` (for financial calculations and visualizations)

## Setup

### 1. Create Data Directories

```bash
mkdir -p data/tech data/marketing data/investor
```

### 2. Add Knowledge Base Files

Place relevant files in each directory:
- `data/tech/` - Technical documentation
- `data/marketing/` - Marketing guides
- `data/investor/` - Fundraising and financial resources

### 3. Seed Assistants

```bash
python scripts/seed_multi_assistants.py
```

This will:
- Create three vector stores
- Upload files from each directory
- Create three specialized assistants
- Save IDs to state file

## Usage

The system automatically detects if multi-assistant setup exists:
- If multi-assistant setup is found: Uses routing system
- If not: Falls back to legacy single-assistant mode

### API Response

Multi-assistant responses include a `routing` field with routing information:

```json
{
  "answer": "...",
  "sources": [...],
  "routing": {
    "label": "investor",
    "confidence": 0.85,
    "top2_label": "marketing",
    "margin": 0.3,
    "is_high_risk": true
  }
}
```

### Ensemble Responses

When multiple assistants are consulted, the response is composed:

```
**InvestorAdvisor Perspective:**
[Primary assistant's answer]

**MarketingAdvisor Perspective:**
[Reviewer assistant's answer]
```

## High-Risk Keywords

Queries containing these keywords automatically trigger consult-then-decide:
- fundraising, investor, pitch, deck, valuation, equity
- legal, compliance, contract, agreement, lawsuit

## Thread Management

- Each assistant maintains its own conversation thread
- Threads are stored per assistant label
- Reset endpoint clears all threads

## Benefits

1. **Specialized Expertise**: Each assistant focuses on its domain
2. **Data Isolation**: No cross-contamination between knowledge bases
3. **Intelligent Routing**: Hybrid approach balances speed and accuracy
4. **Risk Management**: High-risk queries get multiple perspectives
5. **Flexible Composition**: Can combine insights from multiple assistants

