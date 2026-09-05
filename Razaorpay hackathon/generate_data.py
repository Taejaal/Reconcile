"""
Generates synthetic bank_statement.csv and ledger.csv for the reconciliation project,
plus a hidden answer_key.csv that records the TRUE correspondence between rows.

The answer key exists ONLY so we can measure our matcher's real accuracy later.
It is not something the matcher is allowed to look at.
"""

import csv
import random
from datetime import date, timedelta

random.seed(42)  # reproducible data

NAMES = [
    "Aarav Sharma", "Priya Nair", "Rohan Gupta", "Sneha Iyer", "Vikram Rao",
    "Ananya Das", "Karan Mehta", "Ishita Bose", "Arjun Reddy", "Meera Pillai",
    "Sanjay Verma", "Divya Menon", "Farhan Khan", "Neha Kapoor", "Ravi Chandran",
    "Pooja Joshi", "Amitabh Singh", "Kavya Krishnan", "Tarun Malhotra", "Lakshmi Iyer",
]

MERCHANTS = [
    "Zomato", "Swiggy", "Amazon India", "Flipkart", "BigBasket", "Myntra",
    "Ola Cabs", "Uber India", "BookMyShow", "Airtel Payments", "Jio Recharge",
    "Nykaa", "Croma Electronics", "DMart Online", "Urban Company",
]

REASONS = ["Invoice Payment", "Refund", "Salary Credit", "Vendor Settlement",
           "Subscription Fee", "Purchase", "Service Charge", "Transfer"]

TXN_PREFIX = "TXN"

def make_amount():
    # amounts with paise, like real transactions
    return round(random.uniform(150, 85000), 2)

def fmt_date(d, style):
    if style == 0:
        return d.strftime("%Y-%m-%d")
    elif style == 1:
        return d.strftime("%d/%m/%Y")
    else:
        return d.strftime("%d-%b-%Y")

def typo(text):
    """Introduce a mild typo / abbreviation into text."""
    variants = [
        text.upper(),
        text.replace(" ", ""),
        text[:1] + "." + text.split(" ")[-1] if " " in text else text,
        "PYMT-" + text.split(" ")[-1].upper() if " " in text else "PYMT-" + text.upper(),
        text.replace("a", "a ").strip(),  # sloppy spacing typo
    ]
    return random.choice(variants)

def build_narration(name_or_merchant, reason):
    return f"{reason} - {name_or_merchant}"

base_date = date(2026, 8, 1)

bank_rows = []
ledger_rows = []
answer_key = []

txn_counter = 1000

def next_txn_id():
    global txn_counter
    txn_counter += 1
    return f"{TXN_PREFIX}{txn_counter}"

# ---- 1. Perfect exact-CONTENT matches (18 records) ----
# NOTE: bank and ledger txn_ids are intentionally DIFFERENT (as in real life --
# two separate systems never share an ID). This category is still "exact" because
# amount/date/narration are byte-identical, so the exact-content-match pass (not
# the exact-ID pass) should catch these -- exercising that code path honestly.
for _ in range(18):
    d = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration = build_narration(who, reason)
    tid_b = next_txn_id()
    tid_l = next_txn_id()
    bank_rows.append([tid_b, fmt_date(d, 0), amt, narration])
    ledger_rows.append([tid_l, fmt_date(d, 0), amt, narration])
    answer_key.append([tid_b, tid_l, "EXACT_MATCH"])

# ---- 2. Typo / formatting mismatch in narration (10 records) ----
for _ in range(10):
    d = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration_bank = build_narration(who, reason)
    narration_ledger = typo(narration_bank)
    tid_b = next_txn_id()
    tid_l = next_txn_id()
    bank_rows.append([tid_b, fmt_date(d, random.choice([0,1,2])), amt, narration_bank])
    ledger_rows.append([tid_l, fmt_date(d, random.choice([0,1,2])), amt, narration_ledger])
    answer_key.append([tid_b, tid_l, "TYPO_FORMATTING"])

# ---- 3. Date drift (1-3 days apart) (8 records) ----
for _ in range(8):
    d1 = base_date + timedelta(days=random.randint(0, 27))
    drift = random.randint(1, 3)
    d2 = d1 + timedelta(days=drift)
    amt = make_amount()
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration = build_narration(who, reason)
    tid_b = next_txn_id()
    tid_l = next_txn_id()
    bank_rows.append([tid_b, fmt_date(d1, 0), amt, narration])
    ledger_rows.append([tid_l, fmt_date(d2, 0), amt, narration])
    answer_key.append([tid_b, tid_l, "DATE_DRIFT"])

