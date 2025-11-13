# How the Founder Copilot System Works

This document explains the complete architecture and flow of the Founder Copilot multi-assistant system with product cards and data analysis flows.

## 🏗️ System Architecture Overview

The system has **three specialized AI assistants**, each with their own knowledge base:

1. **TechAdvisor** - Technical architecture, AI/ML patterns, system design
2. **MarketingAdvisor** - Launch strategy, growth tactics, copywriting
3. **InvestorAdvisor** - Fundraising, KPIs, pitch decks, financial analysis

Each assistant has:
- **Separate vector store** (isolated knowledge base)
- **Domain-specific instructions** (scope enforcement)
- **Specific tools** (e.g., `code_interpreter` for InvestorAdvisor and TechAdvisor)

## 🔄 Complete Request Flow

### Step 1: User Sends Message

When a user sends a message (with or without files), the system:

1. **Extracts session ID** (based on IP address for now)
2. **Uploads files** (if any) to OpenAI and gets file IDs
3. **Routes to appropriate flow** based on message content

### Step 2: Flow Detection

The system first checks: **Is this a data analysis flow?**

**Data Analysis Flow Detection:**
- User uploaded files (CSV, Excel, etc.) **OR**
- Message contains analysis keywords ("visualize", "chart", "analyze", "kpi", "stats") **AND** data references ("Q1", "progress", "targets", "best", "worst")

**If YES → Data Analysis Flow** (see below)
**If NO → Normal Routing Flow** (see below)

---

## 📊 Data Analysis Flow (Shared Thread)

**Purpose:** Maintain file context across multiple questions about the same data.

### How It Works:

1. **Shared Analysis Thread**
   - Each session gets **one shared analysis thread** (`SESSION_ANALYSIS_THREAD`)
   - This thread persists across all data analysis questions
   - Files are tracked in `SESSION_ANALYSIS_FILES` per session

2. **File Persistence**
   - When user uploads a CSV: file is tracked in `SESSION_ANALYSIS_FILES[session_id]`
   - When user asks follow-up: previous files are **automatically re-attached**
   - Example:
     - Turn 1: "visualize Q1 progress" (with CSV) → CSV tracked
     - Turn 2: "what's the best stat?" → CSV automatically re-attached

3. **Assistant Selection**
   - Uses **InvestorAdvisor** (has `code_interpreter` for data analysis)
   - Bypasses normal routing for data flows

4. **Response**
   - Streams response from the shared analysis thread
   - Charts/images generated are tracked for future reference

### Example Flow:

```
User: "Here's kpi_tracker.csv — visualize our Q1 progress vs targets" [uploads CSV]
  ↓
System detects: is_data_flow = True (has file + "visualize" + "Q1")
  ↓
Creates/gets shared analysis thread for session
  ↓
Uploads CSV, tracks in SESSION_ANALYSIS_FILES[session_id]
  ↓
Routes to InvestorAdvisor (code_interpreter enabled)
  ↓
Assistant generates chart, responds
  ↓
Chart file ID tracked in SESSION_PRODUCED_FILES

User: "in the Q1 progress vs targets, what is the best and worst stat"
  ↓
System detects: is_data_flow = True (references "Q1", "progress", "targets", "best", "worst")
  ↓
Gets same shared analysis thread
  ↓
Retrieves CSV from SESSION_ANALYSIS_FILES[session_id]
  ↓
Automatically re-attaches CSV to new message
  ↓
Assistant can access the data and answer correctly ✅
```

---

## 🎯 Normal Routing Flow (Multi-Assistant)

When it's **not** a data analysis flow, the system uses multi-assistant routing.

### Step 1: Product Card Auto-Extraction

**Before routing**, the system tries to extract product information:

```python
auto_created_card = auto_create_or_update_product_card(user_msg, session_id)
```

- Uses OpenAI to detect product info in the message
- Keywords: "my product", "we're building", "target audience", "MVP", etc.
- If found, creates/updates product card automatically
- Sets it as active for the session

