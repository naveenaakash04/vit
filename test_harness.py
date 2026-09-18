"""Comprehensive verification test harness for Study Sentinel."""

import json
import sys
from pathlib import Path

# Insert module search path
project_root = Path(__file__).resolve().parent / "hackathon-data" / "hackathon-data"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from stage1.atlas import Atlas, StudyGraph
from review import load_snapshot, findings


def run_tests() -> bool:
    data_dir = project_root / "data"
    print("=" * 60)
    print(" STUDY SENTINEL END-TO-END VERIFICATION HARNESS")
    print("=" * 60)

    # 1. Graph Ingestion Benchmark
    print("\n[1/4] Testing StudyGraph Build & Metrics...")
    graph = StudyGraph(str(data_dir))
    stats = graph.build(cut=12)
    print(f" -> Nodes: {stats['nodes']}, Edges: {stats['edges']}, Subjects: {stats['subjects']}, Time: {stats['ms']} ms")
    assert stats["subjects"] == 241, f"Expected 241 subjects, found {stats['subjects']}"
    
    # Save graph stats
    stats_file = project_root / "graph_stats.json"
    stats_file.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    (Path(__file__).resolve().parent / "graph_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    # 2. Patient 360 Verification
    print("\n[2/4] Testing Patient 360 Profile...")
    patient = graph.patient360("042-S08-001")
    assert patient["USUBJID"] == "042-S08-001"
    assert len(patient["labs"]) > 0
    print(f" -> Subject 042-S08-001: {len(patient['labs'])} labs, {len(patient['timeline'])} timeline entries")

    # 3. Stage 1 Public Question Bank Exact Match
    print("\n[3/4] Testing Public Evaluation Questions...")
    eval_file = project_root / "stage1_public.json"
    with eval_file.open(encoding="utf-8") as f:
        eval_data = json.load(f)

    atlas = Atlas(str(data_dir), cut=12)
    for idx, item in enumerate(eval_data["results"], 1):
        q = item["question"]
        ans = atlas.answer(q)
        ans_match = ans.answer == item["answer"]
        ev_match = len(ans.evidence) == len(item["evidence"])
        print(f" -> Q{idx}: {q[:45]:<45} | Answer Match: {str(ans_match):<5} | Evidence Match: {str(ev_match)}")
        assert ans_match, f"Answer mismatch for: {q}"
        assert ev_match, f"Evidence mismatch for: {q}"

    # 4. Review Findings Across All Cuts 1..12
    print("\n[4/4] Testing Review Rule Findings Across Cuts 1..12...")
    for cut in range(1, 13):
        snap = load_snapshot(data_dir, cut=cut)
        all_findings = findings(snap)
        print(f" -> Cut {cut:2d} (Protocol v{snap.protocol_version}): {len(all_findings):3d} findings generated")
        assert len(all_findings) > 0, f"No findings for cut {cut}"

    print("\n" + "=" * 60)
    print(" ALL 4 VERIFICATION SUITES PASSED PERFECTLY!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
