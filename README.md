# Reconcile — Bank Statement ↔ Ledger Transaction Matcher

**Razorpay Buildathon — AI Finance Controller Track**

Automated matching of bank statement transactions against internal ledger records, with confidence-scored fuzzy matching, a full audit trail, and a clear exception list for manual review.

---

## Problem

Finance teams manually reconcile bank statements against internal ledgers every day — a slow, error-prone process, especially when transaction descriptions, dates, or amounts don't line up exactly across systems (bank narration truncation, timezone/date-cutoff mismatches, rounding, partial payments, etc.). Reconciliation errors delay financial close, hide fraud/duplicate payments, and cost analysts hours of spreadsheet cross-checking.

## Architecture

```
 ┌────────────────┐     ┌──────────────────┐
 │  Bank CSV       │     │  Ledger CSV       │
 └────────┬────────┘     └────────┬──────────┘
          │                       │
          └───────────┬───────────┘
                       ▼
              ┌─────────────────┐
              │  Exact Matcher   │  ← txn_id or identical content
              └────────┬─────────┘
                        │  (unmatched only)
                        ▼
              ┌─────────────────┐
              │  Hard Reject     │  ← date >30d or amount >25% off
              │  Gate            │
              └────────┬─────────┘
                        │  (surviving pairs)
                        ▼
              ┌─────────────────┐
              │  Special-Case    │  ← MONEY_DATE_LOCK
              │  Rules           │  ← TEXT_LOCK
              └────────┬─────────┘
                        │  (still ambiguous)
                        ▼
              ┌─────────────────┐
              │  Weighted        │  ← 0.4×amount + 0.3×date + 0.3×text
              │  Fallback        │
              └────────┬─────────┘
                        │
                        ▼
              ┌─────────────────┐
              │  Greedy          │  ← highest confidence first
              │  Assignment      │
              └────────┬─────────┘
                        │
                        ▼
              ┌───────────────────────┐
              │  Confidence Tiers      │
              │  AUTO_MATCH  ≥ 0.90    │
              │  NEEDS_REVIEW ≥ 0.65   │
              │  EXCEPTION   < 0.65    │
              └────────────┬───────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Output      │
                    │ - audit_log    │
                    │ - exceptions   │
                    │ - HTML report  │
                    └───────────────┘
```

## How to Run

### 1. Install dependency

```bash
pip install rapidfuzz
```

### 2. Generate synthetic test data (optional — data files already included)

```bash
python generate_data.py              # own dataset
python generate_recon_dataset.py     # stress-test dataset (writes to current dir)
```

### 3. Run the matcher

```bash
python matcher.py
```

This reads `bank_statement.csv` and `ledger.csv` from the current directory and writes:
- `audit_log.csv` — every matched pair with full score breakdown (amount, date, text scores, rule fired, confidence, tier)
- `exceptions.csv` — unmatched records with category (UNMATCHED_BANK_ENTRY / UNMATCHED_LEDGER_ENTRY)

### 4. Grade accuracy against the answer key

```bash
python grade.py
```

Compares `audit_log.csv` against the hidden `answer_key.csv` and reports precision, recall, F1, and lists false positives.

### 5. Run the threshold sweep diagnostic

```bash
python threshold_sweep.py
```

Checks whether a text-score floor can cleanly separate false positives from genuine rescues in the MONEY_DATE_LOCK rule.

### 6. Generate the HTML report

```bash
python generate_report.py \
  --own-audit audit_log.csv \
  --own-exceptions exceptions.csv \
  --stress-audit stress_test/audit_log.csv \
  --stress-exceptions stress_test/exceptions.csv \
  --output demo_report.html
```

Produces a self-contained HTML report (`demo_report.html`) with:
- Side-by-side metrics for own vs. stress-test datasets
- Confidence tier and rule frequency charts (Chart.js)
- False-positive root-cause breakdown
- Threshold sweep scatter charts
- Sortable exceptions tables
- Known limitations callout

Only Python stdlib is needed for the report generator — no pip install.

## Results

| Metric | Own Dataset | Stress-Test |
|--------|-------------|-------------|
| Precision | 79.3% | 77.2% |
| Recall | 95.8% | 71.0% |
| F1 Score | 86.8% | 73.9% |
| True Positives | 46 | 44 |
| False Positives | 10 | 13 |
| False Negatives | 2 | 18 |

### False-Positive Root Causes (combined)

| Category | Count | Notes |
|----------|-------|-------|
| Structural decoys | 9/14 | Same amount+date, different entity — unfixable without an extra data field |
| Stolen match | 4/14 | Fixable by switching from greedy to optimal (Hungarian) assignment |
| Cross-mismatch | 1/14 | Also fixable by optimal assignment |

## File Structure

```
├── matcher.py                  # Core reconciliation engine
├── generate_data.py            # Own synthetic dataset generator
├── generate_recon_dataset.py   # Adversarial stress-test generator
├── grade.py                    # Accuracy grader (vs answer key)
├── threshold_sweep.py          # Text-score floor diagnostic
├── generate_report.py          # HTML report builder
├── bank_statement.csv          # Own dataset: bank side (64 rows)
├── ledger.csv                  # Own dataset: ledger side (73 rows)
├── answer_key.csv              # Own dataset: ground truth (80 entries)
├── audit_log.csv               # Matcher output: matched pairs
├── exceptions.csv              # Matcher output: unmatched records
├── demo_report.html            # Generated HTML report
├── architecture.md             # Architecture diagrams (Mermaid + ASCII)
└── stress_test/                # Independent adversarial dataset
    ├── matcher.py
    ├── grade.py
    ├── threshold_sweep.py
    ├── bank_statement.csv
    ├── ledger.csv
    ├── answer_key.csv
    ├── audit_log.csv
    └── exceptions.csv
```

## Known Limitations

- The matcher does not see a merchant-category or account-ID field, so structural decoys (same amount, same date, different counterparty) cannot be told apart from a true match.
- Greedy assignment is used instead of optimal (Hungarian) assignment, which accounts for 5 of the 14 false positives.
- One-to-many splits (one bank deposit covering multiple ledger invoices) are not handled by the pairwise matching architecture.
- Text similarity is not currency/locale-aware and does not normalize merchant name variants or abbreviations beyond prefix/suffix stripping.

---

*Built for the Razorpay Buildathon (AI Finance Controller track).*