# ---- 4. Amount mismatch (rounding/fee, tiny difference) (7 records) ----
for _ in range(7):
    d = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    diff = round(random.uniform(0.5, 5.0), 2)
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration = build_narration(who, reason)
    tid_b = next_txn_id()
    tid_l = next_txn_id()
    bank_rows.append([tid_b, fmt_date(d, 0), amt, narration])
    ledger_rows.append([tid_l, fmt_date(d, 0), round(amt - diff, 2), narration])
    answer_key.append([tid_b, tid_l, "AMOUNT_MISMATCH_MINOR"])

# ---- 5. Missing from ledger (bank has it, ledger never recorded it) (6 records) ----
for _ in range(6):
    d = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration = build_narration(who, reason)
    tid = next_txn_id()
    bank_rows.append([tid, fmt_date(d, 0), amt, narration])
    answer_key.append([tid, "NONE", "MISSING_FROM_LEDGER"])

# ---- 6. Missing from bank (ledger has it, not cleared yet) (6 records) ----
for _ in range(6):
    d = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration = build_narration(who, reason)
    tid = next_txn_id()
    ledger_rows.append([tid, fmt_date(d, 0), amt, narration])
    answer_key.append(["NONE", tid, "MISSING_FROM_BANK"])

# ---- 7. Duplicate entries (accidentally recorded twice on one side) (5 records) ----
for _ in range(5):
    d = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    who = random.choice(NAMES + MERCHANTS)
    reason = random.choice(REASONS)
    narration = build_narration(who, reason)
    tid_b = next_txn_id()
    tid_l = next_txn_id()
    dup_tid = next_txn_id()
    bank_rows.append([tid_b, fmt_date(d, 0), amt, narration])
    ledger_rows.append([tid_l, fmt_date(d, 0), amt, narration])
    ledger_rows.append([dup_tid, fmt_date(d, 0), amt, narration])  # duplicate on ledger side
    answer_key.append([tid_b, tid_l, "EXACT_MATCH"])
    answer_key.append(["NONE", dup_tid, "DUPLICATE_ENTRY"])

# ---- 8. One-to-many split (one bank deposit = two ledger invoices) (4 groups) ----
for _ in range(4):
    d = base_date + timedelta(days=random.randint(0, 30))
    part1 = make_amount()
    part2 = make_amount()
    total = round(part1 + part2, 2)
    who = random.choice(NAMES + MERCHANTS)
    tid_bank = next_txn_id()
    tid_l1 = next_txn_id()
    tid_l2 = next_txn_id()
    bank_rows.append([tid_bank, fmt_date(d, 0), total, build_narration(who, "Vendor Settlement")])
    ledger_rows.append([tid_l1, fmt_date(d, 0), part1, build_narration(who, "Invoice Payment")])
    ledger_rows.append([tid_l2, fmt_date(d, 0), part2, build_narration(who, "Invoice Payment")])
    answer_key.append([tid_bank, f"{tid_l1}+{tid_l2}", "ONE_TO_MANY_SPLIT"])

# ---- 9. Coincidence risk (two unrelated txns with similar amount/date, should NOT match) (5 records) ----
for _ in range(5):
    d1 = base_date + timedelta(days=random.randint(0, 30))
    amt = make_amount()
    who1 = random.choice(NAMES)
    who2 = random.choice(MERCHANTS)
    tid1 = next_txn_id()
    tid2 = next_txn_id()
    bank_rows.append([tid1, fmt_date(d1, 0), amt, build_narration(who1, "Transfer")])
    ledger_rows.append([tid2, fmt_date(d1, 0), amt, build_narration(who2, "Purchase")])
    answer_key.append([tid1, "NONE", "MISSING_FROM_LEDGER"])
    answer_key.append(["NONE", tid2, "MISSING_FROM_BANK"])

# Shuffle rows so they aren't grouped by category (more realistic + harder)
random.shuffle(bank_rows)
random.shuffle(ledger_rows)

# ---- Write files ----
with open("bank_statement.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["txn_id", "date", "amount", "narration"])
    w.writerows(bank_rows)

with open("ledger.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["txn_id", "date", "amount", "narration"])
    w.writerows(ledger_rows)

with open("answer_key.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["bank_txn_id", "ledger_txn_id", "category"])
    w.writerows(answer_key)

print(f"bank_statement.csv: {len(bank_rows)} rows")
print(f"ledger.csv: {len(ledger_rows)} rows")
print(f"answer_key.csv: {len(answer_key)} rows")