**Product Card Structure:**
```json
{
  "product_id": "acme-inbox-copilot",
  "name": "Acme Inbox Copilot",
  "description": "AI email triage for SMB founders",
  "target_audience": "solo founders",
  "problem_uvp": "prioritizes investor emails",
  "key_features": ["AI triage", "Priority detection"],
  "stage": "MVP",
  "constraints": {"budget": "$10K", "timeline": "3 months"},
  "files": ["file_id_1", "file_id_2"],
  "version": 1,
  "updated_at": "2024-01-15T10:30:00Z"
}
```

### Step 2: Query Routing

**Hybrid Router** (heuristic + AI classifier):

1. **Heuristic Classification** (fast, keyword-based)
   - Matches keywords against domain lists
   - Calculates confidence based on keyword dominance
   - Used for clear-cut cases

2. **Classifier Classification** (if ambiguous)
   - If heuristic confidence < 0.6, uses OpenAI classifier
   - Returns structured JSON with label, confidence, top2_label, margin

**Router Output:**
```python
{
  "label": "tech" | "marketing" | "investor",
  "confidence": 0.0-1.0,
  "top2_label": "tech" | "marketing" | "investor",
  "margin": 0.0-1.0,  # Difference between top and second
  "is_high_risk": bool
}
```

### Step 3: Deictic Reference Detection

**Detects context-dependent language:**
- Pronouns: "this", "that", "it", "they"
- References: "above", "below", "the product", "my app"
- Implicit references: "the chart", "that KPI", "our product"

**If deictic references found:**
- System needs product card context to understand what user means
- Triggers message rewriting (see below)

### Step 4: Clarification Check

**If confidence < 0.6 AND no product card:**
- If multiple products exist → ask user to select
- If no products → proceed (or could ask to create one)

### Step 5: Message Rewriting (Product Card Injection)

**When deictic references detected AND product card exists:**

The system **rewrites the user message** to include product context:

**Original message:**
```
"Now help me market this product. Focus on a 2-week launch plan."
```

**Rewritten message:**
```
Product: "Acme Inbox Copilot" — AI email triage for SMB founders.
Audience: solo founders.
UVP: prioritizes investor emails and action items.
Stage: MVP.
Constraints: <$200/mo CAC.

User asks: Now help me market this product. Focus on a 2-week launch plan.
```

**Also attaches:**
- Files from product card (`product_card.files`)
- Files produced in previous turns (`SESSION_PRODUCED_FILES`)

### Step 6: Routing Strategy Selection

Based on confidence and risk, selects one of three strategies:

#### Strategy 1: Winner-Take-All (confidence ≥ 0.8)

**When:** High confidence in primary assistant

**Action:**
- Route to primary assistant only
- Use assistant's dedicated thread (`THREADS_BY_ASSISTANT[label]`)
- Stream response immediately

**Example:** "How do I design a scalable API?" → TechAdvisor only

#### Strategy 2: Consult-Then-Decide (0.5 ≤ confidence < 0.8 OR high-risk)

**When:** Moderate confidence OR high-risk query (fundraising, legal, etc.)

**Action:**
1. **Primary assistant** answers the original question
2. **Reviewer assistant** provides "Devil's Advocate" critique
   - Receives primary's response as context
   - Asked to identify risks, gaps, alternative perspectives
   - Focuses on adding value, not just criticizing

**Example:** "How do I create a pitch deck?" 
- InvestorAdvisor provides deck structure
- MarketingAdvisor critiques from marketing perspective

#### Strategy 3: Parallel Ensemble (confidence < 0.5 OR margin < 0.15)

**When:** Low confidence OR labels are very close

**Action:**
- Both assistants answer **independently**
- Both perspectives presented equally
- User gets two different viewpoints

**Example:** "What tools should I use?" (could be tech or marketing)
- TechAdvisor provides technical tool recommendations
- MarketingAdvisor provides marketing tool recommendations

### Step 7: Thread Management

