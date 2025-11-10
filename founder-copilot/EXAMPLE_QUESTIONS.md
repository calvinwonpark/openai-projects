# Example Questions for Multi-Assistant System

This guide provides example questions to test the routing system and see how different assistants respond.

## Tech Advisor Questions

### Architecture & System Design
- "How should I design my API for scalability?"
- "Should I start with a monolithic or microservices architecture?"
- "What's the best database pattern for a high-traffic application?"
- "How do I implement caching in my application?"
- "What are the trade-offs between REST and GraphQL APIs?"

### AI/ML & Product Patterns
- "How do I deploy an ML model to production?"
- "What's the best way to implement RAG (Retrieval-Augmented Generation)?"
- "How should I structure prompts for an LLM application?"
- "What's the difference between fine-tuning and prompt engineering?"
- "How do I monitor ML model performance in production?"

### Infrastructure & DevOps
- "What's the best deployment strategy for zero downtime?"
- "How do I set up CI/CD for my startup?"
- "Should I use containers or serverless for my application?"
- "How do I implement feature flags?"
- "What monitoring tools should I use for my application?"

### Security
- "How do I secure my API endpoints?"
- "What are the most common security vulnerabilities I should watch for?"
- "How should I handle user authentication and authorization?"
- "What's the best way to encrypt sensitive data?"
- "How do I prevent SQL injection attacks?"

## Marketing Advisor Questions

### Growth & Acquisition
- "What are the best growth tactics for a B2B SaaS startup?"
- "How do I acquire my first 100 customers?"
- "What's the difference between paid and organic growth channels?"
- "How do I set up a referral program?"
- "What's the best way to do content marketing?"

### Launch Strategy
- "How should I launch my product?"
- "What should I include in my product launch plan?"
- "How do I get featured on Product Hunt?"
- "What's the best way to build a waitlist before launch?"
- "How do I create buzz before my product launch?"

### Copywriting & Messaging
- "How do I write a compelling value proposition?"
- "What makes a good landing page headline?"
- "How do I write effective email subject lines?"
- "What's the best way to write product descriptions?"
- "How do I create copy that converts?"

### Customer Acquisition
- "What's the best customer acquisition channel for my startup?"
- "How do I calculate customer acquisition cost (CAC)?"
- "What's the difference between inbound and outbound marketing?"
- "How do I set up a content marketing funnel?"
- "What's the best way to do social media marketing?"

## Investor Advisor Questions

### Fundraising
- "How much should I raise in my seed round?"
- "When is the right time to start fundraising?"
- "What should I include in my pitch deck?"
- "How do I find investors for my startup?"
- "What's the typical fundraising timeline?"

### Pitch Deck & Presentation
- "What's the standard pitch deck structure?"
- "How long should my pitch presentation be?"
- "What metrics should I include in my pitch deck?"
- "How do I present my financial projections?"
- "What's the best way to practice my pitch?"

### KPIs & Metrics
- "What KPIs should I track for my startup?"
- "How do I calculate burn rate and runway?"
- "What's a good LTV:CAC ratio?"
- "What metrics do investors care about most?"
- "How do I measure product-market fit?"

### Financials & Valuation
- "How do I value my startup for fundraising?"
- "What's the difference between pre-money and post-money valuation?"
- "How do I create financial projections?"
- "What unit economics should I track?"
- "How do I calculate my runway?"

## Ambiguous Questions (Test Routing Logic)

### Low Confidence / Parallel Ensemble
These questions might trigger parallel ensemble (confidence < 0.5 or margin < 0.15):
- "How do I build a successful startup?" (too broad)
- "What should I focus on first?" (unclear context)
- "How do I grow my business?" (could be marketing or investor)
- "What tools should I use?" (could be tech or marketing)
- "How do I measure success?" (could be investor or marketing)

### Consult-Then-Decide (Moderate Confidence)
These might trigger consult-then-decide (0.5 ≤ confidence < 0.8):
- "How do I create a pitch deck for my tech product?" → InvestorAdvisor answers, TechAdvisor critiques
- "What marketing strategy should I use for my SaaS launch?" → MarketingAdvisor answers, InvestorAdvisor critiques
- "How do I build a scalable product and market it?" → TechAdvisor answers, MarketingAdvisor critiques
- "What metrics should I track for my growth strategy?" → InvestorAdvisor answers, MarketingAdvisor critiques
- "How do I secure my API and communicate it to investors?" → TechAdvisor answers, InvestorAdvisor critiques

**Note**: In consult-then-decide, the reviewer provides a "Devil's Advocate" critique of the primary response, focusing on risks, gaps, alternative perspectives, and potential pitfalls.

