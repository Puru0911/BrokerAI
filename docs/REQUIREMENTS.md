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

---

## REQ-004 — Screened candidates are one-sided Interested/Skip cards

**Date:** 2026-10-16

**Requirement:** Screening stays on Your request. `evaluate_pair` screens up to `MAX_PAIR_PER_REQUEST` (default 3) candidates and stores them on this request only. Ready candidates appear as Interested/Skip cards (`present_candidates`); public photos show clearly and personal photos are blurred with Request photo (which counts as Interested). A two-sided match lane opens only after Interested. Skip excludes that candidate from later fills for this request. Unacted cards can return with new ones on the next screening turn. The counterpart never sees this evaluation or those cards. Clarifying questions for this person stay here; after they answer, stored suggestions are re-evaluated. The other person is contacted only after Interested, on the new match lane.

**What was wrong:** `evaluate_pair` returned one pair. A possible pair was written onto both briefs (`details.possible_pair`) and `message_party(candidate_id)` reached the counterpart before this person opted in. `open_match` created a lane for both parties immediately and `MAX_OPEN_MATCHES_PER_REQUEST` capped live OPEN matches.

**Flow change:**

1. Search and evaluate run in the background. Search does not return counterpart briefs; evaluate loads last-search or stored ids.
2. Store `agent_suggested_matches` on the source request. Ask this person any `ask_clarifying_question` here, then re-evaluate stored ids.
3. `present_candidates` writes request-lane cards. No outreach.
4. Interested or Request photo opens the match, stays on Your request, and kicks off the pair on the new tab. Skip removes that candidate.
5. `open_match` and `message_party` require that Interested step.

**Code change:** `backend-agent/app/services/suggestions.py`, Alembic `0006_suggested_matches`, batch `evaluate_pairs`, `present_candidates` tool, Interested/Skip API, Pillow blur derivatives, gated `open_match` / `message_party`, `schedule_match_kickoff`, frontend `candidate-card.tsx`. Cap renamed to `MAX_PAIR_PER_REQUEST`. `possible_pair` store and pre-open outreach removed.

**Fix:** This person chooses which screened people become matches. The other person is not shown the same evaluation.

---

## REQ-005 — Present the screening set together after clarifying answers

**Date:** 2026-10-16

**Requirement:** Up to three screened candidates are one set. Status is `strong_match` when no question is needed (`pending_clarify` is none) or `pending_clarify` when this person still owes a fact. A pair is not limited to one clarifying question: the pair screener decides the missing facts and the questions, then the packet lists every pending question from every pair. The broker asks those questions on Your request. If any of the set needs a question, do not show cards yet — including the strong matches in that set. After they answer, re-evaluate the stored pairs and present every remaining `strong_match` together in one horizontal row of Interested/Skip cards.

**What was wrong:** `ready` cards could appear immediately while others in the same screening still needed a question. Each card was its own stacked bubble. Screening also kept one `clarifying_question` string per pair and did not hand the broker the full set.

**Flow change:** Hold the whole set while any row is `pending_clarify`. Collect `clarifying_questions` from every pending pair into `pending_questions`. The broker asks them. `present_candidates` writes one `broker_candidate_cards` message for every `strong_match` together.

**Code change:** `backend-agent/app/services/suggestions.py` (`strong_match`, batch hold, one deck message, `pending_questions`). Pair evaluator `clarifying_questions`. Packet and `evaluate_pair` result. Prompts and `present_candidates` tool copy. Frontend `CandidateDeck` in `candidate-card.tsx`.

**Fix:** The three (or fewer) people from one screening appear at once, after any clarifying answers. Clarifying still works as before: the screener decides gaps and questions, the broker asks the combined list.

---

## REQ-006 — Counterpart briefs stay out of the broker chat; index/search/evaluate are async

**Date:** 2026-10-17

**Requirement:** The broker agent works from this person's brief, request ids, candidate ids, counts, statuses, and pending questions. Other people's living briefs never enter the conversation, tool results, or model history except through scoped tools (`get_match_brief`, `answer_match_question`). Index, search, and evaluate run in the background so the user is not blocked. Search does not auto-run after index; the agent decides on a `request_ready` turn. `evaluate_pair` re-screens last-search or stored ids after clarifying answers.

