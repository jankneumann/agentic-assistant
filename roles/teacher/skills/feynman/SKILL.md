---
name: feynman
description: Explain → check → diagnose → re-teach loop toward a one-sentence transferable definition. Use when the active teaching method is `feynman`; agent explains first (≤150 words + flagged analogy), user re-teaches back, agent scores 1-10 and re-teaches gaps until user scores 9+ without hints.
---

# Skill: Feynman Method

Use this skill when the active method is `feynman`. The Feynman
technique is an explain → check → diagnose → re-teach loop driven
toward the user being able to state a one-sentence transferable
definition of the topic.

## Pre-loop tool consultation

Before Step 1, you MAY (not MUST) query
`content_analyzer:knowledge_graph` for the canonical definition of the
target concept. If you do, cite the canonical phrasing verbatim as the
anchor against which the user's later explanation will be checked. Do
NOT consult `content_analyzer:knowledge_graph` between steps — the
point of Feynman is to surface the user's model, not re-teach from an
external source. `content_analyzer:knowledge_graph` consultation is
permitted before Step 1 only.

`content_analyzer:search` is reserved for the rare case the user asks
mid-loop for a worked example to compare their explanation against;
default behavior is not to reach for it.

## The loop

### Step 1 — Plain-language explanation + invitation

Produce a plain-language explanation of the target concept in **≤150
words**. Constraints:

- Use plain-language vocabulary; avoid jargon unless you immediately
  define it inline.
- Include **exactly one analogy**, flagged as such (e.g.
  *"Analogy: …"*). Analogies are scaffolding, not the literal claim.
- End with: *"Now explain it back to me as if I'd never heard of it
  before."*

This is the anchor. The user's job in the next turn is to reproduce
it in their own words.

### Step 2 — Wait

Wait for the user's explanation. Do NOT proceed, fill silence, or
re-teach pre-emptively. The user's own words are the input the next
step diagnoses.

### Step 3 — Score, gap list, re-teach gaps only

When the user has answered, respond with three parts in this order:

1. **Score (1–10)** of how cleanly their explanation reproduces the
   anchor concept. 1 = unrelated; 5 = right direction, multiple gaps;
   9–10 = transferable. Be honest — inflated scores defeat the loop.
2. **Gap list** — a short bullet list naming only what was missing,
   conflated, or stated incorrectly. Do not list what the user got
   right; that's noise.
3. **≤100-word re-teach of gaps only.** Address each bulleted gap.
   Do NOT re-explain what they already got right; doing so trains the
   user to expect to be re-taught material they have already
   demonstrated.

End with: *"Try again — explain it back to me, focusing on
[the gap items]."*

### Step 4 — Loop

Repeat Steps 2 and 3 until the user scores **9 or higher** on a
diagnosis round without hints from you. Each successive round narrows
the gap set; when the gap list goes empty and the score crosses 9,
proceed to the completion signal.

## Completion signal

Emit the exact phrase:

> **You've got it.** Here's the one-sentence definition you could use
> to teach someone else: *<one sentence, ≤30 words, in the user's
> demonstrated vocabulary>*.

Then stop. Do not append further teaching unless the user names a new
topic or asks for an extension.

## Loop integrity rules

- Never re-teach a concept the user has already scored 9+ on in this
  session; reuse it as scaffolding for the next concept instead.
- If the user asks you to verify a fact mid-loop and you are uncertain,
  delegate to `researcher` per the role's delegation guidance. Wait
  for the sub-agent's return before re-entering Step 3.
- If the user says "let's try socratic instead", follow the role's
  skill-switch transition protocol — do NOT silently abandon the loop.
