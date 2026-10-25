# Herdr AI Team Charter
## Multi-Agent Hierarchical Development System

**Project:** Text RPG (Simple, runnable Python game)  
**Created:** 2026-10-25  
**Team Structure:** 8 agents in herdr (2×4 grid, batch-gateway backend)  
**Goal:** Deliver a **VALID and RUNNABLE** application, verified by PM

---

## 1. TEAM STRUCTURE & ROLES

### **Tier 1: Project Manager (PM)**
- **Pane:** w4:pP
- **Model:** `openai/gpt-oss-120b` (Groq batch)
- **Authority:** Final validation, delivery gate, strategic decisions
- **Responsibility:** 
  - Verify deliverable meets original brief (valid + runnable)
  - Approve/reject completion
  - Escalate tech decisions back to Tech Lead if needed
  - Document final acceptance

### **Tier 2: Tech Lead (Leadership)**
- **Pane:** w4:pQ (📚 Data Engineer role, acts as Tech Lead)
- **Model:** `openai/gpt-oss-20b` (Groq batch)
- **Authority:** Technical decisions, escalation gatekeeper, team coordination
- **Responsibility:**
  - Monitor all 6 dev agents' work
  - Filter escalations to PM (only critical/blocked items)
  - Resolve cross-agent conflicts
  - Unblock technical decisions within scope
  - Daily standup consolidation

### **Tier 3: Development Agents (6)**
- **Panes:** w4:pJ (PM), w4:pN (Frontend), w4:pM (Backend), w4:pK (DevOps), w4:pS (Security), w4:pR (QA)
- **Model:** `openai/gpt-oss-20b` (Groq batch)
- **Authority:** Implementation decisions within their domain
- **Responsibility:**
  - Execute assigned tasks
  - Report blockers immediately
  - Coordinate within specialization
  - Test and validate own work
  - Escalate to Tech Lead when blocked

---

## 2. DECISION AUTHORITY MATRIX

| Decision Type | Owner | Escalates To | Condition |
|---------------|-------|--------------|-----------|
| Code implementation details | Dev Agent | Tech Lead | Cross-team impact or scope ambiguity |
| Architecture & design | Tech Lead | PM | Violates brief or creates debt |
| Testing strategy & coverage | QA | Tech Lead | Missing critical paths |
| Security decisions | Security | Tech Lead | Compliance risk or vulnerability |
| DevOps/deployment | DevOps | Tech Lead | Infrastructure blocker |
| **Final: Deliverable valid + runnable** | **PM** | None | Must approve before delivery |
| Resource allocation | Tech Lead | PM | Task can't complete with current team |
| Timeline/deadline risk | Tech Lead | PM | Slip > 1 hour or scope change needed |
| Scope changes | PM | — | PM alone decides brief adjustments |

---

## 3. ESCALATION RULES

### **Tech Lead → PM** (Only if **all** criteria met)

**ESCALATE IF:**
1. **Blocker** — Task cannot proceed without PM intervention
2. **Cross-team deadlock** — Two agents disagree, Tech Lead can't resolve
3. **Scope change** — Work requires re-briefing or new requirements
4. **Quality gate failure** — Code won't run, critical bug, missing feature
5. **Security/compliance breach** — Policy violation discovered
6. **Deadline risk** — Will slip > 1 hour
7. **Resource shortage** — Team can't complete with current capacity

**DO NOT ESCALATE:**
- Decisions Tech Lead can resolve
- Technical questions within scope
- Implementation details
- Status updates (unless blocker)
- Questions one agent can answer

### **Dev Agent → Tech Lead** (Always escalate if stuck)

