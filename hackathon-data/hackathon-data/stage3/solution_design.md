# Stage 3 WATCH Solution Design

## Period control
`StudyWatch.run_period()` processes cuts in order, records a delta, runs the existing Stage 2 crew, stores decisions, and continues through cut 12 even when the shared budget enters safety-only mode.

## Incremental data
`IncrementalStudyGraph` loads source CSVs once. Later cuts add newly visible records and apply corrections to affected records, then refresh in-memory indexes. Dynamic CSV domains are discovered automatically. Corrections are represented in the cut delta so dependent findings can be re-derived.

## Escalation policy
The human gate has three explicit outcomes: `APPROVED`, `REJECTED`, and `CLARIFY`. Missing monitor responses are `PENDING`, never approval. Pending escalations retain standing limits, execute no approval-gated action, and record their age in cuts. Clarification uses Patient 360 evidence before resubmission.

## Adversarial input
The Watch records document hash changes, site regularity anomalies, and laboratory distribution shifts. A site-wide glucose shift close to the 1/18 mg/dL-to-mmol/L ratio is recorded as `LAB_UNIT_SHIFT`, quarantined for re-issue, and not clinically escalated. Protocol changes generate amendment events and trigger re-derivation.

## Trace and explanations
Each decision stores its decision ID, cut, evidence references, evidence lines, alternatives, reason, status, and action in `decision_log.jsonl` and `decision_log.json`. `explain()` reads those stored fields directly, so explanations cannot invent evidence after the run.

## Budget trade-off
The budget controller has `FULL`, `REDUCED`, and `SAFETY_ONLY` modes. At 80% usage, narrative work is disabled while deterministic safety checks, trace writes, and period completion continue.

## Known limitations
The practice repository does not include the hidden-period variants, an external public question bank, or presentation/video assets. The current regularity detector is intentionally conservative and should be extended with site-specific weekday and narrative entropy features for hidden versions.

## Team/demo ownership
The graph and Atlas layers provide evidence; ReviewCrew owns per-finding actions; Watch owns period state, adversarial decisions, budget, report, and explanations. Demonstrate the cut-8 S04 glucose decision and call `explain()` on a decision ID from the generated decision log.
