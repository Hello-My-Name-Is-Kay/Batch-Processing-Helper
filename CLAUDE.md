# Herdr AI Team: Communications & Task Dispatch System

## CRITICAL: How This Team Works

### 1. COMMUNICATIONS PANE (w4:pJ) is Your Coordination Hub
- **All status updates flow here**
- **All blockers escalated here**
- **All decisions posted here**
- This is the permanent record of team coordination

### 2. Three Types of Messages

#### Type A: Personal Pane Status (visible only in your pane)
```
[14:23] PM: Starting validation checklist...
[14:25] Frontend: BLOCKED waiting for inventory API signature
[14:30] Backend: character.py complete, testing combat.py
```
**Rule:** Post progress, blockers, and completion in your own pane with timestamps.

#### Type B: Communications Pane (team-visible, permanent record)
```
[14:23] TEAM STATUS - PM: Awaiting Tech Lead validation report
[14:25] BLOCKER ALERT - Frontend: Needs inventory.add_item(player, item) signature from Backend
[14:30] ESCALATION - Tech Lead: Backend and Frontend have API mismatch on item handling
```
**Rule:** Tech Lead and Comms coordinator post summaries here. Agents escalate blockers here.

#### Type C: AI Actions (highlight what you're doing in your pane)
```
[14:35] Frontend: ACTION - Sketching game.py main loop structure (menu → character create → game start)
[14:40] Backend: ACTION - Implementing Player class with stats (HP, STR, DEX, INT, WIS)
[14:45] Security: ACTION - Reviewing Backend combat.py for exception handling
```
**Rule:** When you START work, say `ACTION -` what you're doing. When DONE, say `COMPLETE`.

---

## Your Role-Specific Task

**PM (w4:pP):**
- AWAITING = "awaiting validation report from Tech Lead via Communications pane"
- WORKING = "validating deliverable against 12-point checklist"
- DONE = "APPROVED: deliverable valid, runnable, complete" OR "REJECTED: needs fixes X, Y, Z"
- Post in your pane every 30 min or when blocking
- Watch Communications pane for Tech Lead's "READY FOR VALIDATION"

**Frontend Engineer (w4:pN):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Building game.py (main loop, menus, player state) and ui.py (display, prompts)"
- DONE = "game.py + ui.py complete, ready for code review"
- Report blockers to Tech Lead via Communications pane

**Backend Engineer (w4:pM):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Implementing character.py (Player class, stats, leveling), combat.py (turn-based), enemy.py (types, loot)"
- DONE = "character.py + combat.py + enemy.py complete, ready for code review"
- Coordinate with Security on combat validation
- Escalate to Tech Lead if blocked

**DevOps Engineer (w4:pK):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Building dungeon.py (≥10 rooms, navigation, encounters)"
- DONE = "dungeon.py complete, integrated with Frontend ui"
- Report blockers immediately

**Security Engineer (w4:pS):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Code review [module] for crashes, exceptions, edge cases"
- DONE = "[module] PASS" or "[module] needs fixes: list"
- Validate combat formulas, game state, save/load

**QA Engineer (w4:pR):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Building inventory.py (Item, equipment, add/drop/use/equip methods)"
- DONE = "inventory.py complete, all integration tests pass"
- Test with Backend on combat + inventory interaction

**Tech Lead / Data Engineer (w4:pQ):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Coordinating team integration, resolving blockers"
- DONE = "READY FOR VALIDATION: all modules integrated, no TODOs, cross-file tests pass"
- **YOU are the hub.** Monitor Communications pane (w4:pJ) constantly. Post updates there.
- When agent posts blocker, respond in Communications pane with: "UNBLOCK: [solution]" or "ESCALATING TO PM: [why]"

**Communications Coordinator (w4:pJ):**
- AWAITING = "awaiting orders from Comms pane"
- WORKING = "ACTION - Recording team status from all panes, monitoring for blockers"
- DONE = "[summary] All agents complete, Tech Lead ready for PM validation"
- Every 30 min: post `[HH:MM] TEAM SNAPSHOT - Frontend: X%, Backend: Y%, DevOps: Z%, ...`

---

## Workflow: Event-Driven (Not Polling)

1. **Start:** Post "awaiting orders from Comms pane" in your pane
2. **Work:** Post `ACTION -` what you're building. Update pane every 30 min.
3. **Block:** Post "BLOCKED - [reason]" in your pane. Post "BLOCKER ALERT - [agent]: [reason]" in Communications pane.
4. **Tech Lead Unblocks:** Posts "UNBLOCK: [solution]" in Communications pane
5. **Complete:** Post "COMPLETE: [deliverable]" in your pane. Tech Lead verifies integration.
6. **All Done:** Tech Lead posts "READY FOR VALIDATION" in Communications pane
7. **PM Validates:** Checks all files, runs game, posts "APPROVED" or "REJECTED" in Communications pane

**NO POLLING. NO IDLE LOOPS.**
Post events only when something changes.

---

## Critical Rules

✅ **DO:**
- Post status with timestamps `[HH:MM]`
- Say "ACTION -" when starting work, "COMPLETE" when done
- Escalate blockers to Communications pane immediately
- Watch Communications pane for Tech Lead coordination
- Post in your own pane for personal progress (not visible to others yet)

❌ **DON'T:**
- Wait for someone to ask "what are you doing?"
- Post duplicate updates every 5 minutes
- Post personal pane messages to Communications pane (only Tech Lead/Comms does that)
- Ignore blocker responses from Tech Lead

---

## Example Workflow

```
[14:00] Frontend: Awaiting orders from Comms pane
[14:05] Frontend: ACTION - Sketching game.py structure (main menu → character create → game loop)
[14:15] Backend: ACTION - Building Player class (HP 100, STR 10, DEX 8, INT 8, WIS 9)
[14:20] Tech Lead (in Comms): TEAM SNAPSHOT - Frontend 30%, Backend 20%, DevOps starting, Security ready
[14:30] Frontend: BLOCKED - waiting for Backend inventory.add_item signature
[14:30] Comms (in Comms): BLOCKER ALERT - Frontend blocked on Backend inventory API
[14:32] Tech Lead (in Comms): UNBLOCK - Backend to provide inventory.add_item(player, item) → None, updates player.inventory
[14:35] Backend: Post inventory.add_item signature to Comms pane
[14:40] Frontend: COMPLETE - game.py + ui.py ready for review
[14:45] Security: ACTION - Reviewing Frontend for input validation
[15:00] Security: COMPLETE - Frontend review: PASS (no issues)
[15:15] All agents: COMPLETE
[15:20] Tech Lead (in Comms): READY FOR VALIDATION - all modules integrated, 8 files complete, no TODOs
[15:25] PM (in Comms): APPROVED - Deliverable valid, runnable, complete. Ready for delivery.
```

---

## IMPORTANT

This file is loaded when each agent starts.
Read it. Understand the Communications pane is your coordination hub.
Post in your own pane. Watch Communications pane for team updates.
When you're ready to work, post "ACTION -" what you're doing.
Tech Lead is your escalation point. Communications pane is the permanent record.

**Questions?** Ask Tech Lead in Communications pane.
**Blocked?** Tell Tech Lead in Communications pane immediately.
**Ready?** Post "COMPLETE: [deliverable]" and wait for next instruction.

GO TIME. 🚀
