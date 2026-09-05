"""
Grades matcher.py's output (audit_log.csv) against the hidden answer_key.csv.
This is NOT part of the matcher itself -- it's how we PROVE the accuracy number
we report, instead of just asserting it.
"""
import csv

def load_answer_key(path):
    true_matches = set()      # set of (bank_id, ledger_id) that are genuinely correct
    should_be_unmatched_bank = set()
    should_be_unmatched_ledger = set()
    one_to_many = {}

    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            b, l, cat = row["bank_txn_id"], row["ledger_txn_id"], row["category"]
            if cat == "ONE_TO_MANY_SPLIT":
                one_to_many[b] = set(l.split("+"))
                continue
            if b != "NONE" and l != "NONE":
                true_matches.add((b, l))
            elif b != "NONE" and l == "NONE":
                should_be_unmatched_bank.add(b)
            elif b == "NONE" and l != "NONE":
                should_be_unmatched_ledger.add(l)

    return true_matches, should_be_unmatched_bank, should_be_unmatched_ledger, one_to_many


def load_predicted_matches(path):
    predicted = set()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            predicted.add((row["bank_txn_id"], row["ledger_txn_id"]))
    return predicted


def grade():
    true_matches, unmatched_bank, unmatched_ledger, one_to_many = load_answer_key("answer_key.csv")
    predicted = load_predicted_matches("audit_log.csv")

    true_positives = predicted & true_matches
    false_positives = predicted - true_matches
    false_negatives = true_matches - predicted

    # One-to-many cases: matcher isn't designed to split, so these will show as
    # false negatives/positives -- report them separately rather than hide them.
    otm_bank_ids = set(one_to_many.keys())
    otm_related_fp = [p for p in false_positives if p[0] in otm_bank_ids]
    otm_related_fn = [f for f in false_negatives if f[0] in otm_bank_ids]

    genuine_fp = [p for p in false_positives if p[0] not in otm_bank_ids]
    genuine_fn = [f for f in false_negatives if f[0] not in otm_bank_ids]

    precision = len(true_positives) / len(predicted) if predicted else 0
    recall = len(true_positives) / len(true_matches) if true_matches else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print("=" * 60)
    print("ACCURACY REPORT (graded against hidden answer key)")
    print("=" * 60)
    print(f"True matches in ground truth: {len(true_matches)}")
    print(f"Matches the matcher claimed:  {len(predicted)}")
    print()
    print(f"Correct matches (true positives):  {len(true_positives)}")
    print(f"Wrong matches (false positives):    {len(genuine_fp)}  <- dangerous ones")
    print(f"Missed matches (false negatives):   {len(genuine_fn)}")
    print()
    print(f"Precision: {precision*100:.1f}%  (of claimed matches, % actually correct)")
    print(f"Recall:    {recall*100:.1f}%  (of true matches, % successfully found)")
    print(f"F1 score:  {f1*100:.1f}%")
    print()
    if genuine_fp:
        print(f"FALSE POSITIVES (matcher wrongly matched these -- REVIEW THESE):")
        for fp in genuine_fp:
            print(f"  bank={fp[0]} <-> ledger={fp[1]}")
    if otm_related_fp or otm_related_fn:
        print()
        print(f"One-to-many split cases (known limitation, {len(otm_bank_ids)} groups in data):")
        print(f"  These were not designed to be caught by pairwise matching.")
    print("=" * 60)


if __name__ == "__main__":
    grade()