**What was wrong:** `search_counterparties` dumped anonymized candidate briefs into in-turn ToolMessages. `evaluate_pair` dumped full pair-evaluation bodies. `get_match_events` returned the other brief. Candidate-card JSON in assistant history re-ingested previews. Index/search/evaluate ran inside the user turn.

**Flow change:**

1. `index_request`, `search_counterparties` / `search_again`, and `evaluate_pair` enqueue a persisted job and return immediately.
2. After HTTP commit, an in-process task runs the job. Index is its own kind. Search plus pair-screen is one `screen` job. Evaluate re-screens given or last-search ids.
3. When the job finishes (done or failed), a `request_ready` turn continues with a `background_job` packet of ids and counts only.
4. The agent uses `get_match_brief` for a complementary summary and `answer_match_question` for a fact in that brief. If the fact is missing and a match is open, it uses `message_party`.
5. Cards still render in the UI. Model history sees placeholders instead of card JSON.

**Code change:** Removed DEV/small prompt copies and `AGENT_PROMPT_SIZE`. Added `agent_request_jobs` (Alembic `0007_request_jobs`), `app/services/request_jobs.py`, `app/services/screening.py`. Tools enqueue jobs. Packet drops `missing_info` from suggestions and `other_brief` from `get_match_events`. `history_visible_content` sanitizes structured cards. Tests in `tests/test_request_jobs.py`, `tests/test_prompts.py`, `tests/test_agent_runtime.py`.

**Fix:** The chat stays on this person's request. Screening work happens in the background. Counterpart facts load only when the agent asks, and only as a source-relative summary.

---

## REQ-007 — Strong matches present now; possible-match questions are a later turn

**Date:** 2026-10-18

**Requirement:** Pair evaluation status follows the screener verdict. `strong_match` cards are shown together as soon as they exist. `possible_match` is not a card. Questions this person still owes (`ask_clarifying_question`) are asked after those cards, on a follow-up request-lane turn. Questions only the other person can answer (`ask_other_person`) go out immediately with `message_party(candidate_id)` on their request lane; this user does not store that question. Interested is still required to open a match. Failed index/search/evaluate jobs still wake the agent so it can retry, but a short “restarted search” bubble is not shown when a retry is already queued. Screen/evaluate JSON parse failures retry once in Python before that wake. OpenRouter broker sampling is temperature 0.3 / top_p 0.8, reasoning effort low, with provider order deepinfra → novita → coreweave → parasail.

**What was wrong:** `ask_other_person` and other non-skip verdicts were stored as `strong_match`, so cards appeared while the counterpart still had unanswered facts. `present_candidates` also refused the whole set while any row was `pending_clarify`. Failed screen jobs woke the agent, which called `search_again` and posted “I’ve restarted the search.” OpenRouter sampling and provider order did not match the intended routing.

**Flow change:**

1. Status: skip/no_match → skipped; verdict strong_match → strong_match; ask_clarifying_question → pending_clarify; everything else, including ask_other_person → possible_match.
2. After screening, present every strong_match. Pending questions are withheld from that packet so the reply is only the cards.
3. A `clarify` job then wakes the agent to ask this person's questions and to `message_party` remaining possible matches.
4. `message_party(candidate_id)` queues a request-lane turn on the other session. When that person answers and their index completes, sources that still have a possible_match on them are re-evaluated.
5. Failed jobs: one silent parse retry, then an agent retry with no searching ack persisted.

**Code change:** `status_for_evaluation` and `present_candidates` in `suggestions.py`; packet retract in `context.py`; `JOB_CLARIFY` and silent retry / possible-match re-eval in `request_jobs.py`; quiet ack drop in `runtime.py`; request-lane outreach in `match_tools.py` and `outreach.py`; OpenRouter provider and sampling in `client.py`. Tests in `test_suggestions.py`, `test_request_jobs.py`, `test_agent_runtime.py`, `test_llm_client.py`, `test_prompts.py`.

**Fix:** Strong matches reach the user immediately. Possible-match questions are asked of the right person without mixing them into the card pitch or treating them as a match.

