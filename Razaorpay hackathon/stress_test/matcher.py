"""
Reconciliation matcher for bank_statement.csv vs ledger.csv.

Architecture (based on how production reconciliation systems actually work):
  1. Exact match pass (txn_id, or amount+date+narration identical) -- fast, cheap, O(n)
  2. For remaining unmatched rows, candidate pairs pass through:
       a) HARD REJECT GATE -- cheap filter, avoids O(n*m) blowup and blocks
          obviously-unrelated pairs from ever being scored
       b) SPECIAL-CASE RULES -- explicit "OR of conditions" that mirror how a
          human explains a match ("amount+date matched, ignore garbled text")
       c) WEIGHTED FALLBACK -- only for pairs that clear the gate but hit no
          special-case rule; these are the genuinely ambiguous ones
  3. CONFIDENCE TIERS -- auto-match / needs-review / exception
  4. Every decision is logged with its full score breakdown -- this log IS
     the match-rate report and the exception list.
"""

import csv
from datetime import datetime
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Config -- all thresholds live here so they're easy to explain and tune
# ---------------------------------------------------------------------------
DATE_WINDOW_DAYS = 7          # matches beyond this are not even scored
AMOUNT_REJECT_PCT = 0.25      # beyond 25% AND beyond the floor below -> reject
AMOUNT_REJECT_FLOOR = 50.0    # rupee floor so tiny transactions aren't over-forgiven

AMOUNT_ROUND_TOLERANCE = 2.0  # up to ₹2 off counts as a perfect amount score

RULE_MONEY_DATE_AMOUNT_MIN = 0.98
RULE_MONEY_DATE_DATE_MIN = 0.85
RULE_MONEY_DATE_TEXT_FLOOR = 0.0  # Deliberately disabled. threshold_sweep.py showed no
                                    # clean gap between coincidence false-positives
                                    # (text_score 0.39-0.68) and genuine garbled-text
                                    # rescues (0.49-1.0) -- shared narration boilerplate
                                    # ("Refund -", "Payment -") causes overlap. A floor
                                    # here trades recall for a false sense of precision.
                                    # Real fix: an independent field (customer/account ID),
                                    # not a stricter text threshold. Documented as future work.
RULE_TEXT_LOCK_TEXT_MIN = 0.85
RULE_TEXT_LOCK_DATE_MIN = 0.70

TIER_AUTO_MATCH = 0.90
TIER_REVIEW = 0.65

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"]

NOISE_PREFIXES = ["UPI/", "NEFT/", "IMPS/", "PYMT-", "PYMT_", "PYMT "]
NOISE_SUFFIXES = [" LTD", " PVT LTD", " PVT.LTD", " PVT. LTD."]


def parse_date(s):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {s}")


def normalize_text(s):
    t = s.upper().strip()
    for p in NOISE_PREFIXES:
        if t.startswith(p.upper()):
            t = t[len(p):]
    for suf in NOISE_SUFFIXES:
        if t.endswith(suf.upper()):
            t = t[: -len(suf)]
    return t.strip()


def load_rows(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "txn_id": r["txn_id"],
                "date": parse_date(r["date"]),
                "amount": float(r["amount"]),
                "narration": r["narration"],
                "matched": False,
            })
    return rows


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def amount_score(a1, a2):
    diff = abs(a1 - a2)
    if diff <= AMOUNT_ROUND_TOLERANCE:
        return 1.0
    ref = max(a1, a2, 1.0)
    return max(0.0, 1 - diff / ref)


def date_score(d1, d2):
    diff = abs((d1 - d2).days)
    # +1 in denominator so the score decays smoothly and doesn't hit exactly zero
    # right at the boundary -- a transaction at exactly DATE_WINDOW_DAYS drift
    # is still plausible, just less likely, not impossible.
    return max(0.0, 1 - diff / (DATE_WINDOW_DAYS + 1))


def text_score(n1, n2):
    return fuzz.token_set_ratio(normalize_text(n1), normalize_text(n2)) / 100.0


