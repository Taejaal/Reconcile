# Architecture

## Mermaid

```mermaid
flowchart LR
    A[Bank CSV] --> C[Exact Matcher]
    B[Ledger CSV] --> C
    C -->|Unmatched| D[Fuzzy Matcher]
    C -->|Matched: 100% confidence| F[Report]
    D -->|Matched: scored confidence| F
    D -->|Still unmatched / low score| E[Exception Classifier]
    E --> F[Report:
    Match Rate + Confidence + Exceptions]
```

## ASCII

```
 ┌────────────────┐     ┌──────────────────┐
 │  Bank CSV       │     │  Ledger CSV       │
 └────────┬────────┘     └────────┬──────────┘
          │                       │
          └───────────┬───────────┘
                       ▼
              ┌─────────────────┐
              │  Exact Matcher   │
              └────────┬─────────┘
                        │  (unmatched only)
                        ▼
              ┌─────────────────┐
              │  Fuzzy Matcher   │
              │ amount+date+text │
              └────────┬─────────┘
                        │  (still unmatched /
                        │   below confidence
                        │   threshold)
                        ▼
              ┌───────────────────────┐
              │ Exception Classifier   │
              └────────────┬───────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Report      │
                    │ - Match Rate   │
                    │ - Confidence   │
                    │ - Exceptions   │
                    └───────────────┘
```
