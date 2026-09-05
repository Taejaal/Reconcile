"""
generate_recon_dataset.py

Generates a HARD, realistic synthetic dataset for stress-testing a
bank-statement-vs-ledger reconciliation matcher.

Outputs (in the same directory as this script):
    bank_statement.csv   (txn_id, date, amount, narration)
    ledger.csv            (txn_id, date, amount, narration)
    answer_key.csv         (bank_txn_id, ledger_txn_id, category)  -- NOT for the matcher

Run:
    python generate_recon_dataset.py

Reproducible via SEED below.
"""

import csv
import random
from datetime import date, timedelta

SEED = 42
random.seed(SEED)

# ----------------------------------------------------------------------
# Reference pools
# ----------------------------------------------------------------------

COMPANIES = [
    "RELIANCE RETAIL", "TATA CONSULTANCY SERV", "BAJAJ FINANCE",
    "INFOSYS", "HCL TECHNOLOGIES", "WIPRO", "ADANI ENTERPRISES",
    "MAHINDRA AND MAHINDRA", "ASIAN PAINTS", "HINDUSTAN UNILEVER",
    "LARSEN AND TOUBRO", "ICICI SECURITIES", "APOLLO HOSPITALS",
    "ZOMATO", "NYKAA FASHION", "BLUE DART EXPRESS", "SHREE CEMENT",
    "GODREJ CONSUMER", "DABUR INDIA", "MARICO",
]

SUFFIX_VARIANTS = ["LTD", "LIMITED", "PVT LTD", "PVT.LTD", "PVT LTD.", ""]

PEOPLE = [
    "RAJESH KUMAR", "PRIYA SHARMA", "AMIT PATEL", "SUNITA RAO",
    "VIKRAM SINGH", "ANITA DESAI", "SURESH IYER", "NEHA GUPTA",
    "KARAN MEHTA", "DEEPA NAIR", "ROHAN JOSHI", "POOJA VERMA",
    "SANJAY REDDY", "KAVITA MENON", "ARJUN CHOPRA", "MEERA PILLAI",
]

BANK_PREFIXES = ["UPI", "NEFT", "IMPS", "RTGS"]
PYMT_PREFIX = "PYMT-"

random_alnum = lambda n: "".join(random.choices("0123456789", k=n))
random_ref = lambda: random_alnum(random.choice([6, 9, 12]))

_txn_counter = {"BNK": 0, "LED": 0}


def next_id(prefix):
    _txn_counter[prefix] += 1
    return f"{prefix}{_txn_counter[prefix]:04d}"


def rand_date(start=date(2024, 1, 5), end=date(2024, 3, 25)):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def company_with_suffix():
    base = random.choice(COMPANIES)
    suf = random.choice(SUFFIX_VARIANTS)
    return f"{base} {suf}".strip()


def entity():
    """Return (clean_entity_name_for_ledger, base_name_for_bank_noise)."""
    if random.random() < 0.6:
        name = company_with_suffix()
    else:
        name = random.choice(PEOPLE)
    return name


def bank_narration(name, ref=None):
    ref = ref or random_ref()
    pattern = random.choice(["upi", "neft", "imps", "pymt", "rtgs"])
    if pattern == "upi":
        return f"UPI/{name}/{ref}/PAYMENT"
    if pattern == "neft":
        return f"NEFT/{ref}/{name}"
    if pattern == "imps":
        return f"IMPS-{ref}-{name}"
    if pattern == "pymt":
        return f"{PYMT_PREFIX}{name}-{ref}"
    return f"RTGS/{name}/{ref}"


def ledger_narration(name, ref=None):
    ref = ref or random_ref()
    pattern = random.choice(["invoice", "payment", "settlement", "services"])
    if pattern == "invoice":
        return f"Invoice {ref} - {name}"
    if pattern == "payment":
        return f"Payment received from {name}"
    if pattern == "settlement":
        return f"Settlement - {name} ({ref})"
    return f"{name} - Services rendered"


def garble(text):
    """Heavily mangle a narration while keeping it plausible bank-side gibberish."""
    words = text.replace("/", " ").replace("-", " ").split()
    random.shuffle(words)
    mangled = []
    for w in words:
        if len(w) > 4 and random.random() < 0.6:
            w = w[: max(3, len(w) - random.randint(1, 3))]
        mangled.append(w)
    codes = random_alnum(random.choice([6, 8, 10]))
    return f"{random.choice(BANK_PREFIXES)}/{''.join(mangled)[:18]}/{codes}"


