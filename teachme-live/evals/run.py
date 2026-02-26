import json
import os
import sys
import urllib.error
import urllib.request

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "datasets", "transcript_eval.jsonl")


def load_dataset(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def call_chat_text(transcript):
    url = f"{API_BASE_URL}/chat_text"
    payload = json.dumps({"transcript": transcript, "session_id": "eval-suite"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def contains_question_prompt(answer_text):
    text = (answer_text or "").lower()
    question_mark = "?" in text
    known_phrases = ["could you", "can you", "which", "what", "어떤", "무엇", "알려주실 수", "말씀해 주"]
    return question_mark or any(phrase in text for phrase in known_phrases)


def evaluate_row(row, output):
    failures = []
    expected = row["expected"]

    should_refuse = bool(expected["should_refuse"])
    actual_refuse = bool(output.get("refusal", {}).get("is_refusal"))
    if should_refuse != actual_refuse:
        failures.append(f"refusal mismatch: expected={should_refuse} got={actual_refuse}")

    expected_language = expected["language"]
    actual_language = output.get("language")
    if expected_language != actual_language:
        failures.append(f"language mismatch: expected={expected_language} got={actual_language}")

    should_ask = bool(expected["should_ask_clarifying"])
    if should_ask and not contains_question_prompt(output.get("answer", "")):
        failures.append("expected clarifying question but response did not look like a question")

    return failures


def main():
    rows = load_dataset(DATASET_PATH)
    total = len(rows)
    failed = 0
    details = []

    for row in rows:
        row_id = row["id"]
        try:
            output = call_chat_text(row["transcript"])
            failures = evaluate_row(row, output)
            if failures:
                failed += 1
                details.append({"id": row_id, "failures": failures, "output": output})
                print(f"[FAIL] {row_id}: {'; '.join(failures)}")
            else:
                print(f"[PASS] {row_id}")
        except urllib.error.URLError as exc:
            failed += 1
            detail = f"request error: {exc}"
            details.append({"id": row_id, "failures": [detail]})
            print(f"[FAIL] {row_id}: {detail}")
        except Exception as exc:
            failed += 1
            detail = f"unexpected error: {exc}"
            details.append({"id": row_id, "failures": [detail]})
            print(f"[FAIL] {row_id}: {detail}")

    passed = total - failed
    print(f"\nSummary: total={total} passed={passed} failed={failed}")
    if failed:
        print("\nFailure details:")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
