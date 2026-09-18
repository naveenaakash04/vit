# Stage 2 Monitor Crew

## Overview
This Stage 2 implementation keeps the Stage 1 Atlas interface intact and adds a six-node review flow around it. The core design is deterministic and evidence-first: each decision is derived from the actual graph and the protocol version in force for the selected cut.

## Six-node architecture
1. detect — run the existing Stage 1 Atlas over the requested cut and collect findings from the actual protocol review rules.
2. medical_review — classify each finding as monitor-only, query, or escalation using evidence, seriousness, plausibility, and the protocol definition.
3. data_manager — turn data-quality issues into actionable record-specific queries, suppressing duplicates on exact record keys.
4. compliance — re-evaluate the subject and site using the protocol version actually in force for the cut, not a passed-in assumption.
5. human_gate — submit escalations and handle APPROVED, REJECTED, and CLARIFY responses.
6. execute — assemble the final ReviewReport with findings, queries, escalations, deviations, actions, and the persisted trace.

## Persistent memory and deduplication
Memory is kept in a small SQLite store under the repo so repeated `run_cycle()` calls retain prior query and escalation keys across restarts. Duplicate queries are suppressed by a stable record key based on domain, subject, sequence, and finding code. Rejected escalations are recorded and not re-escalated later. Site-level recurring issues accumulate a site flag, and unanswered queries remain open instead of being retried blindly.

## Approval, rejection, and clarification
- APPROVED: execute the action and record the decision in the trace.
- REJECTED: downgrade to monitoring with the monitor reason preserved; remember that rejection to avoid later re-escalation.
- CLARIFY: ask the graph for the missing evidence, answer with citations, and resubmit instead of rejecting.

## Protocol version selection and mid-stage changes
The review crew loads the protocol snapshot directly from the study cut metadata, then rechecks findings using the protocol version effective for that cut. This ensures changes from earlier to later protocol versions are reflected in compliance checks and trace entries.

## Trace format and storage
Every node writes trace entries immediately with a timestamp, node name, cut, protocol version, action, evidence, and reason. Traces are written to the JSONL file under the stage2 directory and also kept in SQLite for persistence.

## Run commands
- python -m unittest stage2.test_crew -v
- python -m stage1.web --port 8000

## Status
This implementation is intentionally limited to the Stage 2 specification and keeps Stage 1 unchanged.
