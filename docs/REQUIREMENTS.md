# Product requirements log

Append **one requirement** after every product change. Newest last.

Each entry is the product rule, the broken flow, what code changed, and the fix. A user scenario is an example of the rule, not a one-off patch. Do not encode example domains into prompts.

---

## REQ-001 — Request-lane “open the message” banner hides after the match is read

**Date:** 2026-10-15

**Requirement:** When a match has a new broker message, the request lane may show a banner to open that match. After the user opens the match and the messages are marked read, that banner must hide. Waiting-on-you dots stay on the match tab and sidebar. A later new unread on that match may show the banner again. Connect-offer banners stay until the user accepts or dismisses.

**What was wrong:** `laneAlert` treated `waiting` as a request-lane popup. Opening the match zeroed `unread_count`, but `waiting` stayed true (notebook `waiting_on` or `waiting_match_id`), so “The broker needs you… Open that match” remained. The 4s session poll could also restore unread before mark-read landed.

**Flow change:** Request-lane banners are unread and connect-offer only. Opening a match records it as pending-read so a poll cannot restore that unread until the API reports 0.

**Code change:** `frontend/components/chat/broker-chat.tsx` — `laneAlert`, `noteMatchRead`, `applyLaneReadState`. Waiting UI on `match-lane-rail.tsx` / `session-sidebar.tsx` unchanged.

**Fix:** Hide the “open the message” popup after read without clearing agent waiting state.

---

## REQ-002 — Match-lane title is a compact counterpart label

**Date:** 2026-10-15

**Requirement:** A match tab, sidebar row, and match header title must identify the counterpart in a short label. After accept/connect, use their name (plus short location when present). Before that, use living-brief `domain · location` (or a clipped objective). Do not dump the counterpart’s 72-character first-message session title into the tab.

**What was wrong:** `match_lane_label` preferred `other.title` (`create_title` of the first message). Tabs read as “Electrician in Pimple Nilakh to inst…” and “Find a girl looking for PG…”.

**Flow change:** Label is built from the living brief at serialize time. Identity still opens only after accept/connect.

**Code change:** `backend-agent/app/services/match_lanes.py` (`match_lane_label`, `_short_place`, `_display_domain`, `_short_phrase`). Tests in `tests/test_match_lanes.py`.

**Fix:** Scannable match titles without leaking identity early.

---

## REQ-003 — Opening a match from the request lane still replies on the request lane

**Date:** 2026-10-15

**Requirement:** The UI does not auto-switch after `open_match`. If the user sent from the request lane and the broker opens a match in that turn, they must get **one assistant reply on the request lane** so they are not left hanging. The pair kickoff (the working “I found this counterpart…” note) still starts on the **match lane**. Tools in the same turn (`update_notebook`, `message_party`) still default to the new match.

**What was wrong:** `open_match` called `adopt_focus_if_idle`, which set `focus_match_id` to the new match. `run_broker_turn` then stamped every visible assistant row with `focused_match_id(ctx)`. The user stayed on Your request (empty after their own bubble). The good kickoff sat only on the new tab.

**Flow change:**

1. User sends on the request lane (`match_id` null).
2. Agent may `open_match`. Focus is adopted for later **tools** only.
3. Runtime writes a short request-lane update (`match_id` null).
4. Runtime writes the model’s kickoff on the new match lane (`match_id` = that match).
5. Frontend stays on the request lane, shows the update, and the new tab appears (unread on that tab is expected).

**Code change:**

- `ToolContext.reply_match_id` frozen at turn start in `backend-agent/app/agents/context.py`. `reply_lane_id()` returns it. `adopt_focus_if_idle` still mutates `focus_match_id` for tools.
- `run_broker_turn` in `backend-agent/app/agents/runtime.py`: if the turn started on the request lane and ended with a focused match, persist `REQUEST_LANE_OPENED_MATCH_REPLY` (or the plural copy) on the request lane, then persist model replies on the match. Helper `_persist_assistant_reply`.
- Copy in `backend-agent/app/agents/prompts.py`.
- Failed-turn fallback in `backend-agent/app/services/orchestrator.py` uses `reply_match_id` so errors stay on the lane the user sent from.
- Tests: `tests/test_match_lanes.py` (`test_reply_lane_stays_on_request_when_open_match_adopts_focus`), `tests/test_agent_runtime.py` (`test_open_match_from_request_lane_leaves_an_update_then_starts_match`).

**Fix:** Never leave the request lane silent after a match is opened from it. Keep the match-lane kickoff. Do not auto-switch the tab.
