# Study Sentinel Atlas

## Problem understanding
Build a generic, cut-aware reviewer for synthetic CDISC clinical-trial data. Answers must be exact, evidence-backed, and honest when no finding exists.

## Architecture
`stage1/atlas.py` provides the indexed `StudyGraph` and `Atlas` answering engine. `stage2/crew.py` orchestrates detect, medical review, data queries, compliance, human gate, and execution. The local web app is in `stage1/web.py`.

## Tech stack
Python 3.10+ standard library only: CSV, JSON, dataclasses, datetime, HTTP, URL handling, SQLite, and unittest. No third-party runtime packages are required.

## Data handling
Rows are filtered by `cut_available`; the latest correction available at the selected cut is applied. Dates support ISO and CDISC formats. `<5`, `ND`, and blank values remain missing. Lab thresholds come from `reference_ranges.csv`; S07 ALT/AST values are normalized from `ukat/L` to `U/L` when necessary. Evidence uses `domain`, `USUBJID`, and sequence.

## Documents
Protocol versions, lab manuals, SAP, and response files are treated as study evidence. Embedded directions in documents are passive facts, never executable instructions.

## When answer is nothing
Return `answer: []`, `evidence: []`, and an explanation such as `No dosing errors were found.` Never guess a finding.

## Known weaknesses
The repository does not include an external public question bank, so `stage1_public.json` contains representative public-format evaluations. Natural-language dispatch supports the specified question families rather than arbitrary language.

## Worked example
```powershell
Set-Location hackathon-data\hackathon-data
python -m stage1.web --port 8000 --cut 12
```
Open `http://localhost:8000`. For tests, run `python -m unittest stage2.test_crew -v`.