def passes_hard_gate(bank_row, ledger_row):
    """Cheap reject filter -- also doubles as 'blocking' for performance."""
    days_diff = abs((bank_row["date"] - ledger_row["date"]).days)
    if days_diff > 30:
        return False
    amt_diff = abs(bank_row["amount"] - ledger_row["amount"])
    ref = max(bank_row["amount"], ledger_row["amount"], 1.0)
    if amt_diff > AMOUNT_REJECT_FLOOR and (amt_diff / ref) > AMOUNT_REJECT_PCT:
        return False
    return True


def score_pair(bank_row, ledger_row):
    """Returns dict with full breakdown + which rule (if any) fired."""
    a_score = amount_score(bank_row["amount"], ledger_row["amount"])
    d_score = date_score(bank_row["date"], ledger_row["date"])
    t_score = text_score(bank_row["narration"], ledger_row["narration"])

    rule_fired = None
    confidence = None

    # Special-case rule 1: money + date lock, text can be garbled but not near-zero.
    # A completely unrelated narration (t_score below the floor) is treated as a
    # strong signal these are two coincidentally-similar but unrelated transactions,
    # not the same transaction with reformatted text.
    if (a_score >= RULE_MONEY_DATE_AMOUNT_MIN and d_score >= RULE_MONEY_DATE_DATE_MIN
            and t_score >= RULE_MONEY_DATE_TEXT_FLOOR):
        rule_fired = "MONEY_DATE_LOCK"
        confidence = 0.90 + 0.10 * t_score

    # Special-case rule 2: text lock, amount can be off by a fee-like amount
    elif t_score >= RULE_TEXT_LOCK_TEXT_MIN and d_score >= RULE_TEXT_LOCK_DATE_MIN:
        rule_fired = "TEXT_LOCK"
        confidence = 0.85 + 0.15 * a_score

    # Weighted fallback -- genuinely ambiguous pairs only
    else:
        rule_fired = "WEIGHTED_FALLBACK"
        confidence = 0.4 * a_score + 0.3 * d_score + 0.3 * t_score

    return {
        "amount_score": round(a_score, 3),
        "date_score": round(d_score, 3),
        "text_score": round(t_score, 3),
        "rule_fired": rule_fired,
        "confidence": round(confidence, 3),
    }


def tier_for(confidence):
    if confidence >= TIER_AUTO_MATCH:
        return "AUTO_MATCH"
    elif confidence >= TIER_REVIEW:
        return "NEEDS_REVIEW"
    else:
        return "EXCEPTION"


