# Skill: Request Triage

## When to use
Every incoming message (runs implicitly).

## Workflow
1. Classify intent: question, task, briefing, communication, scheduling,
   research, code, meta
2. Assess complexity: simple (handle directly) vs complex (delegate)
3. Check persona context: are required tools available?
4. Route per triage framework

## Signals
- "?" or question words → question/research
- "write/draft/compose" → writer sub-role
- "plan/roadmap/strategy" → planner sub-role
- "code/bug/PR/repo" → coder sub-role
- "briefing/update/news" → handle directly
- "email/message" → handle with persona-appropriate tools