---

## REQ-008 — Upload asks stay in chat; candidate cards are one-shot, one person, brief-only

**Date:** 2026-10-18

**Requirement:** The broker asks for files in a normal message. It does not post an upload card; this person uses the paperclip next to the composer. A candidate card is shown once: if it is still sitting with no Interested or Skip, later screening must not send that card again or merge it into a new deck. Search, evaluate, and present keep at most one candidate request per counterpart user, even when that person has two similar open briefs. Candidate cards show the complementary brief and Interested/Skip only — no photos, blur tiles, or Request photo.

**What was wrong:** `request_attachment` wrote one upload card per ask. Two asks left two cards; fulfilling one still left the other stuck in chat. `present_candidates` and frontend clustering could append unacted cards into a later deck. Retrieval scored requests, so two briefs from the same person could both appear. Cards always reserved a photo well, including a No photo state, which does not fit every domain.

**Flow change:**

1. `request_attachment` records the ask and returns. The model writes the request in its reply. Uploads go through the composer control. Legacy upload-request messages are hidden in the thread.
2. `present_candidates` writes a new deck only for never-shown `strong_match` rows, up to `MAX_PAIR_PER_REQUEST` per call. Presented, interested, skipped, or `card_message_id` rows are not resent. Asking for more matches on a later turn still presents new people. Consecutive decks are not merged.
3. Retrieve, evaluate, and present skip a second request from a user who is already a suggestion, already in this batch, or already in a live match.
4. New card JSON has no `images`. The UI renders preview text and actions only.

**Code change:** `attachment_tools.py`, `prompts.py`, `suggestions.py`, `screening.py`, `candidate-card.tsx`, `message-list.tsx`, `message-bubble.tsx`. Tests in `test_suggestions.py` and `test_prompts.py`.

**Fix:** File asks use the existing composer. Each match card is shown once, from one person, as a brief.

---

## REQ-009 — One search per turn; `search_counterparties` and `search_again` share a skip key

**Date:** 2026-10-19

**Requirement:** A broker turn starts at most one background search. `search_counterparties` and `search_again` enqueue the same kind of screen job. After a successful search or screen, the broker says so (or watches) instead of starting a second round in that turn.

**What was wrong:** Duplicate skip keyed on `{name, args}`. Empty-arg `search_counterparties` then `search_again` both ran. The prompt called `search_again` a “fresh” search, so the model treated it as a second set. On 2026-10-18 session `2ee8ead6`, a completed screen with five skips was followed by `search_again` and a “widened the search / fresh round” reply. Session `8084bb2f` retried a failed screen first with `search_counterparties`, then with `search_again`.

**Flow change:**

1. The model is told both tools start the same background search and only one runs this turn. A succeeded search or screen does not start another.
2. `run_tool_loop` skip keys both names as `search_pool`. A successful first search skips the other in the same turn.
3. `search_again` still replaces an in-flight job when it is the first search tool of the turn, including a quiet retry after a failed screen.

**Code change:** `runtime.py` `_call_signature`; `prompts.py` HOW YOU WORK, LIMITS, REQUEST_READY, `TOOL_SEARCH_AGAIN`. Tests in `test_agent_runtime.py` and `test_prompts.py`.

**Fix:** One search job per turn. A finished screen is not immediately searched again as a second set.

---

## REQ-010 — After they answer, screen the person who already matched them

**Date:** 2026-10-19

**Requirement:** Screening stays one-sided. If A already has B as a live suggestion and reaches B for a missing fact, B must independently screen A after answering (and after the brief is re-indexed). A card on A's request is not a card on B's request. B should see A when B's own screen rates A as a strong match.

**What was wrong:** On 2026-10-19, groom request `3aa19662` stored bride `ec39b6b6` as `possible_match`, asked her about living with parents, then re-evaluated to `strong_match` and presented her. Her request never got a suggestion row for him. After she answered, her broker re-indexed and searched. That screen failed JSON parse with empty `candidate_ids`. `evaluate_pair` with no ids reused the last *successful* screen (`0f4df0f1`, already skipped). The model said the latest profile was not a fit.

