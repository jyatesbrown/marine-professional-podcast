from __future__ import annotations

from dataclasses import dataclass

from .segment import Segment

# Published self-serve plans (https://elevenlabs.io/pricing, checked 2026-10-29). Monthly price in USD
# and included credits. Text to Dialogue on eleven_v4 / eleven_v3 consumes 1 credit per character.
PLANS = {
    "free": (0, 10_000),
    "starter": (6, 30_000),
    "creator": (22, 121_000),
    "pro": (99, 600_000),
    "scale": (299, 1_800_000),
    "business": (990, 6_000_000),
}
CREDITS_PER_CHAR = {"eleven_v4": 1.0, "eleven_v3": 1.0}
# Pay-as-you-go API price per 1K characters (https://elevenlabs.io/pricing/api).
PAYG_USD_PER_1K_CHARS = {"eleven_v4": 0.08, "eleven_v3": 0.08}


@dataclass
class Estimate:
    segments: int
    chars: int
    credits: int
    plan: str
    plan_share: float          # fraction of the plan's monthly credits
    usd_at_plan_rate: float    # credits valued at plan price / included credits
    usd_payg: float

    def lines(self) -> list[str]:
        return [
            f"segments (API requests): {self.segments}",
            f"characters billed:        {self.chars:,}",
            f"estimated credits:        {self.credits:,}",
            f"share of {self.plan} plan:  {self.plan_share:.1%} of monthly credits",
            f"value at {self.plan} rate:  ${self.usd_at_plan_rate:.2f}",
            f"pay-as-you-go price:      ${self.usd_payg:.2f}",
        ]


def estimate(segments: list[Segment], model_id: str, plan: str) -> Estimate:
    chars = sum(s.chars for s in segments)
    credits = int(round(chars * CREDITS_PER_CHAR.get(model_id, 1.0)))
    price, included = PLANS.get(plan, PLANS["creator"])
    return Estimate(
        segments=len(segments),
        chars=chars,
        credits=credits,
        plan=plan,
        plan_share=credits / included if included else 0.0,
        usd_at_plan_rate=credits * price / included if included else 0.0,
        usd_payg=chars / 1000 * PAYG_USD_PER_1K_CHARS.get(model_id, 0.08),
    )


def monthly_projection(credits_per_episode: int, episodes: int = 30) -> list[str]:
    total = credits_per_episode * episodes
    lines = [f"{episodes} episodes x {credits_per_episode:,} credits = {total:,} credits/month"]
    for name, (price, included) in PLANS.items():
        fits = "fits" if total <= included else f"short by {total - included:,}"
        lines.append(f"  {name:<9} ${price:>4}/mo  {included:>9,} credits  -> {fits}")
    return lines


class LimitExceeded(Exception):
    pass


def enforce_limits(credits: int, segments: int, month_used: int, limits) -> None:
    if segments > limits.max_segments_per_run:
        raise LimitExceeded(
            f"{segments} segments exceeds max_segments_per_run={limits.max_segments_per_run}"
        )
    if credits > limits.max_credits_per_run:
        raise LimitExceeded(
            f"{credits:,} credits exceeds max_credits_per_run={limits.max_credits_per_run:,}"
        )
    if month_used + credits > limits.max_credits_per_month:
        raise LimitExceeded(
            f"{month_used:,} used this month + {credits:,} would exceed "
            f"max_credits_per_month={limits.max_credits_per_month:,}"
        )
