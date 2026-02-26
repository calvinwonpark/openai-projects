import json
import os
import sys
import urllib.error
import urllib.request


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "datasets", "rag_eval.jsonl")


def load_dataset(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def call_chat(user_text):
    url = f"{API_BASE_URL}/chat"
    payload = json.dumps({"message": user_text, "session_id": "eval-suite"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def evaluate_row(row, output):
    failures = []

    expected_language = row["expected_language"]
    if output.get("language") != expected_language:
        failures.append(f"language mismatch: expected={expected_language} got={output.get('language')}")

    refusal = output.get("refusal", {})
    is_refusal = bool(refusal.get("is_refusal"))
    should_refuse = bool(row.get("should_refuse"))
    if should_refuse and not is_refusal:
        failures.append("should_refuse=true but refusal.is_refusal=false")
    if not should_refuse:
        if is_refusal:
            failures.append("should_refuse=false but refusal.is_refusal=true")
        citations = output.get("citations", [])
        if len(citations) < 1:
            failures.append("expected non-refusal answer with >=1 citation")
        for idx, citation in enumerate(citations):
            quote = str(citation.get("quote", "")).strip()
            if not quote:
                failures.append(f"citation[{idx}] quote must be non-empty")

    must_cite_sources = row.get("must_cite_sources") or []
    if must_cite_sources:
        cited_sources = {c.get("source") for c in output.get("citations", [])}
        if not any(s in cited_sources for s in must_cite_sources):
            failures.append(
                f"expected one citation source in {must_cite_sources}, got {sorted(cited_sources)}"
            )

    return failures


def main():
    rows = load_dataset(DATASET_PATH)
    total = len(rows)
    failed = 0
    error_details = []

    for row in rows:
        row_id = row["id"]
        try:
            output = call_chat(row["user"])
            failures = evaluate_row(row, output)
            if failures:
                failed += 1
                error_details.append({"id": row_id, "failures": failures, "output": output})
                print(f"[FAIL] {row_id}: {'; '.join(failures)}")
            else:
                print(f"[PASS] {row_id}")
        except urllib.error.URLError as exc:
            failed += 1
            detail = f"request error: {exc}"
            error_details.append({"id": row_id, "failures": [detail]})
            print(f"[FAIL] {row_id}: {detail}")
        except Exception as exc:
            failed += 1
            detail = f"unexpected error: {exc}"
            error_details.append({"id": row_id, "failures": [detail]})
            print(f"[FAIL] {row_id}: {detail}")

    passed = total - failed
    print(f"\nSummary: total={total} passed={passed} failed={failed}")

    if failed > 0:
        print("\nFailure details:")
        print(json.dumps(error_details, ensure_ascii=False, indent=2))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