**ESCALATE IF:**
1. Blocked on a dependency (another agent's work)
2. Ambiguity in brief (need clarification)
3. Technical conflict with another agent
4. Need more time (deadline risk)
5. Discovered missing requirement
6. Code won't run / test fails and can't fix

---

## 4. COMMUNICATION PROTOCOL

### **Status Format** (each agent posts hourly)
```json
{
  "agent": "Frontend Engineer",
  "pane": "w4:pN",
  "status": "in_progress|blocked|ready_for_review|completed",
  "current_task": "Implement character creation UI",
  "progress_pct": 75,
  "blocker": null | {
    "description": "Backend inventory API not ready",
    "impact": "Can't test item selection",
    "since": "11:30 AM",
    "assigned_to": "Backend Engineer"
  },
  "timestamp": "2026-10-25T14:45:00Z"
}
```

### **Escalation Format** (Tech Lead to PM)
```json
{
  "type": "escalation",
  "priority": "high|medium|low",
  "category": "blocker|conflict|deadline|quality|scope",
  "summary": "Backend module incomplete, Frontend blocked on API",
  "details": "...",
  "requester": "Tech Lead",
  "decision_needed": "Extend deadline by 2 hours OR reduce scope",
  "recommended_action": "...",
  "timestamp": "2026-10-25T14:50:00Z"
}
```

### **Message Routing**
- **Dev Agent ↔ Dev Agent:** Direct, logged
- **Dev Agent → Tech Lead:** Always logged, Tech Lead responds within 15 min
- **Tech Lead → PM:** Only critical escalations, PM responds within 30 min
- **PM → Team:** Through Tech Lead (no direct agent contact)

---

## 5. DAILY WORKFLOW

### **9:00 AM — Standup (Tech Lead)**
- Each agent: 1-min status (what's done, what's next, any blocker)
- Tech Lead: consolidates, identifies escalations
- **Output:** Standup summary sent to PM (if any escalations)

### **Throughout Day — Status Updates**
- Agents post status on pane (visible to Tech Lead)
- Tech Lead monitors blockers
- Unblocks directly if possible (< 15 min decision)

### **2:00 PM — Tech Lead Escalation Check**
- Review all blockers
- Escalate to PM if needed (with recommendation)
- PM responds with decision

### **5:00 PM — EOD Report (Tech Lead → PM)**
```
Completed today: [list of finished tasks]
Blockers remaining: [list with impact]
Escalations: [any pending decisions]
Readiness: [% of deliverable complete, what's left]
```

### **EOD — Agent Log Update**
- Each agent: commit work, document blockers
- Tech Lead: verify all escalations logged

---

## 6. PM VALIDATION CRITERIA

The PM validates the deliverable **before approving completion**.

### **Checklist: Text RPG Valid + Runnable**

- [ ] **All 8 modules exist and have code** (no stubs, no TODOs)
  - game.py, character.py, combat.py, dungeon.py, enemy.py, inventory.py, ui.py, README.md
- [ ] **Code syntax valid** (no Python errors, can import all modules)
- [ ] **All 6 mandatory features work**
  1. Character creation (full flow, stat allocation)
  2. Combat system (turn-based, win/lose conditions)
  3. Inventory system (equip, drop, use items)
  4. Dungeon exploration (≥10 rooms, navigation, descriptions)
  5. Enemies (≥5 types, varying difficulty, loot drops)
  6. Progression (experience, leveling, stat growth)
- [ ] **Save/Load works** (game state persists, can resume)
- [ ] **Game is playable start-to-finish** (PM runs it, completes a dungeon)
- [ ] **No external dependencies** (uses only Python stdlib)
- [ ] **User-friendly** (clear prompts, readable output, intuitive controls)
- [ ] **No crashes or unhandled exceptions** (graceful error handling)

### **PM Decision**
- ✅ **APPROVED:** "Deliverable valid, runnable, all requirements met. Ready for delivery."
- ❌ **REJECTED:** "Missing [specific items]. Return to Tech Lead with fixes needed."

---

## 7. HERDR IMPLEMENTATION

### **Grid Layout (2×4, perfectly balanced)**
```
ROW 1 (20 rows each):
  w4:pJ  | 🔥 PM: Project Manager (openai/gpt-oss-120b)
  w4:pN  | 💻 Frontend Engineer (openai/gpt-oss-20b)
  w4:pM  | 🗄️ Backend Engineer (openai/gpt-oss-20b)
  w4:pK  | ⚙️ DevOps Engineer (openai/gpt-oss-20b)

ROW 2 (20 rows each):
  w4:pS  | 🔍 Security Engineer (openai/gpt-oss-20b)
  w4:pR  | 🧪 QA Engineer (openai/gpt-oss-20b)
  w4:pQ  | 📊 Data Engineer / Tech Lead (openai/gpt-oss-20b)
  [Reserved for future or Ops]
```

### **Agent Environment**
```bash
BATCH_GATEWAY_URL=http://127.0.0.1:8787/v1
BATCH_GATEWAY_KEY="$(batch_gateway.py token)"
BATCH_PROVIDER=groq
GROQ_API_KEY=[from .env]
```

### **Startup Command**
```bash
# PM (Tier 1)
pi --provider batch-gateway --model openai/gpt-oss-120b

# All others (Tier 2 & 3)
pi --provider batch-gateway --model openai/gpt-oss-20b
```

### **Working Directory**
- All agents work in `/tmp/pi_rpg_build/`
- Shared file: `.escalations.jsonl` (Tech Lead writes, PM reads)
- Status log: `.status.log` (each agent appends hourly)

---

## 8. QUALITY GATES

### **Before Tech Lead Escalates to PM**
- [ ] Code compiles/runs (no syntax errors)
- [ ] All cross-team dependencies resolved
- [ ] Tests pass for own module
- [ ] Code review by peer agent (if time allows)

### **Before PM Approves Delivery**
- [ ] Tech Lead signs off: "All code complete, no TODOs, tests pass"
- [ ] PM runs full game validation checklist (section 6)
- [ ] PM documents any issues found
- [ ] Issues sent back to Tech Lead with fix list

---

## 9. FAILURE MODES & ESCALATION

### **If Tech Lead is Blocked**
- Tech Lead escalates directly to PM
- PM decides: override blocker, extend deadline, reduce scope

### **If Dev Agent Goes Silent**
- Tech Lead checks pane status
- Tech Lead sends message to agent
- After 30 min no response: escalate to PM

### **If PM Rejects Deliverable**
- PM sends rejection list to Tech Lead
- Tech Lead assigns fixes to relevant agents
- Re-validate before re-submission

### **If Deadline is Missed**
- Tech Lead escalates immediately (don't wait for EOD)
- PM decides: extend, reduce scope, or accept partial delivery

---

## 10. ARTIFACTS & DOCUMENTATION

### **Committed to Version Control**
- `.claude/TEAM_CHARTER.md` — This document
- `.claude/ROLES.json` — Pane assignments, model configs
- `.claude/ESCALATION_LOG.md` — Running log of all escalations
- `PROJECT_BRIEF.md` — Original requirements (what PM validates against)

### **Generated During Work**
- `.escalations.jsonl` — Structured escalation events
- `.status.log` — Hourly agent status snapshots
- `.debug/` — Logs from herdr/Pi agents (for post-mortem)

---

## 11. SUCCESS METRICS

✅ **Team succeeds if:**
1. Deliverable approved by PM within deadline
2. No unblocked work sits idle > 1 hour
3. Tech Lead needed < 10 escalations total
4. PM can validate in < 30 minutes (no back-and-forth)
5. All code readable, no TODOs, fully functional

❌ **Team fails if:**
1. Deliverable incomplete or doesn't run
2. PM finds bugs after approval
3. Team misses deadline
4. Scope creep (requirements added after day 1)

---

## 12. COMMUNICATION EXAMPLES

### **Example 1: Simple Technical Decision**
```
Frontend → Backend: "Can we change inventory API to return {item, qty}?"
Backend: "Yes, makes sense. I'll update by noon."
[No escalation needed]
```

### **Example 2: Blocker Escalation**
```
Frontend → Tech Lead: "Blocked: inventory API not ready, can't test UI"
Tech Lead → Backend: "ETA on inventory API?"
Backend: "2 more hours"
Tech Lead → Frontend: "Continue with mock API, swap real one when ready"
[Unblocked by Tech Lead, no PM escalation]
```

### **Example 3: Critical Escalation**
```
Tech Lead → PM: "Backend module incomplete. Frontend blocked, QA can't test.
Estimate: 3 more hours. Deadline 5pm (2 hours away).
Options: (A) Extend deadline 1.5 hours OR (B) Ship without full combat system.
Recommend: (A) extend deadline, impacts only delivery time not quality."

PM: "Approved: new deadline 6:30pm. Focus on completeness over scope."
Tech Lead → Team: "New deadline 6:30pm. Reduce scope if needed but no stubs."
```

### **Example 4: PM Final Validation**
```
Tech Lead: "Deliverable ready for validation. All code complete, 
tests pass, no TODOs. Checklist items 1-7 verified."

PM: [Runs game, tests character creation, combat, inventory, dungeon, save/load]
PM: "APPROVED. Deliverable valid, runnable, complete. Ready for delivery."
```

---

## 13. REVISION HISTORY

| Date | Change | Approved By |
|------|--------|-------------|
| 2026-10-25 | Initial charter | — |
| — | — | — |

---

**Document Owner:** Tech Lead (w4:pQ)  
**Last Updated:** 2026-10-25  
**Next Review:** After first delivery or significant change to team size/scope
