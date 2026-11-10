#!/usr/bin/env python3
"""
render_cards.py — animated SVG cards for the Sujay1709 profile README.

    python render_cards.py fetch    # refresh data/contributions.json (+ avatar)
    python render_cards.py          # render every card into cards/
    STATIC=1 python render_cards.py # render the final frame (no animation)

Design: matches the existing README brand — navy #0A2472 on GitHub-dark
#0D1117, body text #C9D1D9, Fira Code. Cards are consumed through <img>
tags, so everything lives inside each SVG: CSS keyframe animations in an
inline <style> block and fonts subset with pyftsubset, embedded as base64
WOFF data URIs. All animations are entrance-only (base styles are the
final state) and are disabled under prefers-reduced-motion.

Deps: fonttools (pyftsubset + varLib.instancer). Stdlib otherwise.
"""

import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape as _esc

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

USER = "Sujay1709"
NAME = "Sujay Gopal Mulagund"
TAGLINE = "I build end-to-end AI/ML systems — RAG pipelines, LLM evals, full-stack AI products."
SUBLINE = "MS Data Science, Analytics & Engineering @ ASU · Tempe, AZ"

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CARDS = ROOT / "cards"
FONT_CACHE = ROOT / ".fonts"

STATIC = os.environ.get("STATIC", "") not in ("", "0")

# Brand palette (lifted from the current README: capsule-render 0A2472,
# shields labelColor 0D1117, stats text c9d1d9, Nord-dark panels).
BG = "#0D1117"          # page / card background
PANEL = "#0E1523"       # card surface
PANEL2 = "#101A2E"      # raised surface
BORDER = "#0A2472"      # brand navy — borders, bars
NAVY = "#0A2472"
NAVY_DEEP = "#071A52"
BLUE_1 = "#16367F"      # heat ramp / secondary
BLUE_2 = "#2B57B8"
BLUE_3 = "#5B84E8"
ACCENT = "#7FA3F0"      # readable brand accent on dark
WHITE = "#F0F4FF"
TEXT = "#C9D1D9"
MUTED = "#8B949E"
EMPTY = "#161B22"       # empty heatmap cell

HEAT_RAMP = [EMPTY, BLUE_1, BLUE_2, BLUE_3, ACCENT]

TILES = [
    dict(slug="building", icon="hammer", title="NOW BUILDING",
         lines=["DocuMind · MRDS · AutoHub", "shipping end-to-end AI"],
         alt="Now building: DocuMind, Model Regression Detection System, AutoHub",
         href=f"https://github.com/{USER}?tab=repositories"),
    dict(slug="demo", icon="play", title="LIVE DEMO",
         lines=["DocuMind — RAG Q&A", "on HuggingFace Spaces"],
         alt="Live demo: DocuMind on HuggingFace Spaces",
         href="https://huggingface.co/spaces/sujay19/documind"),
    dict(slug="connect", icon="link", title="CONNECT",
         lines=["LinkedIn · in/sujay-mulagund", "sujaymulagund19@gmail.com"],
         alt="Connect with Sujay on LinkedIn",
         href="https://www.linkedin.com/in/sujay-mulagund-0ab588269/"),
]

FEATURED = [
    dict(repo="documind-rag", title="DocuMind — RAG Document Q&A Pipeline",
         desc="Retrieval-augmented document Q&A running local LLMs end-to-end, containerized for portable deployment.",
         chips=["LangChain", "ChromaDB", "Ollama", "Docker", "HF Spaces"], lang="Python"),
    dict(repo="Model-Regression-Detection-System", title="Model Regression Detection System",
         desc="4-axis behavioral diff detector for LLM classifiers — CI-ready exit codes, versioned prompts, 75-case golden dataset.",
         chips=["Gemini 2.5 Flash", "Pytest", "YAML thresholds"], lang="Python"),
    dict(repo="evalbench-ai", title="EvalBench — LLM Evaluation Platform",
         desc="Open-source eval + regression gating — 4 scoring methods, versioned prompts, bootstrap confidence intervals.",
         chips=["Flask", "SQLAlchemy", "Docker", "CI/CD"], lang="Python"),
    dict(repo="Auto_News_Site", title="AutoHub — AI Automotive Platform",
         desc="24 vehicles, interactive 3D models, an AI car assistant and a live news feed — a pure front-end SPA on Cloud Run.",
         chips=["React 18", "Vite", "Tailwind", "Cloud Run"], lang="JavaScript"),
    dict(repo="ad-campaign-agent", title="Ad Campaign Agent",
         desc="Multi-agent retail video advertising platform built with Google ADK — Gemini 3 + Veo 3.1.",
         chips=["Google ADK", "Gemini 3", "Veo 3.1"], lang="Python"),
]

