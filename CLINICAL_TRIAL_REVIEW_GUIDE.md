# Clinical-Trial Review Project: Concepts & Architecture Explained

---

## 1. What is a Clinical Trial?

A **clinical trial** is a scientific study conducted with human volunteers to determine whether a medical treatment, drug, device, or procedure is **safe** and **effective**.

```
Researchers develop medicine (e.g. for Diabetes)
                     │
                     ▼
    Controlled study with human volunteers
                     │
                     ▼
  Collect measurements & adverse event logs
                     │
                     ▼
    Analyze efficacy (did it work?) and safety
```

### Key Components of a Trial:
- 👥 **Participants (`DM` / Demographics):** Who took part (Age, Sex, Site, Arm: Drug vs Placebo).
- 💊 **Treatment (`EX` / Exposure):** What dose was administered and when.
- 🧪 **Laboratory Tests (`LB` / Labs):** Blood sugar, liver enzymes, kidney function.
- ⚠️ **Side Effects (`AE` / Adverse Events):** Complications, hospitalizations, severity.
- 💊 **Other Medications (`CM` / Concomitant Meds):** Allowed or prohibited drugs taken concurrently.
- 🚪 **Study Conclusion (`DS` / Disposition):** Completed study vs early discontinuation.

---

## 2. What Does "Review" Mean?

In clinical trials, **review** means systematically auditing, monitoring, and evaluating trial data to ensure:
1. **Patient Safety:** Catch severe toxicity early (e.g. liver injury / Hy's Law).
2. **Protocol Compliance:** Check if doctors gave the correct dose and scheduled visits within allowed time windows.
3. **Data Integrity:** Track corrections across weekly data cuts without losing evidence.

```
       Raw Clinical Data Cuts (CSVs / Tables)
                         │
                         ▼
        Ingest & Apply Historical Corrections
                         │
                         ▼
        Run Automated Protocol & Safety Checks
                         │
                         ▼
       Generate Evidence Citations (Domain · ID · Seq)
                         │
                         ▼
      Synthesize Findings for Medical Monitors & Sites
```

---

## 3. How AI & Software Assist Clinical Trial Review

| Manual Review | AI / Automated Sentinel Review |
|---|---|
| Reviewers manually read thousands of rows in spreadsheets | High-speed in-memory graph processes 27,000+ records in <50 ms |
| Prone to missing subtle date deviations or unit differences | Automatically flags visit window shifts and converts units (`ukat/L` $\to$ `U/L`) |
| Unstructured human notes | Exact evidence triples: `(Domain, USUBJID, Sequence)` |
| Risk of bias or hallucination | 100% deterministic rules with truthful "no finding" reporting |

---

## 4. Key Clinical Safety Rules Implemented

### 1. Hy's Law (Severe Drug-Induced Liver Injury)
- **Criteria:** ALT or AST $> 3\times$ Upper Limit of Normal (ULN) **combined with** Total Bilirubin $> 2\times$ ULN within 14 days of each other.
- **Handling:** Converts units if a local lab reports in $\mu\text{kat/L}$ ($1\,\mu\text{kat/L} = 60\,\text{U/L}$).

### 2. Dosing Adherence
- **Drug Arm:** Must receive exact target dose (e.g. 10 mg).
- **Placebo Arm:** Must receive 0 mg.
- Any discrepancy is flagged as a dosing error.

### 3. Visit Window Deviations
- Protocols specify target visit days (e.g., Week 2 = Day 14, Week 24 = Day 168).
- Protocol v1 allows $\pm 7$ days; Protocol v2 & v3 tighten the window to $\pm 3$ days.

### 4. Prohibited Medications
- Protocol v1 & v2: Systemic Glucocorticoids prohibited.
- Protocol v3 Amendment: Sulfonylureas also prohibited.

---

## 5. System Architecture & Information Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      DATA LAYER                             │
│  CDISC Datasets: DM, AE, LB, VS, EX, CM, DS, MH, Cuts       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   INGESTION & GRAPH INDEX                   │
│  - Filter records by cut_available <= N                     │
│  - Apply latest historical corrections                      │
│  - Build O(1) indexed lookup tables in StudyGraph           │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌─────────────────────────────┐     ┌─────────────────────────────┐
│    ATLAS NATURAL LANGUAGE   │     │    PROTOCOL AUDIT RULES     │
│       ANSWERING ENGINE      │     │           ENGINE            │
│  - Hy's Law detector        │     │  - Eligibility checks       │
│  - Dosing error finder      │     │  - Visit window deviations  │
│  - Discontinuation counter  │     │  - Prohibited medications   │
│  - Date-windowed lookups    │     │  - Serious adverse events   │
└──────────────┬──────────────┘     └──────────────┬──────────────┘
               │                                   │
               └──────────────────┬────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                  EVIDENCE CITATION SYSTEM                   │
│   Outputs exact verified triple: (Domain, USUBJID, Seq)     │
│   Truthful "None found" reporting when clean                │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  INTERACTIVE REVIEW DESK                    │
│   - Localhost Web Application (http://localhost:8000)       │
│   - REST API Endpoints (/api/summary, /api/answer, /api/pt) │
│   - Patient 360 Longitudinal Trajectory Visualizer          │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Summary in One Sentence

> **Study Sentinel** is an automated clinical trial review engine that ingests longitudinal patient trial data across progressive cuts, identifies protocol deviations and life-threatening safety signals, and returns exact, evidence-backed answers with zero hallucination.
