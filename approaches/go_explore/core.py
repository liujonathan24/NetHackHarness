"""Monte-Carlo lookahead over a live NetHack engine state.

The core primitive is :func:`mc_lookahead`: snapshot the engine's CURRENT
state once, then for each candidate action explore ``n_branches`` rollouts by
restoring the snapshot, (optionally) reseeding so random chance diverges,
stepping the candidate action, rolling out a default policy for ``horizon``
steps, and scoring the resulting state.  The ranked candidates tell you which
next action looks most promising.

This is the LIVE-state MC primitive — it branches from wherever the passed-in
``env`` currently is.  Deterministically replaying a SAVED harness trace to a
point additionally requires that trace's per-example seed (see README).

blstats indices used (verified empirically against the fork engine):
    blstats[0]  = player x
    blstats[1]  = player y
    blstats[12] = dungeon depth (dlvl)
"""

from __future__ import annotations

from typing import Callable, Optional

# blstats indices (verified: see module docstring / README).
_BL_X = 0
_BL_Y = 1
_BL_DEPTH = 12

#: Penalty subtracted from the default score when a rollout ends in death/done.
_DEATH_PENALTY = 1000.0


def _depth_of(obs) -> int:
    """Dungeon depth (dlvl) from an observation, robust to missing blstats."""
    try:
        return int(obs.blstats[_BL_DEPTH])
    except Exception:
        return 0


def default_score_fn(obs, done: bool) -> float:
    """Default rollout score: depth gained, with a large death penalty.

    Deeper is better (progress); a finished/dead game is heavily penalised so
    candidates that survive and descend rank above candidates that die.
    """
    score = float(_depth_of(obs))
    if done:
        score -= _DEATH_PENALTY
    return score


def _rollout_branch(
    env,
    handle,
    candidate_action: int,
    *,
    horizon: int,
    reseed: bool,
    branch_seed: int,
    rollout_policy: Optional[Callable[[object, int], int]],
    score_fn: Callable[[object, bool], float],
):
    """Restore the snapshot, branch the candidate action, roll out, and score.

    Returns ``(score, depth_gain, died)``.  Any engine exception inside the
    branch is caught and scored as a death so one bad branch never aborts the
    whole MC call.
    """
    try:
        # Order matters: the snapshot captures the RNG, so reseed must follow
        # restore (mirrors EngineEnv.branch()).
        start_obs = env.restore(handle)
        start_depth = _depth_of(start_obs)
        if reseed:
            env.engine.reseed(core=1000 + branch_seed, disp=2000 + branch_seed)

        # Step the candidate action that this branch is evaluating.
        obs, done, _info = env.step(candidate_action)

        # Roll out a default policy for `horizon` steps.  Default policy:
        # repeat the candidate action; otherwise call the provided policy.
        for _ in range(horizon):
            if done:
                break
            action = (
                rollout_policy(obs, candidate_action)
                if rollout_policy is not None
                else candidate_action
            )
            obs, done, _info = env.step(action)

        score = float(score_fn(obs, done))
        depth_gain = float(_depth_of(obs) - start_depth)
        return score, depth_gain, bool(done)
    except Exception:
        # A branch that throws is scored as a death rather than aborting.
        return float(-_DEATH_PENALTY), 0.0, True


def mc_lookahead(
    env,
    candidate_actions,
    *,
    horizon: int = 40,
    n_branches: int = 3,
    reseed: bool = True,
    score_fn: Optional[Callable[[object, bool], float]] = None,
    rollout_policy: Optional[Callable[[object, int], int]] = None,
) -> list[dict]:
    """Monte-Carlo evaluate candidate next actions from the env's current state.

    Snapshots the env's CURRENT state ONCE.  For each action in
    ``candidate_actions`` (a list of NLE/raw action ints) performs
    ``n_branches`` rollouts: restore the snapshot, (if ``reseed``) reseed with a
    per-branch seed so chance diverges, step the candidate action, then roll out
    ``horizon`` steps of a default policy (default: repeat the candidate action,
    or a provided ``rollout_policy(obs, candidate_action) -> action``), and score
    the resulting state with ``score_fn(obs, done)`` (default
    :func:`default_score_fn` = depth minus a death penalty).

    Returns a list of dicts sorted best-first::

        {"action": a, "mean_score": float, "scores": [...],
         "mean_depth_gain": float, "death_rate": float}

    The single snapshot handle is reused across all branches and freed before
    returning (RawEngine snapshots support repeated restore).  Per-branch engine
    exceptions are caught and scored as deaths, so one bad branch does not abort
    the call.
    """
    if score_fn is None:
        score_fn = default_score_fn

    handle = env.snapshot()
    try:
        results: list[dict] = []
        for action in candidate_actions:
            scores: list[float] = []
            depth_gains: list[float] = []
            deaths = 0
            for b in range(n_branches):
                score, depth_gain, died = _rollout_branch(
                    env,
                    handle,
                    action,
                    horizon=horizon,
                    reseed=reseed,
                    branch_seed=b,
                    rollout_policy=rollout_policy,
                    score_fn=score_fn,
                )
                scores.append(score)
                depth_gains.append(depth_gain)
                if died:
                    deaths += 1
            n = max(len(scores), 1)
            results.append(
                {
                    "action": action,
                    "mean_score": sum(scores) / n,
                    "scores": scores,
                    "mean_depth_gain": sum(depth_gains) / n,
                    "death_rate": deaths / n,
                }
            )
        results.sort(key=lambda r: r["mean_score"], reverse=True)
        return results
    finally:
        env.free_snapshot(handle)


def replay_then_branch(env, action_prefix, candidate_actions, **kw) -> list[dict]:
    """Step ``env`` through ``action_prefix`` from its current state, then MC.

    ``action_prefix`` is a list of NLE/raw action ints replayed in order from
    the env's current state; afterwards :func:`mc_lookahead` is invoked over
    ``candidate_actions`` from the reached state.  This is the
    "replay to a point, then Monte-Carlo the continuations" workflow.

    Extra keyword args are forwarded to :func:`mc_lookahead`.  Note this steps
    the LIVE env forward (it does not snapshot/restore the prefix); after the
    call the env sits at the end of ``action_prefix`` (mc_lookahead restores its
    own snapshot internally, so the env is left at the post-prefix state).
    """
    for action in action_prefix:
        env.step(action)
    return mc_lookahead(env, candidate_actions, **kw)
