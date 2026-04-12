# Skill: Task Delegation to Sub-Agents

## When to use
Task is too complex to handle directly.

## Workflow
1. Classify task type (research, writing, coding, planning)
2. Select appropriate sub-role
3. Compose delegation brief: objective, context, constraints, format, priority
4. Spawn sub-agent with role + current persona
5. Monitor progress
6. Review output and integrate

## Decision Rules
- Multi-domain → spawn multiple sub-agents in parallel
- Dependencies → spawn sequentially, pass output forward
- Insufficient output → feedback and re-delegate
- Never exceed `delegation.max_concurrent`
