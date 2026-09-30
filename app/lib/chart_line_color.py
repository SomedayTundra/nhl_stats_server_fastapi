###################################################
# PICKS EACH TEAM'S CHART LINE COLOR FROM ITS OWN LOGO
#
# A team's line color is the color that covers the most area of its (era-correct) logo, ignoring
# white, black, and grays - those are either background or read as "no color" on the chart. Every
# logo yields a ranked list of candidate colors rather than just one, because many crests land on
# the same handful of colors (TOR, TBL, EDM, WPG, CBJ, FLA, NSH, SEA, and VAN all measure out to
# essentially the same dark navy). Within a single season - the only scope the chart ever draws at
# once - a team whose top color is too close to one already taken falls back to its next candidate
# (FLA and NSH land on their gold that way).
#
# Colors are always assigned for a whole season at a time, in a fixed order that doesn't depend on
# which order teams were farmed in, so update_mongodb.py (which adds teams one at a time) and
# backfill_chart_line_color.py (which recolors every season at once) always agree.
###################################################

import colorsys
import io
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import resvg_py
from PIL import Image

# app/logos, resolved relative to this file so it works regardless of CWD or OS
LOGOS_DIR = Path(__file__).resolve().parents[1] / "logos"

# width to rasterize a logo's SVG at. Every crest shares a 960x640 viewBox, so this is 256x171 -
# plenty of pixels to measure area from, and cheap enough to do ~165 logos in a couple of seconds
RENDER_WIDTH = 256

# pixels more transparent than this are anti-aliased edges or background, not logo
MIN_ALPHA = 200

# a pixel whose brightest and dimmest channels are closer than this is white, black, or a gray -
# none of which make a usable line color
MIN_CHROMA = 30

# candidates are grouped by hue (in bins this many degrees wide) and by lightness band, so a
# logo's navy and its lighter blue stay separate choices while the anti-aliased shades of one
# flat color still land in the same group
HUE_BIN_DEGREES = 20
LIGHTNESS_BANDS = 3

# two teams in the same season closer than this (CIE76 delta-E) would be hard to tell apart as
# chart lines, so the later one moves on to its next candidate
MIN_DELTA_E = 10

# a logo's secondary colors only count as candidates if they cover at least this much of it -
# otherwise a collision would push a team onto a thin outline or highlight (CAR's pink edge
# shading, BOS's cream) that nobody would recognize as that team's color
MIN_ALTERNATE_SHARE = 0.2

# when every real candidate collides, the team keeps its top color but shifted lighter or darker
# (HLS lightness, alternating, growing by this step) until it's clear of everyone else - the same
# kind of "own shade within the same family" nudge the old hand-picked colors used
SHADE_STEP = 0.06
MAX_SHADE_STEPS = 6

# logos with no color at all - every visible pixel is black, white, or silver - get the team's
# well-known color instead. Only a team's colorless era falls back here; its other logos are
# still measured normally
NO_COLOR_FALLBACK = {
    "LAK": "#6F9BD1",  # "Forum Blue", for the silver-and-black crests since 1988-89
    "CHI": "#CF0A2C",  # Blackhawks red, for the black-and-white 1926-27 through 1956-57 crest
}
DEFAULT_COLOR = "#808080"


@dataclass(frozen=True)
class Candidate:
    color: str  # "#RRGGBB"
    share: float  # fraction of the logo's colored pixels this candidate covers


def _render_logo(local_logo: str) -> Image.Image:
    svg_path = LOGOS_DIR / local_logo
    try:
        png_bytes = bytes(resvg_py.svg_to_bytes(svg_path=str(svg_path), width=RENDER_WIDTH))
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except Exception:
        # the pre-rasterized PNG build-logos.mjs writes next to each SVG, if resvg can't cope
        return Image.open(svg_path.with_name(f"{svg_path.stem}@2x.png")).convert("RGBA")