LANG_DOT = {"Python": "#3572A5", "JavaScript": "#F1E05A", "TypeScript": "#3178C6"}

FONT_VF_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/firacode/FiraCode%5Bwght%5D.ttf"

W = 880  # full-width card viewBox width

# ----------------------------------------------------------------------------
# Fonts: download once, instance wght 400/600, subset per card, embed as WOFF
# ----------------------------------------------------------------------------

_ADV = None  # advance-width ratio (em units), measured from the font


def _font_static(weight: int) -> Path:
    FONT_CACHE.mkdir(exist_ok=True)
    vf = FONT_CACHE / "FiraCode-VF.ttf"
    if not vf.exists():
        urllib.request.urlretrieve(FONT_VF_URL, vf)
    out = FONT_CACHE / f"FiraCode-{weight}.ttf"
    if not out.exists():
        from fontTools import ttLib
        from fontTools.varLib.instancer import instantiateVariableFont
        f = ttLib.TTFont(vf)
        instantiateVariableFont(f, {"wght": weight}, inplace=True)
        f.save(out)
    return out


def _advance_ratio() -> float:
    global _ADV
    if _ADV is None:
        from fontTools import ttLib
        f = ttLib.TTFont(_font_static(400))
        upm = f["head"].unitsPerEm
        _ADV = f["hmtx"]["M"][0] / upm
    return _ADV


def text_w(s: str, size: float) -> float:
    """Exact width of a string: Fira Code is monospaced."""
    return len(s) * size * _advance_ratio()


def _subset_woff_b64(text: str, weight: int) -> str:
    """pyftsubset the static font down to this card's glyphs -> base64 WOFF."""
    chars = "".join(sorted(set(text + " ")))
    src = _font_static(weight)
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / "chars.txt"
        tf.write_text(chars, encoding="utf-8")
        out = Path(td) / "sub.woff"
        subprocess.run(
            ["pyftsubset", str(src), f"--text-file={tf}", "--flavor=woff",
             f"--output-file={out}", "--layout-features=", "--no-hinting",
             "--desubroutinize", "--name-IDs="],
            check=True, capture_output=True)
        return base64.b64encode(out.read_bytes()).decode()


def font_faces(card_text: str) -> str:
    faces = []
    for weight in (400, 600):
        b64 = _subset_woff_b64(card_text, weight)
        faces.append(
            f"@font-face{{font-family:'FC';font-weight:{weight};"
            f"src:url(data:font/woff;base64,{b64}) format('woff');}}")
    return "".join(faces)


# ----------------------------------------------------------------------------
# Small SVG helpers
# ----------------------------------------------------------------------------

def esc(s: str) -> str:
    return _esc(str(s))


def wrap(s: str, max_chars: int, max_lines: int = 2):
    words, lines, cur = s.split(), [], ""
    for w_ in words:
        cand = (cur + " " + w_).strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max_chars - 1].rstrip() + "…"
    return lines


def txt(x, y, s, size=14, fill=TEXT, weight=400, anchor="start", cls="", spacing=None):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    c = f' class="{cls}"' if cls else ""
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" font-family="FC" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}"{a}{c}{ls}>{esc(s)}</text>')


ANIM_RESET = ("@media (prefers-reduced-motion: reduce){"
              "*{animation:none !important;transition:none !important;}}")