**Flow change:**

1. Request-lane `message_party(candidate_id)` writes a `possible_match` pointer on the recipient for the sender (no copy of the sender's evaluation).
2. When the recipient's brief is re-indexed, Python also evaluates those reverse live suggestions on their request.
3. A failed screen still stores retrieved ids. Empty `evaluate_pair` skips already-skipped last-search ids and uses stored active suggestions.
4. After they answer, the broker evaluates stored candidates instead of starting a new search for that answer.

**Code change:** `suggestions.py` `ensure_inbound_suggestion`; `match_tools.py`; `request_jobs.py` `enqueue_reciprocal_evaluations`, `latest_screen_candidate_ids`, `resolve_evaluate_ids`; `screening.py` persists ids before pair eval; `prompts.py`. Tests in `test_request_jobs.py`, `test_suggestions.py`, `test_prompts.py`.

**Fix:** The person who was asked independently screens the person who asked, instead of retrying an old skip.

---

## REQ-011 — One pipeline wake; questions only for possible matches

**Date:** 2026-10-19

**Requirement:** Index, search, and pair evaluation run as one background pipeline. The broker turn wakes once when that pipeline finishes, not after index and again after search. Possible matches are not stored as candidate or request ids. The living brief keeps only the clarifying questions needed to decide if a pair can become a strong match. When this person or the other person answers, the brief is updated and the pipeline searches and evaluates pairs again; with those answers the screener returns strong_match or skip. The broker has no `evaluate_pair` tool. Internal `evaluate_pairs` still runs inside the screen job so the model cannot mediate possible matches on the request lane.

**What was wrong:** The model woke after indexing and again after searching, which produced extra request-lane turns. Possible-match rows stored counterpart ids, so the model treated those people as live suggestions and started mediating on Your request. After an answer the model was told to re-evaluate stored ids instead of searching again, which could reuse a stale screen.

**Flow change:**

1. `index_request` does not wake the broker. On a successful index, Python enqueues `screen` (search + `evaluate_pairs`). The broker wakes when that screen finishes. A failed index still wakes so the agent can retry.
2. Screening stores strong_match and skip only. This person's questions replace `request.pending_questions`. Questions only the other person can answer are asked on their request lane at screen time, without a possible-match row.
3. Save/update clears pending questions. After they answer, they index; the pipeline searches and evaluates again with the new brief.
4. The `evaluate_pair` broker tool is removed.

**Code change:** `request_jobs.py`, `screening.py`, `suggestions.py`, `search_tools.py`, `request_tools.py`, `match_tools.py`, `prompts.py`, `context.py`, `runtime.py`, Alembic `0008_pending_questions`. Tests in `test_request_jobs.py`, `test_suggestions.py`, `test_prompts.py`, `test_match_lanes.py`, `test_agent_runtime.py`.

**Fix:** One wake after index+search+eval. Possible matches are questions, not stored pairs. The model presents strong cards and asks this person's questions; it does not re-screen by id.

---

## REQ-012 — Strong fit and Close fit cards; this-user questions stay off the deck

**Date:** 2026-10-19

**Requirement:** Pair screening returns three live cases. Strong matches (`strong_match` + `open_match`) appear as Strong fit Interested/Skip cards. Possible matches that need negotiation or a fact from the other person (`ask_other_person`) appear as Close fit cards that show what fits and what is still open; the other person is not contacted until this person marks Interested, which opens a match lane so later questions stay on that pair. Matches that still need a fact from this person (`ask_clarifying_question`) are stored as `pending_clarify` with candidate ids and are not presented; those questions go on Your request, and after answers `evaluate_pair` re-screens the stored ids. Do not open or involve the other party for a pending_clarify row.

**What was wrong:** Only strong matches were cards. Possible matches were dropped to questions, so the agent asked the other person without asking if this person wanted that pair, then lost which match a question belonged to. This-user gaps were mixed into the same path.

**Flow change:**

1. Index still chains to search + `evaluate_pairs`; the broker wakes once when that screen finishes.
2. Store A/B/C/skip on `agent_suggested_matches`. Present Strong fit and Close fit together. Hold this-user questions for a later `clarify` turn, tagged with `candidate_id`.
3. Interested on a Close fit opens the match, then the kickoff asks the other person on that lane.
4. After this person answers, `evaluate_pair` the stored candidate ids (no new search for that answer). If the pair becomes Strong or Close fit, present it.

**Code change:** `suggestions.py`, `screening.py`, `search_tools.py` (`evaluate_pair`), `prompts.py`, `context.py`, `broker.py` kickoff, `frontend/components/chat/candidate-card.tsx`. Tests in `test_suggestions.py`, `test_request_jobs.py`, `test_prompts.py`, `test_match_lanes.py`.

**Fix:** This person chooses Close fits before anyone is asked. This-user questions stay on the request lane with the candidate they belong to. Strong fits stay one-click Interested.

---

## REQ-013 — Card, then Interested, then match; no request-lane outreach

**Date:** 2026-10-21

**Requirement:** After this person answers Case C questions, `evaluate_pair` re-screens those stored ids. Strong stays a Strong fit card. Skip stays off the deck. Any leftover live pair becomes a Close fit card. `message_party` only runs on an open match, after Interested. Do not reach the other person from Your request with `candidate_id`.

**What was wrong:** After Case C answers, the broker messaged the other person on their request lane (`message_party` with no match). Pair negotiation (budget, milestones, start date) landed on Your request, with no Interested and no match tab to pin the thread.

**Flow change:**

1. Case C questions stay on Your request. The other person is not contacted.
2. After answers, re-eval those ids. Present Strong fit or Close fit. Do not present skip.
3. Interested opens the match. Then `message_party` on that match lane.

**Code change:** `match_tools.py` (`message_party` requires an open match), `suggestions.py` (`promote_pending` on `evaluate_pair`), `screening.py`, `prompts.py`. Tests in `test_suggestions.py`, `test_prompts.py`.

**Fix:** Pair talk waits for a card and Interested, then lives on the match tab.

---

## REQ-014 — Upload caption vs broker file description

**Date:** 2026-10-21

**Requirement:** The text a person types with an upload is `caption` on the file. The broker writes `description` from this chat, that caption, and what it asked, via `classify_attachment`. Later turns use `description` to know what they are sharing. Counterpart packets and share cards see `description`, not `caption`.

**What was wrong:** Typed caption was stored in `description`. The model had no field for a durable “what this file is,” so later share turns often only saw generic `Photo` / `PDF`.

**Flow change:** Upload writes `caption` and leaves `description` empty. Classify may fill `description`. This person’s packet lists both. The other room lists description only.

**Code change:** `AgentAttachment.caption`, Alembic `0009_attachment_caption`, `attachments.py`, `attachment_tools.py`, `context.py`, `prompts.py`, schemas, frontend types. Tests in `test_attachments.py`, `test_prompts.py`.

**Fix:** User words stay on `caption`. Broker identity of the file lives on `description` for later sharing.

---

## REQ-015 — View filters on evaluate; only user Skip is durable

**Date:** 2026-10-25

**Requirement:** Searching a slice of the saved brief (a neighbourhood, an amenity, a shift, a stack) is a view overlay, not a brief update. `search_counterparties` still retrieves against the indexed living brief. `evaluate_pair` optional `filters` stores `view_filters` on the request and pair evaluation scores against the brief plus that overlay. The overlay does not change `living_request`, does not clear `indexed_at`, and does not re-index. Empty `filters` clears the overlay. Save/update of the brief also clears it. Only this person's Skip on a card is dropped from later search and evaluation. Screener `no_match` / skip is stored as `no_match` and is eligible again on the next search. There is no `search_again` tool.

**What was wrong:** Any browse term looked like a request change, so the agent called `update_request`, re-indexed, and searched a new brief. Evaluator skips were stored as `skipped` and `known_candidate_ids` hid those people from later searches. `search_again` duplicated `search_counterparties`.

**Flow change:**

1. Durable change of what they want is `update_request` then index.
2. A browse overlay is `evaluate_pair` `filters`. Search still uses the indexed brief. Evaluation applies `view_filters`.
3. Next search excludes user-skipped people (and live matches). Everyone else can be scored again.

**Code change:** `AgentRequest.view_filters`, Alembic `0010_view_filters`, `search_tools.py`, `evaluate.py`, `screening.py`, `suggestions.py`, `prompts.py`, `context.py`, `request_tools.py`. Tests in `test_prompts.py`, `test_evaluate.py`, `test_suggestions.py`, `test_request_jobs.py`, `test_living_request.py`.

**Fix:** Trying a slice of the ask does not rewrite the brief. User Skip is the only durable search exclusion.

---

## REQ-016 — Public landing and privacy pages for Google OAuth

**Date:** 2026-10-25

**Requirement:** The product has a public homepage and a public Privacy Policy. Google OAuth consent needs a homepage URL and a privacy URL that accurately describe Google data (name, email, profile picture, plus gender and date of birth when those scopes are granted) and everything else the app collects. Public site and app are described as `broker-ai.app`. `/` is marketing, not a redirect into `/app`. `/privacy` is reachable without signing in. Login links to the policy. User-facing copy must not mention staging hosts or that the domain is pending.

**What was wrong:** `/` redirected to `/app`, so there was no landing page. There was no privacy page for the OAuth consent screen.

**Flow change:** Visitors land on a cream/teal marketing page (how it works, privacy promises, sign-in). Privacy policy is a long-form public page. Login shows “By continuing, you agree to our Privacy Policy.” Brand on login links home.

**Code change:** `frontend/app/page.tsx`, `frontend/app/privacy/page.tsx`, `frontend/components/layout/site-chrome.tsx`, `frontend/components/marketing/product-preview.tsx`, `frontend/lib/site.ts`, `frontend/lib/marketing-copy.ts`, login shell legal line, `robots.ts` / `sitemap.ts`.

**Fix:** Google reviewers and new visitors can read what the broker is and what data it uses.

---

## REQ-017 — Search brief vs request details; evaluate without re-index

**Date:** 2026-10-27

**Requirement:** A living request has one JSON blob (`agent_requests.details`). Vector search is a five-key projection of that blob: `domain`, `objective`, `hard_constraints`, `soft_preferences`, `freeform_notes`. Everything else the agent adds is request context for evaluation, Q&A, and mediation. Patching the search core is `update_search_brief` (or a rewrite with `save_request`); it clears `indexed_at` and `view_filters`. Storing facts, answers, secondary constraints, or background is `update_request_details`; it does not re-index, does not clear `indexed_at`, and does not start a screen. Extra keys never enter the Chroma document. Pair screening and `answer_match_question` read the full public details. `JOB_EVALUATE` runs without `indexed_at`; `JOB_SCREEN` and `search_counterparties` still require an indexed brief. The match notebook stays for pair process, outstanding questions, and pair-only concessions. Reusable person facts go on details, not the notebook. Same-turn `update_notebook` plus `update_request_details` is allowed. Recording details does not auto-evaluate and does not tell the model to evaluate after the write.

**What was wrong:** One store and one `update_request` tool treated every new fact as a brief rewrite. `indexed_at` cleared, then `evaluate_pair` in the same turn failed with "This brief is not indexed." Failed evaluate jobs woke the broker and retried, looping the user-visible re-check. Extra context either never persisted (patch rebuilt canonical fields and dropped unknown keys) or would have been embedded into search if kept on the same document.

**Flow change:**

1. Who to retrieve is the search brief. Index only after `save_request` or `update_search_brief`.
2. Facts, answers, and secondary constraints are named extras on the same details blob. They help evaluate and mediation. They do not change retrieval until the brief itself changes.
3. After a this-user answer, store it on details. Re-screen stored ids with `evaluate_pair` when the broker decides; that job no longer waits for a new index.
4. Pair-only concessions and process stay in the match notebook.

**Code change:** `living_request.py` (`search_brief_dict`, `living_request_dict`, `apply_search_brief_patch`, `apply_details_extra_patch`), `request_tools.py` (`update_search_brief`, `update_request_details`; `budget`/`location`/`timeline` leave the canonical schema), `indexer.py` (five-key document), `request_jobs.py` (`JOB_EVALUATE` before the index gate), `titles.py`, `prompts.py`, `runtime.py`. Tests in `test_living_request.py`, `test_request_jobs.py`, `test_evaluate.py`, `test_prompts.py`, `test_titles.py`.

**Fix:** A hometown or rate answer can be stored and used to re-score a stored pair without dropping the request from the index. Search still only sees the five-key brief.

---

## REQ-018 — Failed jobs do not loop; screener JSON is an instance

**Date:** 2026-10-27

**Requirement:** A failed background job wakes the broker once. That `request_ready` turn must not enqueue another job of the same kind. `background_job` includes the clipped `error` and `retry_allowed: false`. The person writing again may enqueue freely. Screen/evaluate JSON parse failures still retry once inside the same job, with a correction that asks for a filled instance. Structured LLM calls send an instance hint, not a JSON Schema dump. A schema-shaped object with `properties` / `const` is unwrapped into values before Pydantic validate.

**What was wrong:** Failed jobs woke the broker with `retry that job` and an empty error field. The agent queued a new job of the same kind. Failed jobs are not open, so coalesce did not apply, and the chain ran until stopped by hand. Pair screening also appended LangChain JSON Schema format instructions; the model often echoed `properties` / `enum` instead of a filled `PairEvaluation`, which failed Pydantic and started that loop.

**Flow change:**

1. `request_ready` + `status=failed` refuses the same job kind. A later `user_message` may start that kind again.
2. Prompt: a failed job is finished; do not start the same job this turn; continue from `suggested_matches` or say you will try again.
3. Packet: real clipped error, `retry_allowed` false on failure.
4. Screener: instance JSON only. Silent retry adds a short “not a schema” line. Unwrap salvage when the model nested values under `properties`.

**Code change:** `request_jobs.py` (`JobRetryBlocked`, `job_packet`, silent-retry hint), `request_tools.py` / `search_tools.py` / `runtime.py`, `prompts.py`, `llm/client.py` (`unwrap_schema_echo`, `parse_structured_output`). Tests in `test_request_jobs.py`, `test_prompts.py`, `test_llm_client.py`.

**Fix:** A parse miss or worker error cannot enqueue the same kind forever. A schema-echo that still has values can screen instead of failing the job.

---

## REQ-019 — Structured parse retry is per call; one empty pair does not fail the screen

**Date:** 2026-10-27

**Requirement:** A structured LLM call that fails Pydantic or JSON parse retries once in that same call, with the previous output, the real validation error, and the required instance keys. The job worker does not rerun the whole screen or evaluate pipeline for a parse miss. Pair evaluation isolates failures: a candidate that still cannot be scored is skipped and listed on `background_job.errors`; scored pairs are stored. If every pair in the set still fails to parse, the job fails and `retry_allowed` stays false. Do not invent verdict or score. Do not re-run retrieval because one pair was empty.

**What was wrong:** An empty `{}` PairEvaluation failed `asyncio.gather` for the whole screen. The job-level silent retry discarded the completion and asked only for “not a JSON Schema,” so the second attempt could not correct missing `verdict` / `score` / `recommended_action`. One unusable score failed every candidate. The broker then saw a failed job and could not present the pairs that would have scored.

**Flow change:**

1. `invoke_structured_model` tries twice. The second human includes previous output, the parse error, and required keys.
2. `evaluate_pairs` keeps successful scores and records per-candidate errors.
3. A screen or evaluate job succeeds when at least one pair scored. Pair errors are on the packet. All-pair parse failure still fails the job.

**Code change:** `llm/client.py` (`invoke_structured_model` parse retry, `structured_retry_instruction`), `evaluate.py` (`evaluate_pairs` `return_exceptions`), `screening.py`, `request_jobs.py` (retired `_run_kind_with_parse_retry`), `job_packet.errors`, `prompts.py`. Tests in `test_llm_client.py`, `test_evaluate.py`, `test_suggestions.py`, `test_request_jobs.py`, `test_prompts.py`.

**Fix:** One empty screener JSON cannot wipe a screen that already has good scores. The retry can correct missing keys instead of repeating a generic schema hint.
