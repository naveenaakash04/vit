# Stage 3 Watch

`StudyWatch` runs the Stage 2 review crew over twelve progressive cuts while keeping an incremental graph, pending monitor escalations, adversarial-data decisions, a shared budget, and durable explanations.

Run from this directory:

```powershell
python -m stage3.watch --data-dir data --budget-ms 30000 --report-out stage3/surveillance_report.json
python -m unittest stage3.test_watch stage2.test_crew -v
```

The decision trace is written to `stage3/decision_log.jsonl`. Call `watch.explain("D-001")` to read an explanation from the recorded trace rather than reconstructing it from current data. `surveillance_summary.json` is the compact checked-in public summary; full report and decision JSON files are generated locally because they contain thousands of evidence records.