KEYFRAMES = (
    "@keyframes rise{from{opacity:0;transform:translateY(14px);}}"
    "@keyframes fade{from{opacity:0;}}"
    "@keyframes pop{from{opacity:0;transform:scale(.6);}}"
    "@keyframes grow{from{transform:scaleY(0);}}"
    "@keyframes sweep{from{transform:translateX(-18px);opacity:0;}}"
    "@keyframes drift{from{transform:translateX(0);}to{transform:translateX(-160px);}}"
)


def style_block(card_text: str, rules: str) -> str:
    """Inline <style>: embedded fonts + keyframes + animation rules.
    STATIC=1 drops every animation so the final frame renders."""
    css = font_faces(card_text)
    if not STATIC:
        css += KEYFRAMES + rules
    css += ANIM_RESET
    return f"<style>{css}</style>"


def svg_open(w, h, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">')


def card_bg(w, h, r=14, fill=PANEL):
    return (f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="{r}" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="1"/>')


def chip(x, y, label, delay, fill=PANEL2, color=ACCENT, size=11.5):
    w_ = text_w(label, size) + 18
    a = "" if STATIC else f' style="animation:pop .45s cubic-bezier(.2,.9,.3,1.4) {delay:.2f}s both;transform-origin:{x + w_/2}px {y+10}px"'
    return (f'<g{a}><rect x="{x}" y="{y}" width="{w_:.0f}" height="21" rx="10.5" '
            f'fill="{fill}" stroke="{BORDER}" stroke-width="1"/>'
            + txt(x + w_ / 2, y + 14.5, label, size, color, 400, "middle") + "</g>", w_)


def anim(rule_delay: str) -> str:
    return "" if STATIC else f' style="animation:{rule_delay}"'


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------

def load_days():
    p = DATA / "contributions.json"
    if not p.exists():
        sys.exit("data/contributions.json missing — run: python render_cards.py fetch")
    j = json.loads(p.read_text())
    days = [(dt.date.fromisoformat(d["date"]), int(d["count"])) for d in j["days"]]
    days.sort()
    return j, days


def month_series(days):
    """Totals for the last 12 calendar months (oldest first)."""
    by = {}
    for d, c in days:
        by.setdefault((d.year, d.month), 0)
        by[(d.year, d.month)] += c
    last = days[-1][0]
    out = []
    y, m = last.year, last.month
    for _ in range(12):
        out.append(((y, m), by.get((y, m), 0)))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def stats(days):
    counts = dict(days)
    last = days[-1][0]
    streak, d = 0, last
    if counts.get(d, 0) == 0:          # today may not have activity yet
        d -= dt.timedelta(days=1)
    while counts.get(d, 0) > 0:
        streak += 1
        d -= dt.timedelta(days=1)
    active = sum(1 for _, c in days if c > 0)
    bd, bc = max(days, key=lambda t: t[1])
    return streak, active, (bd, bc)


# ----------------------------------------------------------------------------
# Cards
# ----------------------------------------------------------------------------

def hero():
    h = 240
    avatar = DATA / "avatar.png"
    has_avatar = avatar.exists()
    body_parts, card_text = [], NAME + TAGLINE + SUBLINE + USER

    waves = []
    for i, (opac, amp, yy, dur) in enumerate(
            [(0.35, 18, 168, 13), (0.5, 24, 184, 9), (0.9, 30, 200, 11)]):
        pts = []
        for xx in range(-160, W + 161, 40):
            pts.append(f"{xx},{yy + amp * (0.6 if (xx // 40) % 2 else -0.6):.0f}")
        path = "M-160,{0} C ".format(yy) + " ".join(pts[1:]) + f" L{W+160},{h} L-160,{h} Z"
        a = "" if STATIC else f' style="animation:drift {dur}s linear infinite alternate"'
        waves.append(f'<path d="{path}" fill="{NAVY}" opacity="{opac}"{a}/>')

    tx = 56
    body_parts.append(f'<g{anim("rise .7s ease-out .05s both")}>' +
                      txt(tx, 96, NAME, 34, WHITE, 600) + "</g>")
    body_parts.append(f'<g{anim("rise .7s ease-out .2s both")}>' +
                      txt(tx, 130, TAGLINE, 15.5, TEXT) + "</g>")
    body_parts.append(f'<g{anim("rise .7s ease-out .35s both")}>' +
                      txt(tx, 156, SUBLINE, 13, ACCENT) + "</g>")
    underline_w = text_w(NAME, 34)
    u = "" if STATIC else ' style="animation:grow .6s ease-out .45s both;transform-origin:56px 0"'
    body_parts.append(f'<rect x="{tx}" y="106" width="{underline_w:.0f}" height="3" rx="1.5" fill="{ACCENT}"{u} transform="scale(1,1)"/>')

    portrait = ""
    if has_avatar:
        b64 = base64.b64encode(avatar.read_bytes()).decode()
        cx, cy, r = W - 118, 104, 62
        portrait = (
            f'<g{anim("pop .7s cubic-bezier(.2,.9,.3,1.3) .3s both")} '
            f'transform-origin="{cx}px {cy}px">'
            f'<circle cx="{cx}" cy="{cy}" r="{r+5}" fill="none" stroke="{ACCENT}" stroke-width="2" opacity="0.8"/>'
            f'<clipPath id="pc"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>'
            f'<image href="data:image/png;base64,{b64}" x="{cx-r}" y="{cy-r}" '
            f'width="{2*r}" height="{2*r}" clip-path="url(#pc)" preserveAspectRatio="xMidYMid slice"/></g>')

    rules = ""
    return "hero.svg", (
        svg_open(W, h, f"{NAME} — {TAGLINE}")
        + style_block(card_text, rules)
        + f'<defs><linearGradient id="hg" x1="0" y1="0" x2="1" y2="1">'
          f'<stop offset="0" stop-color="{NAVY_DEEP}"/><stop offset="1" stop-color="{PANEL}"/></linearGradient>'
          f'<clipPath id="hc"><rect width="{W}" height="{h}" rx="14"/></clipPath></defs>'
        + f'<g clip-path="url(#hc)"><rect width="{W}" height="{h}" fill="url(#hg)"/>'
        + "".join(waves) + "</g>"
        + f'<rect x="0.5" y="0.5" width="{W-1}" height="{h-1}" rx="14" fill="none" stroke="{BORDER}"/>'
        + "".join(body_parts) + portrait + "</svg>")


ICONS = {
    "hammer": "M3 14 L10 7 M8 5 l4 -2 3 3 -2 4 -3 -3 z",
    "play":   "M6 4 L14 9 L6 14 Z",
    "link":   "M7 11 a3.5 3.5 0 0 1 0 -5 l2 -2 a3.5 3.5 0 0 1 5 5 l-1 1 M11 7 a3.5 3.5 0 0 1 0 5 l-2 2 a3.5 3.5 0 0 1 -5 -5 l1 -1",
}


def tile(i, spec):
    w_, h = 300, 112
    base = 0.35 + i * 0.15
    card_text = spec["title"] + "".join(spec["lines"]) + "→"
    icon = (f'<g transform="translate(22,20)" fill="none" stroke="{ACCENT}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{ICONS[spec["icon"]]}" transform="scale(1.1)"/></g>')
    inner = [
        f'<g{anim(f"pop .5s cubic-bezier(.2,.9,.3,1.3) {base+0.1:.2f}s both")} transform-origin="30px 28px">{icon}</g>',
        f'<g{anim(f"sweep .5s ease-out {base+0.18:.2f}s both")}>' +
        txt(52, 33, spec["title"], 12, ACCENT, 600, spacing="2") + "</g>",
        f'<g{anim(f"sweep .5s ease-out {base+0.28:.2f}s both")}>' +
        txt(22, 64, spec["lines"][0], 13.5, WHITE, 600) + "</g>",
        f'<g{anim(f"sweep .5s ease-out {base+0.38:.2f}s both")}>' +
        txt(22, 86, spec["lines"][1], 12, MUTED) + "</g>",
        f'<g{anim(f"fade .5s ease-out {base+0.5:.2f}s both")}>' +
        txt(w_ - 20, 86, "→", 15, ACCENT, 600, "end") + "</g>",
    ]
    return f"tile-{spec['slug']}.svg", (
        svg_open(w_, h, spec["alt"]) + style_block(card_text, "")
        + card_bg(w_, h, 12)
        + f'<rect x="0.5" y="0.5" width="4" height="{h-1}" rx="2" fill="{NAVY}"/>'
        + "".join(inner) + "</svg>")


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def contributions_card(j, days):
    h = 292
    months = month_series(days)
    streak, active, (bd, bc) = stats(days)
    total = sum(c for _, c in days)
    bd_label = bd.strftime("%b %d") + ("" if bd.year == days[-1][0].year else bd.strftime(" ’%y"))
    streak_label = f"{streak} day" + ("" if streak == 1 else "s")
    card_text = ("CONTRIBUTIONS · LAST 12 MONTHS current streak active days busiest day "
                 f"{total} total {streak_label} {active}/365 {bd_label} · {bc}"
                 + "".join(MONTHS) + "0123456789 days d’")

    parts = [card_bg(W, h)]
    parts.append(f'<g{anim("sweep .6s ease-out .9s both")}>' +
                 txt(28, 40, "CONTRIBUTIONS · LAST 12 MONTHS", 13, WHITE, 600, spacing="1.5") +
                 txt(28, 60, f"{total} total", 12, MUTED) + "</g>")

    # stat chips, right side of header
    defs = [("current streak", streak_label),
            ("active days", f"{active}/365"),
            ("busiest day", f"{bd_label} · {bc}")]
    cx = W - 28
    for k, (label, value) in enumerate(reversed(defs)):
        bw = max(text_w(value, 15), text_w(label, 10)) + 28
        cx -= bw
        d = 1.0 + (2 - k) * 0.12
        parts.append(
            f'<g{anim(f"rise .55s ease-out {d:.2f}s both")}>'
            f'<rect x="{cx:.0f}" y="24" width="{bw:.0f}" height="46" rx="10" fill="{PANEL2}" stroke="{BORDER}"/>'
            + txt(cx + bw / 2, 44, value, 15, ACCENT, 600, "middle")
            + txt(cx + bw / 2, 60, label, 9.5, MUTED, 400, "middle") + "</g>")
        cx -= 10

    # bars
    bx, by, bw_area, bh = 28, 96, W - 56, 150
    maxv = max((v for _, v in months), default=1) or 1
    slot = bw_area / 12
    bar_w = min(42, slot - 18)
    for i, ((y, m), v) in enumerate(months):
        x = bx + i * slot + (slot - bar_w) / 2
        hh = max(3, (v / maxv) * (bh - 8))
        yy = by + bh - hh
        d = 0.95 + i * 0.06
        g = "" if STATIC else (f' style="animation:grow .6s cubic-bezier(.2,.8,.3,1.1) {d:.2f}s both;'
                               f'transform-origin:{x + bar_w/2}px {by + bh}px"')
        parts.append(f'<rect x="{x:.1f}" y="{yy:.1f}" width="{bar_w:.1f}" height="{hh:.1f}" '
                     f'rx="5" fill="{BLUE_2 if v < maxv else ACCENT}"{g}/>')
        parts.append(f'<g{anim(f"fade .4s ease-out {d+0.35:.2f}s both")}>' +
                     txt(x + bar_w / 2, yy - 8, str(v), 11, TEXT, 600, "middle") + "</g>")
        parts.append(txt(x + bar_w / 2, by + bh + 22, MONTHS[m - 1], 11, MUTED, 400, "middle"))
    parts.append(f'<line x1="{bx}" y1="{by+bh}" x2="{bx+bw_area}" y2="{by+bh}" stroke="{BORDER}" stroke-width="1"/>')

    return "contributions.svg", (
        svg_open(W, h, f"Contributions, last 12 months: {total} total, "
                       f"{streak}-day streak, {active} active days, busiest {bd.strftime('%b %d')} with {bc}")
        + style_block(card_text, "") + "".join(parts) + "</svg>")


def repo_card(i, spec):
    h = 132
    base = 1.2 + i * 0.18
    desc_lines = wrap(spec["desc"], 86)
    card_text = spec["title"] + spec["desc"] + " ".join(spec["chips"]) + spec["lang"] + spec["repo"] + "→"

    parts = [card_bg(W, h, 12),
             f'<rect x="0.5" y="0.5" width="4" height="{h-1}" rx="2" fill="{NAVY}"/>']
    parts.append(f'<g{anim(f"sweep .55s ease-out {base:.2f}s both")}>' +
                 txt(30, 36, spec["title"], 16.5, WHITE, 600) + "</g>")
    dot = LANG_DOT.get(spec["lang"], ACCENT)
    lang_w = text_w(spec["lang"], 11.5)
    parts.append(f'<g{anim(f"fade .5s ease-out {base+0.15:.2f}s both")}>'
                 f'<circle cx="{W - 42 - lang_w:.0f}" cy="31" r="5" fill="{dot}"/>'
                 + txt(W - 30, 35, spec["lang"], 11.5, MUTED, 400, "end")
                 + txt(W - 30, 110, "→", 15, ACCENT, 600, "end") + "</g>")
    for li, line in enumerate(desc_lines):
        parts.append(f'<g{anim(f"sweep .55s ease-out {base+0.1+li*0.08:.2f}s both")}>' +
                     txt(30, 60 + li * 18, line, 12.5, TEXT) + "</g>")
    x = 30
    cy = 96
    for ci, c in enumerate(spec["chips"]):
        g, w_ = chip(x, cy, c, base + 0.3 + ci * 0.08)
        parts.append(g)
        x += w_ + 8

    return f"repo-{spec['repo'].lower()}.svg", (
        svg_open(W, h, f"{spec['title']} — {spec['desc']}")
        + style_block(card_text, "") + "".join(parts) + "</svg>")


def graph_card(j, days):
    cell, gap = 12, 3
    counts = dict(days)
    last = days[-1][0]
    # grid: full weeks, Sunday-start, ending at the current week
    end_sunday = last - dt.timedelta(days=(last.weekday() + 1) % 7)
    weeks = 53
    gx, gy = 56, 58
    gw = weeks * (cell + gap) - gap          # 792
    w_card = W                               # match the other full-width cards
    h = gy + 7 * (cell + gap) + 44
    total = sum(c for _, c in days)
    maxv = max((c for _, c in days), default=1) or 1

    def level(c):
        if c <= 0:
            return 0
        q = c / maxv
        return 1 if q <= 0.25 else 2 if q <= 0.5 else 3 if q <= 0.75 else 4

    parts = [card_bg(w_card, h)]
    parts.append(f'<g{anim("sweep .6s ease-out 1.75s both")}>' +
                 txt(28, 36, f"CONTRIBUTION GRAPH · {total} IN THE LAST YEAR",
                     13, WHITE, 600, spacing="1.5") + "</g>")

    month_labels, seen = [], None
    for wk in range(weeks):
        monday = end_sunday - dt.timedelta(weeks=(weeks - 1 - wk))
        for dow in range(7):
            d = monday + dt.timedelta(days=dow)
            if d > last:
                continue
            c = counts.get(d, 0)
            x = gx + wk * (cell + gap)
            y = gy + dow * (cell + gap)
            delay = 1.85 + (wk + dow) * 0.016
            a = "" if STATIC else (f' style="animation:pop .4s ease-out {delay:.3f}s both;'
                                   f'transform-origin:{x + cell/2}px {y + cell/2}px"')
            parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" '
                         f'fill="{HEAT_RAMP[level(c)]}"{a}/>')
        if monday.day <= 7 and monday.month != seen:
            seen = monday.month
            month_labels.append(txt(gx + wk * (cell + gap), gy - 8, MONTHS[monday.month - 1], 10, MUTED))
    parts += month_labels
    for dow, lab in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        parts.append(txt(gx - 8, gy + dow * (cell + gap) + cell - 2, lab, 9.5, MUTED, 400, "end"))

    lx = w_card - 28 - 5 * (cell + gap) - text_w("less", 10) - text_w("more", 10) - 16
    parts.append(txt(lx, h - 18, "less", 10, MUTED))
    for i_ in range(5):
        parts.append(f'<rect x="{lx + text_w("less",10) + 8 + i_*(cell+gap):.0f}" y="{h-28}" '
                     f'width="{cell}" height="{cell}" rx="2.5" fill="{HEAT_RAMP[i_]}"/>')
    parts.append(txt(lx + text_w("less", 10) + 8 + 5 * (cell + gap) + 8, h - 18, "more", 10, MUTED))

    card_text = (f"CONTRIBUTION GRAPH · {total} IN THE LAST YEAR lessmore MonWedFri"
                 + "".join(MONTHS) + "0123456789")
    svg = (svg_open(w_card, h, f"Contribution graph: {total} contributions in the last year")
           + style_block(card_text, "") + "".join(parts) + "</svg>")
    return "graph.svg", svg


# ----------------------------------------------------------------------------
# fetch: contributions.json (+ avatar)
# ----------------------------------------------------------------------------

def _http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch():
    DATA.mkdir(exist_ok=True)
    token = os.environ.get("GITHUB_TOKEN", "")
    days = None
    if token:
        q = {"query": "query($l:String!){user(login:$l){contributionsCollection{"
                      "contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}",
             "variables": {"l": USER}}
        try:
            raw = _http("https://api.github.com/graphql", json.dumps(q).encode(),
                        {"Authorization": f"bearer {token}", "Content-Type": "application/json"})
            weeks = json.loads(raw)["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
            days = [{"date": d["date"], "count": d["contributionCount"]}
                    for wk in weeks for d in wk["contributionDays"]]
        except Exception as e:
            print(f"GraphQL fetch failed ({e}); trying public page", file=sys.stderr)
    if days is None:
        try:
            html = _http(f"https://github.com/users/{USER}/contributions").decode()
            cells = re.findall(r'data-date="(\d{4}-\d\d-\d\d)"[^>]*data-level="(\d)"', html)
            tips = dict(re.findall(r'(\d+|No) contributions? on [^<]*?(\d{4}-\d\d-\d\d)', html))
            lvl = {0: 0, 1: 2, 2: 5, 3: 9, 4: 14}
            days = [{"date": d, "count": int(tips[d]) if tips.get(d, "No").isdigit()
                     else lvl[int(l)]} for d, l in cells]
        except Exception as e:
            print(f"Public page fetch failed ({e}); writing PLACEHOLDER data", file=sys.stderr)
            rng = hashlib.sha256(USER.encode()).digest()
            today = dt.date.today()
            days = []
            for i in range(366):
                d = today - dt.timedelta(days=365 - i)
                b = rng[i % 32] ^ (i * 7 & 0xFF)
                c = 0 if b % 5 < 2 else (b % 9)
                days.append({"date": d.isoformat(), "count": c})
            placeholder = True
        else:
            placeholder = False
    else:
        placeholder = False
    days.sort(key=lambda d: d["date"])
    out = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "user": USER, "placeholder": placeholder,
           "total": sum(d["count"] for d in days), "days": days}
    (DATA / "contributions.json").write_text(json.dumps(out, indent=1))
    print(f"wrote data/contributions.json ({out['total']} contributions"
          f"{', PLACEHOLDER' if placeholder else ''})")
    try:
        png = _http(f"https://avatars.githubusercontent.com/{USER}?size=420")
        (DATA / "avatar.png").write_bytes(png)
        print("wrote data/avatar.png")
    except Exception as e:
        print(f"avatar fetch failed ({e}) — hero renders without portrait", file=sys.stderr)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        fetch()
        return
    j, days = load_days()
    CARDS.mkdir(exist_ok=True)
    outputs = [hero()]
    outputs += [tile(i, t) for i, t in enumerate(TILES)]
    outputs.append(contributions_card(j, days))
    outputs += [repo_card(i, r) for i, r in enumerate(FEATURED)]
    outputs.append(graph_card(j, days))
    for name, svg in outputs:
        (CARDS / name).write_text(svg, encoding="utf-8")
        print(f"cards/{name}  {len(svg)//1024}KB{'  [static]' if STATIC else ''}")
    if j.get("placeholder"):
        print("\nNOTE: contributions.json is PLACEHOLDER data — the first "
              "workflow run will replace it with your real history.")


if __name__ == "__main__":
    main()