def money(lo=500, hi=250000):
    return round(random.uniform(lo, hi), 2)


bank_rows = []
ledger_rows = []
answer_key = []
stats = {}


def bump(cat, n=1):
    stats[cat] = stats.get(cat, 0) + n


# ----------------------------------------------------------------------
# 1. Exact matches
# ----------------------------------------------------------------------
for _ in range(8):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money()
    narr = ledger_narration(name, ref)
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, amt, narr])
    ledger_rows.append([l_id, d, amt, narr])
    answer_key.append((b_id, l_id, "exact_match"))
    bump("exact_match")

# ----------------------------------------------------------------------
# 2. Noisy text match (prefixes/suffixes stripped -> same underlying txn)
# ----------------------------------------------------------------------
for _ in range(8):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money()
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, amt, bank_narration(name, ref)])
    ledger_rows.append([l_id, d, amt, ledger_narration(name, ref)])
    answer_key.append((b_id, l_id, "noisy_text_match"))
    bump("noisy_text_match")

# ----------------------------------------------------------------------
# 3. Date drift at exact boundary values: 1,2,3,5,7 days
# ----------------------------------------------------------------------
for drift in (1, 2, 3, 5, 7):
    for _ in range(3):
        name = entity()
        ref = random_ref()
        d_ledger = rand_date()
        d_bank = d_ledger + timedelta(days=drift)
        amt = money()
        b_id, l_id = next_id("BNK"), next_id("LED")
        bank_rows.append([b_id, d_bank, amt, bank_narration(name, ref)])
        ledger_rows.append([l_id, d_ledger, amt, ledger_narration(name, ref)])
        answer_key.append((b_id, l_id, f"date_drift_{drift}d"))
        bump(f"date_drift_{drift}d")

# ----------------------------------------------------------------------
# 4. Amount boundary — exactly AT tolerance (inclusive edge test)
#    3 pairs at exactly Rs 2 off, 3 pairs at exactly 5% off
# ----------------------------------------------------------------------
for _ in range(3):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money()
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, round(amt + 2.00, 2), bank_narration(name, ref)])
    ledger_rows.append([l_id, d, amt, ledger_narration(name, ref)])
    answer_key.append((b_id, l_id, "amount_boundary_abs2"))
    bump("amount_boundary_abs2")

for _ in range(3):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money(2000, 100000)
    bank_amt = round(amt * 1.05, 2)
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, bank_amt, bank_narration(name, ref)])
    ledger_rows.append([l_id, d, amt, ledger_narration(name, ref)])
    answer_key.append((b_id, l_id, "amount_boundary_5pct"))
    bump("amount_boundary_5pct")

# ----------------------------------------------------------------------
# 5. Amount mismatches just BEYOND tolerance -> must be correctly REJECTED
#    (not written to answer_key: ground truth says "no match")
# ----------------------------------------------------------------------
for _ in range(3):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money()
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, round(amt + 2.51, 2), bank_narration(name, ref)])
    ledger_rows.append([l_id, d, amt, ledger_narration(name, ref)])
    bump("amount_beyond_tolerance_abs")

for _ in range(3):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money(2000, 100000)
    bank_amt = round(amt * 1.081, 2)
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, bank_amt, bank_narration(name, ref)])
    ledger_rows.append([l_id, d, amt, ledger_narration(name, ref)])
    bump("amount_beyond_tolerance_pct")

# ----------------------------------------------------------------------
# 6. Near-miss coincidences: same amount + same date, unrelated entities.
#    Designed to bait a naive (amount,date)-only matcher into a false positive.
#    NOT a true match -> excluded from answer_key.
# ----------------------------------------------------------------------
for _ in range(3):
    d = rand_date()
    amt = money()
    name_a = entity()
    name_b = entity()
    while name_b == name_a:
        name_b = entity()
    b_id = next_id("BNK")
    l_id = next_id("LED")
    bank_rows.append([b_id, d, amt, bank_narration(name_a, random_ref())])
    ledger_rows.append([l_id, d, amt, ledger_narration(name_b, random_ref())])
    bump("near_miss_coincidence")