**Per-Assistant Threads:**
- Each assistant has its own thread (`THREADS_BY_ASSISTANT[label]`)
- Maintains conversation history per domain
- Files are tracked per thread (`THREAD_UPLOADED_FILES[thread_id]`)

**File Persistence in Normal Flow:**
- If user references data but no new files uploaded
- System checks if previous files exist for that thread
- Automatically re-attaches them

### Step 8: Response Generation

**Streaming Response:**
- Uses OpenAI's streaming API
- Yields chunks as they arrive
- Frontend updates in real-time

**Response Structure:**
```json
{
  "type": "text_delta" | "done" | "phase_transition",
  "accumulated": "text so far...",
  "answer": "final answer",
  "bullets": ["bullet 1", "bullet 2"],
  "sources": [{"file_id": "...", "quote": "..."}],
  "images": [{"file_id": "...", "data_url": "..."}],
  "routing": {"strategy": "...", "label": "..."},
  "phase": "primary" | "reviewer"
}
```

---

## 🔑 Key Concepts

### 1. Session Management

**Session ID:** Based on IP address (could use session cookie)
- Tracks active product card per session
- Tracks files produced across turns
- Maintains shared analysis thread per session

### 2. Product Card System

**Purpose:** Provide context for deictic references ("this product", "my app")

**Auto-Extraction:**
- Automatically detects product info in messages
- Creates/updates product cards on-the-fly
- No manual creation needed (but can be done via API)

**Message Rewriting:**
- When deictic references detected
- Prepends product card to user message
- Ensures assistant understands context

### 3. File Persistence

**Three Types of File Tracking:**

1. **`SESSION_ANALYSIS_FILES`** - Files in shared analysis thread (data flows)
2. **`THREAD_UPLOADED_FILES`** - Files per assistant thread (normal routing)
3. **`SESSION_PRODUCED_FILES`** - Files produced by assistants (charts, images)

**Automatic Re-attachment:**
- Data analysis flows: files persist in shared thread
- Normal flows: files persist per assistant thread
- Follow-up questions: files automatically re-attached

### 4. Data Isolation

**Per-Assistant Vector Stores:**
- Each assistant has separate knowledge base
- Prevents irrelevant retrievals
- Keeps citations meaningful

**Per-Assistant Threads:**
- Separate conversation history per domain
- Maintains context within each domain
- Prevents cross-contamination

### 5. Scope Enforcement

**System Instructions:**
- Each assistant has domain-specific instructions
- Told when to defer to other assistants
- Example: "If asked about fundraising and you are MarketingAdvisor, briefly defer to InvestorAdvisor."

---

## 📝 Example Scenarios

### Scenario 1: Data Analysis Flow

```
User: "Here's kpi_tracker.csv — visualize our Q1 progress vs targets" [uploads CSV]
  ↓
Detected as data analysis flow
  ↓
Uses shared analysis thread (InvestorAdvisor)
  ↓
CSV tracked in SESSION_ANALYSIS_FILES
  ↓
Assistant generates chart, responds
  ↓
User: "what's the best and worst stat?"
  ↓
Detected as data analysis flow (references "best", "worst", "Q1")
  ↓
Same shared analysis thread
  ↓
CSV automatically re-attached
  ↓
Assistant can access data ✅
```

### Scenario 2: Product Card + Deictic Reference

```
User: "I'm building an AI email copilot for solo founders. It prioritizes investor emails."
  ↓
Product card auto-extracted and created
  ↓
Set as active for session
  ↓
User: "Now help me market this product"
  ↓
Deictic reference detected ("this product")
  ↓
Product card retrieved
  ↓
Message rewritten with product context
  ↓
Routes to MarketingAdvisor with full context
  ↓
MarketingAdvisor understands what "this product" means ✅
```

### Scenario 3: Consult-Then-Decide

