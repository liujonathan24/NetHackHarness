# Model size sweep — Qwen3.5-35B-A3B vs 9B on corridor_explore

Both run on 2026-05-15 22:00 EDT against env v0.0.14.

## Headline

**Bigger model avoided the menu-prompt trap.** 35B-A3B made 0 `menu_option`
calls; 9B made 41. Neither reached dlvl 2 in 10 minutes — that's
still a multi-hour task for a non-fine-tuned LM.

## Numbers

| | 9B (Qwen/Qwen3.5-9B) | 35B-A3B (qwen/qwen3.5-35b-a3b) |
|-|-|-|
| turns | 146 | 162 |
| tool calls | 144 | 162 |
| reward | 0 | 0 |
| `move_to` calls | 42 | 24 |
| `move` calls | 35 | 96 |
| `attack` calls | 10 | 0 |
| `search` calls | 6 | 6 |
| `descend` calls | 4 | 1 |
| `autoexplore` calls | 2 | 34 |
| `menu_option` calls | **41** | **0** |
| `kick` calls | 2 | 0 |
| `add_note` calls | 1 | 0 |
| input tokens | 4.27M | 4.62M |
| output tokens | 46K | 41K |
| cost | $0.79 | $1.46 |

## Read

- **The 9B model gets stuck on menus.** 41 menu_option calls suggests it
  triggered inventory/menu prompts (probably via misuse of `eat`/`quaff`/`read`
  without checking inventory_prompt first) and then burned turns escaping
  them. The 35B model avoided this entirely — likely a better understanding
  of the tool schema's preconditions.
- **35B used `autoexplore` 17× more often** than 9B (34 vs 2). That's the
  high-leverage skill: each call expands ~5 env actions per LM turn. A
  more capable model concentrates on it.
- **35B didn't attack anything** (0 attacks vs 9B's 10). It explored
  pacifistically. Whether this is a good NetHack strategy is open —
  monks would agree, fighters wouldn't.
- **Cost is 2x for 35B** at similar wallclock and same outcome. For pure
  reward-maximization purposes, 9B + better prompting is probably cheaper
  per descent.
- Neither model finished `corridor_explore`. With max_turns=200 cap and
  10min wallclock, 9B managed 146 turns and 35B managed 162 — but
  neither reached dlvl 2.

## Where this lands the project Monday

- Substrate works at both sizes. No crashes.
- The reward signal is currently too sparse for behavior cloning at this
  model size + budget. Either:
  - bigger model (Qwen3-235B or Claude-haiku-4-5: ~$5–10/rollout)
  - longer wallclock (30min instead of 10min: ~3x cost)
  - richer shaping (track BALROG progression milestones as auxiliary reward)
  - SFT first (run a few hundred rollouts, score by tile coverage, fine-tune)

For Monday: the takeaway is "the env runs end-to-end, and the substrate
exercises every skill the agent needs. Reward signal is sparse by design —
that's the *long-horizon* in *long-horizon eval*."
