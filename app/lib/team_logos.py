###################################################
# DARK-BACKGROUND VARIANTS OF THE TEAM LOGOS
#
# The NHL publishes most crests in two versions on assets.nhle.com: `..._light.svg`, drawn for a
# light page, and `..._dark.svg`, recolored for a dark one (black outlines turned light, and so
# on). The standings payload hands us both (`teamLogo`, `teamLogoDark`), and the playoff bracket
# payload carries `logo`/`darkLogo`. A handful of historical crests have no dark version at all
# (the 1940-1995 Bruins crests, NYI 2010-17, WSH 1995-2007); for those localLogoDark is stored as
# None and clients fall back to the light logo.
#
# Dark files live next to the light ones in app/logos, under the NHL's own filename, so the
# /nhl_team_info/logo route serves them unchanged. Run `npm run build:logos` after new ones land
# so they get the same svgo pass and pre-rasterized PNGs as the light set.
###################################################

from pathlib import Path
from typing import Optional

import httpx

# app/logos, resolved relative to this file so it works regardless of CWD or OS
LOGOS_DIR = Path(__file__).resolve().parents[1] / "logos"


def logo_filename(logo_url: str) -> str:
    # the last path segment, minus any query string (the SVGs are occasionally parameterized)
    return logo_url.split("/")[-1].split("?")[0]


def dark_logo_url(light_logo_url: str, api_dark_logo_url: Optional[str] = None) -> Optional[str]:
    """The dark crest's URL: the API's own value when it gave one, else derived from the light URL."""
    if api_dark_logo_url:
        return api_dark_logo_url
    name = logo_filename(light_logo_url)
    if not name.endswith("_light.svg"):
        return None
    return light_logo_url.split("?")[0][: -len("_light.svg")] + "_dark.svg"


def ensure_local_logo(logo_url: str, client: Optional[httpx.Client] = None) -> Optional[str]:
    """
    Make sure the logo at `logo_url` is saved in app/logos, downloading it if needed. Returns its
    filename, or None when the NHL doesn't have that file (a crest with no dark version 404s).
    """
    name = logo_filename(logo_url)
    path = LOGOS_DIR / name
    if path.is_file():
        return name

    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    try:
        response = client.get(logo_url)
    finally:
        if own_client:
            client.close()
    if response.status_code != 200:
        return None
    path.write_bytes(response.content)
    print(f"Downloaded: {name}, saved to: {path}")
    return name
