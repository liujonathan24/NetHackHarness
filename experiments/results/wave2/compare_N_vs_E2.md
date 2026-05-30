# Descent-rate comparison: `N` vs `E2`

## Headline

| variant | n | descended | rate | 95% Wilson CI | avg_score |
|---|---|---|---|---|---|
| **N** | 9 | 1 |  11.1% | [  2.0%,  43.5%] | 0.309 |
| **E2** | 9 | 0 |   0.0% | [  0.0%,  29.9%] | 0.074 |

## Per-seed outcomes

| seed | N descended | N mode | E2 descended | E2 mode |
|---|---|---|---|---|
| 22 | False | starved | False | killed_by_monster |
| 23 | False | starved | False | killed_by_monster |
| 24 | True | — | False | killed_by_monster |
| 25 | False | starved | False | starved |
| 26 | False | killed_by_monster | — | — |
| 27 | False | starved | False | killed_by_monster |
| 28 | False | killed_by_monster | False | killed_by_monster |
| 29 | — | — | False | killed_by_monster |
| 30 | False | killed_by_monster | False | killed_by_monster |
| 31 | False | killed_by_monster | False | killed_by_monster |

## Failure-mode breakdown (non-descending rollouts)

| mode | N | E2 |
|---|---|---|
| starved | 4 | 1 |
| killed_by_monster | 4 | 8 |
| turn_budget | 0 | 0 |
| stuck_no_progress | 0 | 0 |
| door_block | 0 | 0 |
| other | 0 | 0 |