# ----------------------------------------------------------------------
# 7. One-to-many splits: one bank deposit == sum of 2-3 ledger invoices
# ----------------------------------------------------------------------
for n_parts in (2, 2, 2, 3, 3):
    name = entity()
    d_bank = rand_date(date(2024, 2, 1), date(2024, 3, 25))
    parts = [money(1000, 40000) for _ in range(n_parts)]
    total = round(sum(parts), 2)
    b_id = next_id("BNK")
    bank_rows.append([b_id, d_bank, total, bank_narration(name, random_ref())])
    for p in parts:
        d_led = d_bank - timedelta(days=random.randint(0, 4))
        l_id = next_id("LED")
        ledger_rows.append([l_id, d_led, p, ledger_narration(name, random_ref())])
        answer_key.append((b_id, l_id, "one_to_many_split"))
    bump("one_to_many_split", n_parts)

# ----------------------------------------------------------------------
# 8. Duplicate entries: ledger has 2 identical rows (data-entry duplicate),
#    only ONE has a real bank counterpart; the other is an orphan duplicate
#    that must NOT be matched to anything.
# ----------------------------------------------------------------------
for _ in range(3):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money()
    narr_led = ledger_narration(name, ref)
    b_id = next_id("BNK")
    l_id_real = next_id("LED")
    l_id_dup = next_id("LED")
    bank_rows.append([b_id, d, amt, bank_narration(name, ref)])
    ledger_rows.append([l_id_real, d, amt, narr_led])
    ledger_rows.append([l_id_dup, d, amt, narr_led])  # orphan duplicate
    answer_key.append((b_id, l_id_real, "duplicate_true_match"))
    bump("duplicate_true_match")
    bump("duplicate_orphan")

# ----------------------------------------------------------------------
# 9. Missing entries — present on one side only
# ----------------------------------------------------------------------
for _ in range(6):
    name = entity()
    d = rand_date()
    amt = money()
    bank_rows.append([next_id("BNK"), d, amt, bank_narration(name, random_ref())])
    bump("missing_bank_only")

for _ in range(6):
    name = entity()
    d = rand_date()
    amt = money()
    ledger_rows.append([next_id("LED"), d, amt, ledger_narration(name, random_ref())])
    bump("missing_ledger_only")

# ----------------------------------------------------------------------
# 10. "Text score high, amount off by a fee-like amount" special case
#     (true match: bank amount = ledger amount minus/plus a bank charge)
# ----------------------------------------------------------------------
FEE_AMOUNTS = [10.0, 25.0, 50.0, 100.0, 118.0, 236.50]  # incl. GST-like fee
for _ in range(5):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money(5000, 100000)
    fee = random.choice(FEE_AMOUNTS)
    bank_amt = round(amt - fee, 2) if random.random() < 0.5 else round(amt + fee, 2)
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, bank_amt, bank_narration(name, ref)])
    ledger_rows.append([l_id, d, amt, ledger_narration(name, ref)])
    answer_key.append((b_id, l_id, "fee_like_amount_diff"))
    bump("fee_like_amount_diff")

# ----------------------------------------------------------------------
# 11. "Amount+date lock but text heavily garbled" special case
# ----------------------------------------------------------------------
for _ in range(5):
    name = entity()
    ref = random_ref()
    d = rand_date()
    amt = money()
    clean_narr = ledger_narration(name, ref)
    b_id, l_id = next_id("BNK"), next_id("LED")
    bank_rows.append([b_id, d, amt, garble(clean_narr)])
    ledger_rows.append([l_id, d, amt, clean_narr])
    answer_key.append((b_id, l_id, "garbled_text_amount_date_lock"))
    bump("garbled_text_amount_date_lock")

# ----------------------------------------------------------------------
# Shuffle row order so failure types aren't grouped together
# ----------------------------------------------------------------------
random.shuffle(bank_rows)
random.shuffle(ledger_rows)

# ----------------------------------------------------------------------
# Write CSVs
# ----------------------------------------------------------------------
def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


write_csv("bank_statement.csv", ["txn_id", "date", "amount", "narration"], bank_rows)
write_csv("ledger.csv", ["txn_id", "date", "amount", "narration"], ledger_rows)
write_csv("answer_key.csv", ["bank_txn_id", "ledger_txn_id", "category"], answer_key)

# ----------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------
print(f"bank_statement.csv : {len(bank_rows)} rows")
print(f"ledger.csv          : {len(ledger_rows)} rows")
print(f"answer_key.csv      : {len(answer_key)} true-match pairs (hidden ground truth)")
print()
print("Row counts injected per failure-mode category:")
for cat, n in sorted(stats.items()):
    print(f"  {cat:32s} {n}")