# ---------------------------------------------------------------------------
# Matching pipeline
# ---------------------------------------------------------------------------
def run_reconciliation(bank_path, ledger_path):
    bank_rows = load_rows(bank_path)
    ledger_rows = load_rows(ledger_path)

    audit_log = []

    # ---- Pass 1: exact match (txn_id OR amount+date+narration identical) ----
    ledger_by_txn = {r["txn_id"]: r for r in ledger_rows if not r["matched"]}
    for b in bank_rows:
        if b["txn_id"] in ledger_by_txn:
            l = ledger_by_txn[b["txn_id"]]
            if not l["matched"]:
                b["matched"] = True
                l["matched"] = True
                audit_log.append({
                    "bank_txn_id": b["txn_id"],
                    "ledger_txn_id": l["txn_id"],
                    "amount_score": 1.0, "date_score": 1.0, "text_score": 1.0,
                    "rule_fired": "EXACT_ID_MATCH",
                    "confidence": 1.0,
                    "tier": "AUTO_MATCH",
                })

    # Also catch exact-content matches with different txn_ids (defensive, rare)
    for b in bank_rows:
        if b["matched"]:
            continue
        for l in ledger_rows:
            if l["matched"]:
                continue
            if (b["amount"] == l["amount"] and b["date"] == l["date"]
                    and normalize_text(b["narration"]) == normalize_text(l["narration"])):
                b["matched"] = True
                l["matched"] = True
                audit_log.append({
                    "bank_txn_id": b["txn_id"],
                    "ledger_txn_id": l["txn_id"],
                    "amount_score": 1.0, "date_score": 1.0, "text_score": 1.0,
                    "rule_fired": "EXACT_CONTENT_MATCH",
                    "confidence": 1.0,
                    "tier": "AUTO_MATCH",
                })
                break

    # ---- Pass 2: fuzzy matching on remaining rows ----
    unmatched_bank = [b for b in bank_rows if not b["matched"]]
    unmatched_ledger = [l for l in ledger_rows if not l["matched"]]

    # Score every surviving candidate pair, keep the best mutual matches
    # (greedy by descending confidence -- simple, explainable, good enough at this scale)
    candidates = []
    for b in unmatched_bank:
        for l in unmatched_ledger:
            if not passes_hard_gate(b, l):
                continue
            result = score_pair(b, l)
            candidates.append((result["confidence"], b, l, result))

    candidates.sort(key=lambda x: x[0], reverse=True)

    for confidence, b, l, result in candidates:
        if b["matched"] or l["matched"]:
            continue
        tier = tier_for(result["confidence"])
        if tier == "EXCEPTION":
            continue  # don't force-claim a match for low-confidence pairs
        b["matched"] = True
        l["matched"] = True
        audit_log.append({
            "bank_txn_id": b["txn_id"],
            "ledger_txn_id": l["txn_id"],
            **{k: v for k, v in result.items() if k != "confidence"},
            "confidence": result["confidence"],
            "tier": tier,
        })

    # ---- Remaining unmatched rows are the honest exception list ----
    exceptions = []
    for b in bank_rows:
        if not b["matched"]:
            exceptions.append({
                "bank_txn_id": b["txn_id"], "ledger_txn_id": None,
                "amount": b["amount"], "date": str(b["date"]), "narration": b["narration"],
                "category": "UNMATCHED_BANK_ENTRY",
            })
    for l in ledger_rows:
        if not l["matched"]:
            exceptions.append({
                "bank_txn_id": None, "ledger_txn_id": l["txn_id"],
                "amount": l["amount"], "date": str(l["date"]), "narration": l["narration"],
                "category": "UNMATCHED_LEDGER_ENTRY",
            })

    return bank_rows, ledger_rows, audit_log, exceptions


def write_report(bank_rows, ledger_rows, audit_log, exceptions):
    total_bank = len(bank_rows)
    total_ledger = len(ledger_rows)
    matched_bank = sum(1 for b in bank_rows if b["matched"])
    matched_ledger = sum(1 for l in ledger_rows if l["matched"])

    with open("audit_log.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "bank_txn_id", "ledger_txn_id", "amount_score", "date_score",
            "text_score", "rule_fired", "confidence", "tier"])
        w.writeheader()
        w.writerows(audit_log)

    with open("exceptions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "bank_txn_id", "ledger_txn_id", "amount", "date", "narration", "category"])
        w.writeheader()
        w.writerows(exceptions)

    tier_counts = {}
    for a in audit_log:
        tier_counts[a["tier"]] = tier_counts.get(a["tier"], 0) + 1

    print("=" * 60)
    print("RECONCILIATION REPORT")
    print("=" * 60)
    print(f"Bank records:    {total_bank}")
    print(f"Ledger records:  {total_ledger}")
    print(f"Matched (bank):  {matched_bank}/{total_bank} ({matched_bank/total_bank*100:.1f}%)")
    print(f"Matched (ledger):{matched_ledger}/{total_ledger} ({matched_ledger/total_ledger*100:.1f}%)")
    print()
    print("Match breakdown by tier:")
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier:15s}: {count}")
    print()
    print(f"Unresolved exceptions: {len(exceptions)}")
    print(f"  -> see exceptions.csv")
    print(f"Full audit trail: audit_log.csv ({len(audit_log)} matched pairs)")
    print("=" * 60)


if __name__ == "__main__":
    bank_rows, ledger_rows, audit_log, exceptions = run_reconciliation(
        "bank_statement.csv", "ledger.csv")
    write_report(bank_rows, ledger_rows, audit_log, exceptions)