### High-Risk Questions (Auto Consult-Then-Decide)
These contain high-risk keywords and will trigger consult-then-decide:
- "How do I structure my fundraising pitch?" → InvestorAdvisor answers, MarketingAdvisor critiques
- "What should I include in my investor deck?" → InvestorAdvisor answers, MarketingAdvisor critiques
- "How do I value my company for investors?" → InvestorAdvisor answers, TechAdvisor critiques
- "What legal considerations are there for fundraising?" → InvestorAdvisor answers, reviewer critiques
- "How do I negotiate a term sheet?" → InvestorAdvisor answers, reviewer critiques

## Questions That Test Scope Enforcement

### Tech Advisor (Should Defer)
- "How do I raise money for my startup?" → Should defer to InvestorAdvisor
- "What marketing channels should I use?" → Should defer to MarketingAdvisor
- "How do I create a pitch deck?" → Should defer to InvestorAdvisor

### Marketing Advisor (Should Defer)
- "How do I design a scalable architecture?" → Should defer to TechAdvisor
- "What's my company worth?" → Should defer to InvestorAdvisor
- "How do I deploy my ML model?" → Should defer to TechAdvisor

### Investor Advisor (Should Defer)
- "How do I implement microservices?" → Should defer to TechAdvisor
- "What's the best growth hack?" → Should defer to MarketingAdvisor
- "How do I optimize my database?" → Should defer to TechAdvisor

## Questions That Test File Upload + Code Interpreter

### Investor Advisor (with CSV upload)
- "Here's my financial data (CSV) - calculate my burn rate and runway"
- "Analyze this KPI tracker (CSV) - show me which metrics are behind target"
- "Visualize my revenue growth from this data (CSV)"
- "Calculate my CAC:LTV ratio from this customer data (CSV)"

### Tech Advisor (with code/data files)
- "Review this API design document - what improvements would you suggest?"
- "Analyze this architecture diagram - is this scalable?"
- "Here's my database schema - what optimization opportunities do you see?"

## Questions That Test Knowledge Base Retrieval

### Should Retrieve from Knowledge Base
- "What does 'do things that don't scale' mean?" (from yc_do_things_dont_scale.md)
- "What should I include in my pre-seed pitch deck?" (from preseed_checklist.md)
- "What are the key fundraising metrics?" (from kpi_definitions.md)
- "How do I write a good headline?" (from copywriting_tips.md)
- "What's the difference between monolithic and microservices?" (from architecture_patterns.md)

## Testing Routing Strategies

### Test Winner-Take-All (High Confidence)
- Clear, domain-specific questions:
  - "How do I implement Redis caching?" → Tech (high confidence)
  - "What's a good email subject line?" → Marketing (high confidence)
  - "How do I calculate my runway?" → Investor (high confidence)

### Test Consult-Then-Decide
- Moderate confidence or high-risk:
  - "How do I create a pitch deck for my tech startup?" → InvestorAdvisor answers, MarketingAdvisor critiques (Devil's Advocate)
  - "What marketing metrics should I track for fundraising?" → MarketingAdvisor answers, InvestorAdvisor critiques
  - "How do I build a secure API for my product?" → TechAdvisor answers, InvestorAdvisor critiques (if security is high-risk)
  
**Expected Behavior**: Primary assistant answers the question, then reviewer assistant critiques the response with risks, gaps, and alternative perspectives.

### Test Parallel Ensemble
- Low confidence or ambiguous:
  - "How do I grow my startup?" → Marketing + Investor perspectives
  - "What should I focus on?" → Multiple perspectives
  - "How do I build a successful product?" → Tech + Marketing perspectives

### Test Clarifying Question
- Too vague, both assistants retrieve nothing:
  - "Help me" (too vague)
  - "What should I do?" (no context)
  - "Tell me about startups" (too broad)

## Pro Tips for Testing

1. **Start with clear questions** - Test winner-take-all first
2. **Try ambiguous questions** - See how routing handles uncertainty
3. **Test scope enforcement** - Ask each assistant out-of-scope questions
4. **Upload files** - Test code_interpreter with CSV/data files
5. **Check responses** - Verify assistants defer appropriately
6. **Look at routing info** - Check the `routing` field in API responses
7. **Test ensemble responses** - See how multiple perspectives are composed

## Expected Behaviors

### Winner-Take-All
- Single assistant responds
- Clear, confident answer
- Routing confidence ≥ 0.8

### Consult-Then-Decide
- Primary assistant answers the question
- Reviewer assistant critiques the primary response (Devil's Advocate)
- Response format: "Response" + "Critique (Devil's Advocate)"
- Routing confidence 0.5-0.8 or high-risk flag
- Reviewer focuses on: risks, gaps, alternative perspectives, missing factors, potential pitfalls

### Parallel Ensemble
- Two assistants answer the original question independently
- Both perspectives presented equally
- Response format: "Perspective" + "Perspective"
- Routing confidence < 0.5 or margin < 0.15
- No critique involved - both are independent answers

### Clarifying Question
- System asks for clarification
- Both assistants retrieved nothing
- Helpful prompts to refine question