```
User: "How do I create a pitch deck for my tech product?"
  ↓
Router: label="investor", confidence=0.7, top2="marketing"
  ↓
Strategy: Consult-then-decide (0.5 ≤ 0.7 < 0.8)
  ↓
InvestorAdvisor provides deck structure
  ↓
MarketingAdvisor critiques from marketing perspective
  ↓
User gets comprehensive answer + critique ✅
```

### Scenario 4: Parallel Ensemble

```
User: "What tools should I use?"
  ↓
Router: label="tech", confidence=0.4, top2="marketing", margin=0.1
  ↓
Strategy: Parallel ensemble (confidence < 0.5)
  ↓
TechAdvisor provides technical tools
  ↓
MarketingAdvisor provides marketing tools
  ↓
User gets both perspectives ✅
```

---

## 🎨 State Management

**In-Memory Storage (session-based):**

```python
THREADS = {}  # Legacy single thread
THREADS_BY_ASSISTANT = {}  # Per-assistant threads
SESSION_PRODUCT_IDS = {}  # Active product per session
SESSION_PRODUCED_FILES = {}  # Files produced per session
THREAD_UPLOADED_FILES = {}  # Files per thread
SESSION_ANALYSIS_THREAD = {}  # Shared analysis thread per session
SESSION_ANALYSIS_FILES = {}  # Files in analysis thread per session
```

**Product Cards:**
- Stored in `PRODUCT_CARDS` dict (in-memory)
- Versioned (`PRODUCT_CARD_VERSION`)
- Could be moved to Redis/DB for persistence

---

## 🔄 Complete Flow Diagram

```
User Message (+ optional files)
         ↓
    Extract Session ID
         ↓
    Upload Files (if any)
         ↓
    ┌─────────────────┐
    │ Data Analysis?  │
    └─────────────────┘
         ↓
    YES → Shared Analysis Thread
         │
         ├─→ Get/Create Analysis Thread
         ├─→ Track Files in SESSION_ANALYSIS_FILES
         ├─→ Use InvestorAdvisor (code_interpreter)
         └─→ Stream Response
         
    NO → Normal Routing Flow
         │
         ├─→ Auto-extract Product Card
         ├─→ Route Query (heuristic + classifier)
         ├─→ Detect Deictic References
         ├─→ Check Clarification Needed
         ├─→ Rewrite Message (if deictic + product card)
         ├─→ Select Routing Strategy
         │   ├─→ Winner-take-all
         │   ├─→ Consult-then-decide
         │   └─→ Parallel ensemble
         ├─→ Get/Create Assistant Thread
         ├─→ Track Files in THREAD_UPLOADED_FILES
         └─→ Stream Response(s)
```

---

## 🛠️ Tools & Capabilities

**TechAdvisor:**
- `file_search` - Search technical knowledge base
- `code_interpreter` - Run Python code for calculations

**MarketingAdvisor:**
- `file_search` - Search marketing knowledge base

**InvestorAdvisor:**
- `file_search` - Search investor/fundraising knowledge base
- `code_interpreter` - Run Python code for data analysis, KPIs, visualizations

---

## 🎯 Key Design Decisions

1. **Shared Analysis Thread for Data Flows**
   - Solves file persistence problem
   - Maintains context across data analysis questions
   - Separate from per-assistant threads

2. **Product Card Auto-Extraction**
   - No manual creation needed
   - Extracts from natural conversation
   - Updates automatically when user provides new info

3. **Message Rewriting with Product Card**
   - Solves deictic reference problem
   - Makes messages self-contained
   - Ensures assistants understand context

4. **Per-Assistant Threads**
   - Maintains domain-specific context
   - Prevents cross-contamination
   - Enables specialized knowledge bases

5. **Hybrid Routing**
   - Fast heuristic for clear cases
   - AI classifier for ambiguous cases
   - Balances speed and accuracy

---

This architecture enables the system to:
- ✅ Handle data analysis with file persistence
- ✅ Understand context-dependent references
- ✅ Route queries to specialized assistants
- ✅ Provide multiple perspectives when needed
- ✅ Maintain conversation context per domain
- ✅ Auto-extract and manage product information

