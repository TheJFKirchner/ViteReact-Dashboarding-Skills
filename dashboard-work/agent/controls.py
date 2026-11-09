"""Control cards: live color / slider / switch controls the agent attaches to a reply.

The agent binds each control to an exact spot in the section code:
    anchor = a snippet that occurs once in the code, value = the value text inside it (once).
After that, the user's tweaks are applied by the server alone (no model call): the value inside
the anchor is swapped for the new one. Every swap still passes the protected-parts guard.
"""
from __future__ import annotations

import json
import re

KINDS = ("color", "slider", "switch")
MAX_CONTROLS = 6
HEX = re.compile(r"#[0-9a-fA-F]{6}")
QUOTED_HEX = re.compile(r"""^(['"])#[0-9a-fA-F]{6}\1$""")
NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def theme_swatches(root, uses_fx: bool, color_name) -> list[dict]:
    """[{label, hex, expr}] for the active theme. expr is what gets written into the code:
    an fx() expression when the file uses fx(), otherwise the quoted hex."""
    config = json.loads((root / "dashboard.config.json").read_text(encoding="utf-8"))
    colors = json.loads((root / "Themes" / config.get("theme", "house") / "tokens.json").read_text(encoding="utf-8"))["colors"]
    picks = [(f"f.color({i})", color_name(h), h) for i, h in enumerate(colors["series"])]
    for key, expr in (("good", "f.good"), ("bad", "f.bad"), ("accent", "f.colors.accent"), ("textMuted", "f.colors.textMuted"), ("text", "f.colors.text")):
        if key in colors:
            picks.append((expr, f"{key} ({color_name(colors[key])})" if key in ("good", "bad") else key, colors[key]))
    seen, out = set(), []
    for expr, label, h in picks:  # same color twice (e.g. accent == series 0) -> keep the first
        if h.upper() not in seen:
            seen.add(h.upper())
            out.append({"label": label, "hex": h.upper(), "expr": expr if uses_fx else f"'{h.upper()}'"})
    return out


def is_color_value(value: str, swatches: list[dict]) -> bool:
    return value in {s["expr"] for s in swatches} or bool(QUOTED_HEX.match(value)) or bool(re.fullmatch(r"f\.color\(\d\)", value))


def check_offer(code: str, controls: list, swatches: list[dict]) -> tuple[list[dict] | None, str | None]:
    """Validate the agent's control specs against the current code. Returns (controls, error)."""
    if not isinstance(controls, list) or not 1 <= len(controls) <= MAX_CONTROLS:
        return None, f"Offer between 1 and {MAX_CONTROLS} controls."
    out, spans = [], []
    for i, c in enumerate(controls):
        kind, label = c.get("kind"), (c.get("label") or "").strip()
        anchor, value = c.get("anchor") or "", str(c.get("value", ""))
        name = f'control {i + 1} ("{label or kind}")'
        if kind not in KINDS:
            return None, f"{name}: kind must be one of {', '.join(KINDS)}."
        if not label:
            return None, f"{name}: needs a short label."
        if code.count(anchor) != 1:
            return None, f"{name}: anchor must occur exactly once in the current code (found {code.count(anchor)}). Copy it exactly."
        if not value or anchor.count(value) != 1:
            return None, f"{name}: value must occur exactly once inside the anchor."
        start = code.index(anchor)
        if any(start < e and s < start + len(anchor) for s, e in spans):
            return None, f"{name}: anchors of one card must not overlap."
        spans.append((start, start + len(anchor)))
        spec = {"id": f"c{i}", "kind": kind, "label": label, "anchor": anchor, "value": value}
        if kind == "color" and not is_color_value(value, swatches):
            return None, (f"{name}: value must be a theme color expression (e.g. f.color(4), f.good) or a quoted hex like '#FFB020'. "
                          "If the color comes from a variable, bind the control where the variable is defined.")
        if kind == "slider":
            try:
                lo, hi, step = float(c["min"]), float(c["max"]), float(c.get("step") or 1)
            except (KeyError, TypeError, ValueError):
                return None, f"{name}: slider needs numeric min, max (and optional step)."
            if not NUMBER.match(value) or not lo < hi or step <= 0:
                return None, f"{name}: slider value must be a plain number and min < max."
            spec.update(min=lo, max=hi, step=step)
        if kind == "switch" and value not in ("true", "false"):
            return None, f"{name}: switch value must be true or false."
        out.append(spec)
    return out, None


def trial_value(spec: dict) -> str:
    """A different valid value, used to check a binding doesn't touch protected code."""
    return {"color": "'#000000'", "slider": format_number(spec.get("min", 0), spec.get("step", 1)),
            "switch": "false" if spec["value"] == "true" else "true"}[spec["kind"]]


def format_number(v: float, step: float) -> str:
    """6.0 -> '6', 2.5 -> '2.5' (decimals follow the slider step)."""
    decimals = len(str(step).split(".")[1].rstrip("0")) if "." in str(step) else 0
    text = f"{v:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def code_value(spec: dict, raw, swatches: list[dict]) -> str:
    """User's pick -> text written into the code. Raises ValueError for anything not allowed."""
    if spec["kind"] == "color":
        raw = str(raw)
        if raw in {s["expr"] for s in swatches}:
            return raw
        if HEX.fullmatch(raw):
            return f"'{raw.upper()}'"
        raise ValueError("pick a theme swatch or a #RRGGBB color")
    if spec["kind"] == "slider":
        v = float(raw)
        if not spec["min"] <= v <= spec["max"]:
            raise ValueError(f"value must be between {spec['min']} and {spec['max']}")
        return format_number(v, spec["step"])
    if raw in (True, "true"):
        return "true"
    if raw in (False, "false"):
        return "false"
    raise ValueError("switch value must be true or false")


def public_card(card_id: int, specs: list[dict], swatches: list[dict]) -> dict:
    """What the browser needs to draw the card (no anchors)."""
    keys = ("id", "kind", "label", "value", "min", "max", "step")
    return {"id": card_id, "swatches": swatches, "controls": [{k: s[k] for k in keys if k in s} for s in specs]}
