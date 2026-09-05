"""
Diagnostic: sweep text_score to find whether there's a clean gap between
  (a) coincidence false-positives (unrelated txns, similar amount+date), and
  (b) genuine MONEY_DATE_LOCK rescues (real match, garbled/reformatted text)

This tells us whether a text floor is a safe fix, and if so, exactly where to set it,
instead of picking a number by feel.
"""
import csv

def load_answer_key(path):
    true_matches = set()
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["bank_txn_id"] != "NONE" and row["ledger_txn_id"] != "NONE" \
                    and row["category"] != "ONE_TO_MANY_SPLIT":
                true_matches.add((row["bank_txn_id"], row["ledger_txn_id"]))
    return true_matches


def sweep():
    true_matches = load_answer_key("answer_key.csv")

    false_positive_scores = []
    genuine_rescue_scores = []

    with open("audit_log.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["rule_fired"] != "MONEY_DATE_LOCK":
                continue
            pair = (row["bank_txn_id"], row["ledger_txn_id"])
            t_score = float(row["text_score"])
            if pair in true_matches:
                genuine_rescue_scores.append(t_score)
            else:
                false_positive_scores.append(t_score)

    false_positive_scores.sort()
    genuine_rescue_scores.sort()

    print("=" * 60)
    print("TEXT FLOOR DIAGNOSTIC (for MONEY_DATE_LOCK rule)")
    print("=" * 60)
    print(f"Coincidence false-positive text_scores ({len(false_positive_scores)}):")
    print(f"  {false_positive_scores}")
    print()
    print(f"Genuine garbled-text rescue text_scores ({len(genuine_rescue_scores)}):")
    print(f"  {genuine_rescue_scores}")
    print()

    if not false_positive_scores or not genuine_rescue_scores:
        print("Not enough data in one of the two groups to find a gap.")
        print("=" * 60)
        return

    max_fp = max(false_positive_scores)
    min_rescue = min(genuine_rescue_scores)

    if max_fp < min_rescue:
        floor = round((max_fp + min_rescue) / 2, 3)
        print(f"CLEAN GAP FOUND: false-positives top out at {max_fp}, "
              f"genuine rescues start at {min_rescue}.")
        print(f"Recommended floor: {floor}")
        print(f"This floor would remove all {len(false_positive_scores)} false positives")
        print(f"while keeping all {len(genuine_rescue_scores)} genuine rescues.")
    else:
        overlap = [s for s in false_positive_scores if s >= min_rescue]
        print(f"NO CLEAN GAP: {len(overlap)} false-positive score(s) overlap with the "
              f"genuine-rescue range.")
        print(f"A text floor here would trade recall for precision, not fix it for free.")
        print(f"Recommendation: keep the rule as-is, document this as a known limitation, "
              f"and note the real production fix would be an independent field "
              f"(e.g. customer/account ID) rather than a stricter text threshold.")
    print("=" * 60)


if __name__ == "__main__":
    sweep()
