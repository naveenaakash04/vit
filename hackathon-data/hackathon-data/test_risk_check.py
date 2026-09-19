import json
import urllib.request
import urllib.error
from pathlib import Path
from stage1.atlas import Atlas
from stage1.web import _build_subject_risk, _build_subject_replay

def main():
    atlas = Atlas("data", cut=12)
    atlas.graph.build()
    subjects = sorted(list(atlas.graph.by_subject.keys()))
    print(f"Loaded {len(subjects)} subjects from Cut 12 data.")

    # 1. Direct Python Evaluation
    print("\n--- 1. Evaluating Direct Functions ---")
    risk_distribution = {"Critical": 0, "High": 0, "Moderate": 0, "Low": 0}
    max_risk_sub = None
    max_risk_score = -1
    total_events = 0

    for s in subjects:
        risk = _build_subject_risk(s)
        lvl = risk["risk_level"]
        risk_distribution[lvl] = risk_distribution.get(lvl, 0) + 1
        if risk["risk_score"] > max_risk_score:
            max_risk_score = risk["risk_score"]
            max_risk_sub = s

        replay = _build_subject_replay(s)
        total_events += replay["event_count"]
        # Verify chronological order
        dates = [e["date"] for e in replay["events"]]
        assert dates == sorted(dates), f"Dates not chronological for {s}!"

    print(f"Risk Levels Distribution across all {len(subjects)} subjects:")
    for k, v in risk_distribution.items():
        print(f"  - {k}: {v} subjects")
    print(f"Total timeline events across all subjects: {total_events}")
    print(f"Highest Risk Subject: {max_risk_sub} (Score: {max_risk_score})")

    # Inspect the highest risk subject
    sample_risk = _build_subject_risk(max_risk_sub)
    print(f"\nDetailed Risk Profile for {max_risk_sub}:")
    print(json.dumps(sample_risk, indent=2))

    sample_replay = _build_subject_replay(max_risk_sub)
    print(f"\nReplay Timeline for {max_risk_sub} ({sample_replay['event_count']} events):")
    print("First 3 events:")
    print(json.dumps(sample_replay["events"][:3], indent=2))
    print("Last 3 events:")
    print(json.dumps(sample_replay["events"][-3:], indent=2))

    # 2. HTTP Server Endpoints Evaluation
    print("\n--- 2. Testing HTTP Server API Endpoints (http://127.0.0.1:8000) ---")
    base_url = "http://127.0.0.1:8000"
    
    # Test /api/risk/predict with valid subject
    url = f"{base_url}/api/risk/predict?subject_id={max_risk_sub}"
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    assert res["subject_id"] == max_risk_sub
    assert res["risk_score"] == max_risk_score
    print(f"GET {url} -> 200 OK, Score={res['risk_score']}, Level={res['risk_level']}")

    # Test /api/risk/replay with valid subject
    url = f"{base_url}/api/risk/replay?subject_id={max_risk_sub}"
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    assert res["subject_id"] == max_risk_sub
    assert res["event_count"] == sample_replay["event_count"]
    print(f"GET {url} -> 200 OK, Events={res['event_count']}")

    # Test parameter aliases (subject, usubjid, formatted string)
    for param_name in ["subject", "usubjid"]:
        url = f"{base_url}/api/risk/predict?{param_name}={max_risk_sub}"
        req = urllib.request.urlopen(url)
        res = json.loads(req.read().decode())
        assert res["subject_id"] == max_risk_sub
        print(f"GET {url} -> 200 OK (alias '{param_name}' working)")

    # Test formatted ref string (e.g. 'DS · 042-S01-010 · 1')
    url = f"{base_url}/api/risk/predict?subject_id=DS%20%C2%B7%20{max_risk_sub}%20%C2%B7%201"
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    assert res["subject_id"] == max_risk_sub
    print(f"GET {url} -> 200 OK (regex extraction working)")

    # Test global overview /api/risk/predict without subject parameter
    url = f"{base_url}/api/risk/predict"
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    assert isinstance(res, list)
    assert len(res) == len(subjects)
    print(f"GET {url} (overview) -> 200 OK, Returned {len(res)} subject risk profiles")

    # Test error handling when missing subject_id in /api/risk/replay
    try:
        urllib.request.urlopen(f"{base_url}/api/risk/replay")
        raise AssertionError("Expected 400 Bad Request for missing subject_id in replay")
    except urllib.error.HTTPError as e:
        assert e.code == 400
        print(f"GET {base_url}/api/risk/replay (no param) -> 400 Bad Request (handled correctly)")

    # Test unknown subject ID
    url = f"{base_url}/api/risk/predict?subject_id=999-S99-999"
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    assert res["risk_score"] == 0 and res["risk_level"] == "Low"
    print(f"GET {url} (unknown subject) -> 200 OK, Returned default baseline Low risk")

    url = f"{base_url}/api/risk/replay?subject_id=999-S99-999"
    req = urllib.request.urlopen(url)
    res = json.loads(req.read().decode())
    assert res["event_count"] == 0 and res["events"] == []
    print(f"GET {url} (unknown subject) -> 200 OK, Returned 0 events")

    print("\n[SUCCESS] All Risk Prediction and Risk Replay checks passed 100%!")

if __name__ == "__main__":
    main()
