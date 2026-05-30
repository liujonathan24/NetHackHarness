# Descent-rate comparison: `N` vs `E1`

## Headline

| variant | n | descended | rate | 95% Wilson CI | avg_score |
|---|---|---|---|---|---|
| **N** | 9 | 1 |  11.1% | [  2.0%,  43.5%] | 0.309 |
| **E1** | 9 | 0 |   0.0% | [  0.0%,  29.9%] | 0.059 |

## Per-seed outcomes

| seed | N descended | N mode | E1 descended | E1 mode |
|---|---|---|---|---|
| 22 | False | starved | False | killed_by_monster |
| 23 | False | starved | False | killed_by_monster |
| 24 | True | — | False | starved |
| 25 | False | starved | False | killed_by_monster |
| 26 | False | killed_by_monster | False | starved |
| 27 | False | starved | False | killed_by_monster |
| 28 | False | killed_by_monster | False | killed_by_monster |
| 30 | False | killed_by_monster | False | killed_by_monster |
| 31 | False | killed_by_monster | False | starved |

## Failure-mode breakdown (non-descending rollouts)

| mode | N | E1 |
|---|---|---|
| starved | 4 | 3 |
| killed_by_monster | 4 | 6 |
| turn_budget | 0 | 0 |
| stuck_no_progress | 0 | 0 |
| door_block | 0 | 0 |
| other | 0 | 0 |