@cache
def logo_color_candidates(local_logo: str) -> tuple[Candidate, ...]:
    """Every distinct color on the logo, most area first."""
    image = _render_logo(local_logo)

    # group key -> [pixel count, r sum, g sum, b sum]
    groups: dict[tuple[int, int], list[int]] = {}
    for r, g, b, a in image.get_flattened_data():
        if a < MIN_ALPHA or max(r, g, b) - min(r, g, b) < MIN_CHROMA:
            continue
        hue, lightness, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        # offset by half a bin so pure red (hue 0) sits in the middle of a bin, not on its edge
        hue_bin = int(hue * 360 + HUE_BIN_DEGREES / 2) // HUE_BIN_DEGREES % (360 // HUE_BIN_DEGREES)
        band = min(int(lightness * LIGHTNESS_BANDS), LIGHTNESS_BANDS - 1)
        group = groups.setdefault((hue_bin, band), [0, 0, 0, 0])
        group[0] += 1
        group[1] += r
        group[2] += g
        group[3] += b

    total = sum(group[0] for group in groups.values())
    candidates = [
        Candidate(
            color="#{:02X}{:02X}{:02X}".format(*(round(channel / count) for channel in sums)),
            share=count / total,
        )
        for count, *sums in groups.values()
    ]
    candidates.sort(key=lambda candidate: candidate.share, reverse=True)
    return tuple(candidates)


def _hex_to_lab(color: str) -> tuple[float, float, float]:
    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(int(color[i:i + 2], 16)) for i in (1, 3, 5))
    # sRGB -> XYZ (D65), normalized by the D65 white point
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(color_a: str, color_b: str) -> float:
    lab_a, lab_b = _hex_to_lab(color_a), _hex_to_lab(color_b)
    return sum((p - q) ** 2 for p, q in zip(lab_a, lab_b)) ** 0.5


def _shade_variants(color: str):
    """The same hue, alternately lighter and darker, a little further each time."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    for step in range(1, MAX_SHADE_STEPS + 1):
        for direction in (1, -1):
            shifted = min(max(lightness + direction * step * SHADE_STEP, 0.08), 0.85)
            yield "#{:02X}{:02X}{:02X}".format(
                *(round(channel * 255) for channel in colorsys.hls_to_rgb(hue, shifted, saturation))
            )


def assign_season_colors(teams: list[dict[str, Any]]) -> dict[str, str]:
    """teamAbbrev -> chart line color for every team in one season's team_data document."""
    candidates_by_abbrev = {team["teamAbbrev"]: logo_color_candidates(team["localLogo"]) for team in teams}

    # the team with the most dominant single color gets first claim on it; abbrev breaks ties so
    # the order never depends on how the teams happen to be stored
    def claim_order(abbrev: str) -> tuple[float, str]:
        candidates = candidates_by_abbrev[abbrev]
        return (-candidates[0].share if candidates else 0.0, abbrev)

    assigned: dict[str, str] = {}
    for abbrev in sorted(candidates_by_abbrev, key=claim_order):
        candidates = candidates_by_abbrev[abbrev]
        if not candidates:
            assigned[abbrev] = NO_COLOR_FALLBACK.get(abbrev, DEFAULT_COLOR)
            continue
        taken = list(assigned.values())

        def is_clear(color: str) -> bool:
            return all(delta_e(color, other) >= MIN_DELTA_E for other in taken)

        top, *alternates = candidates
        options = [top.color, *(c.color for c in alternates if c.share >= MIN_ALTERNATE_SHARE)]
        assigned[abbrev] = next(
            (color for color in [*options, *_shade_variants(top.color)] if is_clear(color)),
            # nothing is clear of everyone - the logo's own top color still beats a made-up one
            top.color,
        )
    return assigned


def recolor_season(collection_team_data, season_id: int, dry_run: bool = False) -> dict[str, str]:
    """(Re)assigns chartLineColor to every team in one season's team_data document."""
    doc = collection_team_data.find_one({"seasonId": season_id})
    if doc is None:
        return {}
    colors = assign_season_colors(doc.get("teams", []))
    if not dry_run:
        for abbrev, color in colors.items():
            collection_team_data.update_one(
                {"seasonId": season_id},
                {"$set": {"teams.$[team].chartLineColor": color}},
                array_filters=[{"team.teamAbbrev": abbrev}],
            )
    return colors
