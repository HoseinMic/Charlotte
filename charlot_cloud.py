import csv
import io
import sys
import re
import os
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
import json
import sqlite3
import textwrap
import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional
import requests
import importlib
import importlib.util

def _try_import(module_name: str):
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return None, f"{module_name} not found on sys.path"
    try:
        mod = importlib.import_module(module_name)
        return mod, None
    except Exception as e:
        return None, f"{module_name} import failed: {type(e).__name__}: {e}"

# mlconjug3 (offline)
mlconjug3, _MLCONJUG3_ERR = _try_import("mlconjug3")

# Reverso-API wrapper (online, unofficial)
_reverso_api_mod, _REVERSO_ERR = _try_import("reverso_api")
ReversoAPI = getattr(_reverso_api_mod, "ReversoAPI", None) if _reverso_api_mod else None
if _reverso_api_mod is not None and ReversoAPI is None and _REVERSO_ERR is None:
    _REVERSO_ERR = "reverso_api imported, but ReversoAPI class not found (version mismatch?)"


import streamlit as st
import streamlit.components.v1 as components

import warnings
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated as an API.*",
    category=UserWarning,
)

# =========================
# Config
# =========================
APP_TITLE = "Charlot"
DB_PATH = "charlot.sqlite3"

DICTAPI_BASE = "https://api.dictionaryapi.dev/api/v2/entries"
WIKTIONARY_BASE = {"fr": "https://fr.wiktionary.org", "en": "https://en.wiktionary.org"}

HTTP_HEADERS = {
    "User-Agent": "Charlot/9.0 (Streamlit; educational app)",
    "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
}

# st.set_page_config(page_title=APP_TITLE, page_icon="🇫🇷", layout="wide")

st.set_page_config(page_title=APP_TITLE,page_icon="💁‍♀️", layout="centered")

st.markdown("""
<style>
/* Main content container max width */
section.main > div { max-width: 1080px; margin: 0 auto; }

/* Optional: reduce side padding */
section.main { padding-left: 1rem; padding-right: 1rem; }
</style>
""", unsafe_allow_html=True)


# =========================
# Theme tokens
# =========================
THEMES = {
    "Dark": {
        "bg": "#0b0f17",
        "bg2": "#0f1623",
        "surface": "rgba(255,255,255,.06)",
        "surface2": "rgba(255,255,255,.04)",
        "txt": "rgba(255,255,255,.92)",
        "mut": "rgba(255,255,255,.66)",
        "mut2": "rgba(255,255,255,.46)",
        "line": "rgba(255,255,255,.1)",
        "brand": "#58cc02",
        "brand2": "#1cb0f6",
        "warn": "#ffcc00",
        "danger": "#ff4b4b",
        "shadow": "0 14px 40px rgba(0,0,0,.45)",
        "shadow2": "0 10px 26px rgba(0,0,0,.35)",
        "chip": "rgba(255,255,255,.08)",
        "chip_border": "rgba(255,255,255,.12)",
    },
    "Light": {
        "bg": "#f7f8fb",
        "bg2": "#eef2f8",
        "surface": "rgba(255,255,255,1.0)",
        "surface2": "rgba(255,255,255,.72)",
        "txt": "rgba(12,16,20,.94)",
        "mut": "rgba(12,16,20,.66)",
        "mut2": "rgba(12,16,20,.48)",
        "line": "rgba(12,16,20,.10)",
        "brand": "#58cc02",
        "brand2": "#1cb0f6",
        "warn": "#ffcc00",
        "danger": "#ff4b4b",
        "shadow": "0 14px 34px rgba(16,24,40,.12)",
        "shadow2": "0 10px 22px rgba(16,24,40,.10)",
        "chip": "rgba(12,16,20,.06)",
        "chip_border": "rgba(12,16,20,.10)",
    },
}

PAGES = [
    ("🏠", "Home"),
    ("📚", "Dictionary"),
    ("🧠", "Review"),
    ("🗂️", "Cards"),
    ("📝", "Notes"),
    ("📘", "Grammar"),
    ("🔁", "Import"),
    ("⚙️", "Settings"),
    ("❓", "About"),
]

# =========================
# Session state
# =========================
def init_session_state() -> None:
    ss = st.session_state
    ss.setdefault("nav", "Home")
    ss.setdefault("nav_pending", None)
    ss.setdefault("theme", "Dark")
    ss.setdefault("xp", 0)
    ss.setdefault("streak", 1)
    ss.setdefault("last_xp_date", iso_date(today_utc_date()))
    ss.setdefault("ulapi_key", get_setting("ulapi_key", ""))
    ss.setdefault("openai_api_key", get_setting("openai_api_key", ""))
    ss.setdefault("openai_model", get_setting("openai_model", "gpt-5.2"))
    ss.setdefault("ai_notes_enabled", get_setting("ai_notes_enabled", "1"))
    ss.setdefault("conj_provider", "Free (Offline)")
    ss.setdefault("review_idx", 0)
    ss.setdefault("edit_card_id", None)
    ss.setdefault("selected_card_id", None)
    ss.setdefault("scroll_to_selected_card", False)
    ss.setdefault("scroll_to_editor", False)
    ss.setdefault("delete_confirm_id", None)
    ss.setdefault("cards_page", 1)
    ss.setdefault("cards_page_size", 18)
    ss.setdefault("global_query", "")
    ss.setdefault("nb_pdf_book_id", None)
    ss.setdefault("nb_pdf_page", 1)
    ss.setdefault("nb_pdf_zoom", 100)
    ss.setdefault("nb_vocab_q", "")
    ss.setdefault("nb_pdf_text_cache_page", None)
    ss.setdefault("nb_pdf_extracted_text", "")
    # --- Auth (multi-user) ---
    ss.setdefault("auth_user_id", None)
    ss.setdefault("auth_username", None)
    ss.setdefault("auth_is_admin", False)
    ss.setdefault("auth_prev_user_id", None)
    # aliases used by older UI parts
    ss.setdefault("username", "")
    ss.setdefault("is_admin", False)


# =========================
# Responsive breakpoint
# =========================
def detect_breakpoint(breakpoint_px: int = 760) -> str:
    """Return 'm' (mobile) or 'd' (desktop) using a query-param probe."""
    try:
        bp = st.query_params.get("bp", None)
    except Exception:
        bp = st.experimental_get_query_params().get("bp", [None])[0]

    components.html(
        f"""
<script>
(function() {{
  const bp = (window.innerWidth <= {breakpoint_px}) ? "m" : "d";
  const url = new URL(window.location.href);
  const cur = url.searchParams.get("bp");
  if (!cur || cur !== bp) {{
    url.searchParams.set("bp", bp);
    window.location.href = url.toString();
  }}
}})();
</script>
""",
        height=0,
    )
    return bp or "d"

# =========================
# CSS
# =========================
def inject_global_css(theme_name: str) -> None:
    t = THEMES.get(theme_name, THEMES["Dark"])
    css = f"""
<style>
:root {{
  --bg:{t["bg"]};
  --bg2:{t["bg2"]};
  --surface:{t["surface"]};
  --surface2:{t["surface2"]};
  --line:{t["line"]};
  --txt:{t["txt"]};
  --mut:{t["mut"]};
  --mut2:{t["mut2"]};
  --brand:{t["brand"]};
  --brand2:{t["brand2"]};
  --warn:{t["warn"]};
  --danger:{t["danger"]};
  --chip:{t["chip"]};
  --chipb:{t["chip_border"]};
  --sh:{t["shadow"]};
  --sh2:{t["shadow2"]};
  --r12:12px;
  --r16:16px;
  --r20:20px;
  --r24:24px;
  --r28:28px;
}}

html, body, [class*="css"] {{
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
}}
.stApp {{
  background:
    radial-gradient(900px 520px at 12% -10%, rgba(28,176,246,.18), transparent 60%),
    radial-gradient(900px 520px at 88% 0%, rgba(88,204,2,.14), transparent 55%),
    linear-gradient(180deg, var(--bg) 0%, var(--bg2) 100%);
  color: var(--txt);
}}

.block-container {{
  padding-top: .9rem;
  padding-bottom: 4.0rem;
  max-width: 1200px;
}}

header[data-testid="stHeader"]{{ background: rgba(0,0,0,0); }}
div[data-testid="stToolbar"]{{ visibility: hidden; height: 0px; }}
footer{{ visibility:hidden; }}

::selection {{ background: rgba(88,204,2,.22); }}

/* Prevent button labels from wrapping character-by-character on narrow cards */
div.stButton > button, div.stButton > button * {{
  white-space: nowrap !important;
}}

@keyframes fadeIn {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to   {{ opacity: 1; transform: translateY(0px); }}
}}
.page {{ animation: fadeIn .18s ease-out; }}

.card {{
  background: linear-gradient(180deg, var(--surface), var(--surface2));
  border-radius: var(--r24);
  box-shadow: var(--sh2);
  padding: 18px 18px;
}}
.card-tight {{ border-radius: var(--r20); padding: 14px 16px; }}
.h-title {{ font-weight: 950; font-size: 18px; letter-spacing: .4px; }}
.h-sub {{ color: var(--mut); margin-top: 0px; font-size: 13px; line-height: 1.35; }}
/* Control spacing around the divider inside cards */
.card hr {{
  margin: 10px 0;   /* top/bottom spacing — reduce this */
}}

.chip {{
  display:inline-flex; align-items:center; gap:8px;
  background: var(--chip);
  border: 1px solid var(--chipb);
  border-radius: 999px;
  padding: 7px 12px;
  color: var(--mut);
  font-size: 13px;
  font-weight: 850;
}}
.chip b {{ color: var(--txt); font-weight: 1000; }}
.small {{ font-size: 13px; color: var(--mut); }}

.statline {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; }}
.statlabel {{ font-weight: 850; color: var(--txt); }}
.statvalue {{ font-weight: 900; font-size: 20px; color: var(--txt); }}

hr {{ border-color: var(--line) !important; }}

div[data-testid="stWidgetLabel"] label {{
  color: var(--mut) !important;
  font-weight: 850 !important;
}}

/* ===== Inputs: simple + flat ===== */
.stTextInput input,
.stTextArea textarea,
.stDateInput input,
.stNumberInput input {{
  color: var(--txt) !important;
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: var(--r12) !important;
  box-shadow: none !important;
}}

.stTextInput input:focus,
.stTextArea textarea:focus,
.stDateInput input:focus,
.stNumberInput input:focus {{
  border-color: var(--brand2) !important;
  outline: none !important;
  box-shadow: none !important;
}}

/* Select boxes: match inputs */
div[data-baseweb="select"] > div {{
  border-radius: var(--r12) !important;
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  box-shadow: none !important;
}}
div[data-baseweb="select"] * {{ color: var(--txt) !important; }}

/* Buttons — Duolingo-like (chunky + pressed) */
.stButton>button, .stDownloadButton>button{{
  border-radius: 16px !important;
  border: 2px solid rgba(0,0,0,0) !important;
  background: linear-gradient(180deg, var(--surface), var(--surface2)) !important;
  color: var(--txt) !important;
  font-weight: 1000 !important;
  letter-spacing: .2px !important;
  padding: .58rem 1.05rem !important;
  min-height: 44px !important;
  box-shadow:
    0 6px 0 rgba(0,0,0,.22),
    0 16px 26px rgba(0,0,0,.18) !important;
  transition: transform .08s ease, filter .10s ease, box-shadow .10s ease !important;
}}
.stButton>button:hover, .stDownloadButton>button:hover{{
  transform: translateY(-1px);
  filter: brightness(1.05);
}}
.stButton>button:active, .stDownloadButton>button:active{{
  transform: translateY(2px);
  box-shadow:
    0 3px 0 rgba(0,0,0,.22),
    0 10px 18px rgba(0,0,0,.16) !important;
}}

/* Primary CTA */
.stButton>button[kind="primary"]{{
  background: linear-gradient(180deg, rgba(88,204,2,1), rgba(58,184,0,1)) !important;
  color: #07110a !important;
  border: 2px solid rgba(255,255,255,.12) !important;
  box-shadow:
    0 6px 0 rgba(0,0,0,.28),
    0 18px 34px rgba(88,204,2,.18) !important;
}}
.stButton>button[kind="primary"]:active{{
  box-shadow:
    0 3px 0 rgba(0,0,0,.28),
    0 12px 22px rgba(88,204,2,.16) !important;
}}

/* Compact buttons (used in per-card action bars) */
.card-action-row .stButton > button{{
  padding: 0.35rem 0.70rem !important;
  font-size: 0.86rem !important;
  min-height: 38px !important;
  border-radius: 14px !important;
  box-shadow:
    0 5px 0 rgba(0,0,0,.22),
    0 12px 18px rgba(0,0,0,.16) !important;
}}


/* Tabs */
div[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: 8px;
  padding: 6px 8px;
  background: linear-gradient(180deg, var(--surface), var(--surface2));
  border: 1px solid var(--line);
  border-radius: 999px;
  box-shadow: var(--sh2);
}}
div[data-testid="stTabs"] [data-baseweb="tab"] {{
  border-radius: 999px !important;
  padding: 10px 14px !important;
  font-weight: 950 !important;
  color: var(--mut) !important;
}}
div[data-testid="stTabs"] [aria-selected="true"] {{
  background: linear-gradient(180deg, rgba(28,176,246,.20), rgba(88,204,2,.14)) !important;
  color: var(--txt) !important;
}}

/* Sticky action footer */
.sticky-bottom {{
  position: sticky;
  bottom: 0;
  z-index: 50;
  padding-top: 10px;
  padding-bottom: 10px;
  background: linear-gradient(180deg, rgba(0,0,0,0), var(--bg2) 35%);
}}

/* Desktop segmented nav (radio) */
div[data-testid="stRadio"] > div {{
  margin-left: 30px;
  margin-right: 10px;
  background: linear-gradient(180deg, var(--surface), var(--surface2));
  border: 1px solid var(--line);
  border-radius: 30px;
  padding: 8px 10px;
  box-shadow: var(--sh2);
}}

/* Remove radio circle + dot */
div[data-testid="stRadio"] input[type="radio"] {{
  position: absolute !important;
  opacity: 0 !important;
  width: 0 !important;
  height: 0 !important;
  pointer-events: none !important;
}}
div[data-testid="stRadio"] label > div:first-child {{ display: none !important; }}
div[data-testid="stRadio"] label {{
  background: transparent;
  border-radius: 999px;
  padding: 10px 14px;
  margin: 4px 6px;
  transition: transform .10s ease, background .12s ease, filter .12s ease;
  color: var(--mut);
  font-weight: 950;
}}
div[data-testid="stRadio"] label:hover {{
  transform: translateY(-1px);
  background: rgba(28,176,246,.10);
  color: var(--txt);
}}
div[data-testid="stRadio"] label:has(input:checked) {{
  background: linear-gradient(180deg, rgba(28,176,246,.20), rgba(88,204,2,.14));
  color: var(--txt);
  box-shadow: 0 10px 22px rgba(0,0,0,.10);
}}
div[data-testid="stRadio"] label * {{ color: inherit !important; }}

/* Cards page: bordered container "tiles" */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  border-radius: 16px !important;
  overflow: hidden !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  box-shadow: 0 12px 34px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.06) !important;
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease, filter 160ms ease !important;
  background: transparent !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{
  background:
    radial-gradient(520px 240px at 18% 18%, rgba(28,176,246,0.16), transparent 60%),
    radial-gradient(520px 240px at 86% 86%, rgba(88,204,2,0.12), transparent 62%),
    linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.05)) !important;
  padding: 16px 16px 14px 16px !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
  transform: translateY(-3px) !important;
  border-color: rgba(255,255,255,0.20) !important;
  box-shadow: 0 16px 44px rgba(0,0,0,0.36), 0 0 0 1px rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.07) !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:hover > div {{
  filter: brightness(1.06) !important;
}}

a {{ color: var(--brand2); }}

/* === Horizontal control rows: align mixed widgets (buttons/inputs/selects) === */
.ctl-label {{
  height: 18px;            /* reserve a consistent label slot */
  margin-bottom: 6px;
  display: flex;
  align-items: flex-end;
  font-weight: 950;
  font-size: 13px;
  color: var(--mut);
}}

/* Card action buttons: compact sizing */
.card-action-row .stButton > button {{
  padding: 0.18rem 0.55rem !important;
  font-size: 0.82rem !important;
  line-height: 1.05 !important;
  min-height: 32px !important;
  border-radius: 999px !important;
}}
.card-action-row .stButton {{margin: 0 !important; }}
.card-action-row [data-testid="column"] {{ padding-left: 0 !important; padding-right: 0 !important; }}

</style>
"""
    st.markdown(textwrap.dedent(css).lstrip(), unsafe_allow_html=True)

# =========================
# Utils
# =========================
def today_utc_date() -> date:
    return datetime.utcnow().date()

def iso_date(d: date) -> str:
    return d.isoformat()

def clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(x)))

def norm_text(s: str) -> str:
    return (s or "").strip()

def norm_word(s: str) -> str:
    return (s or "").strip().lower()


def pdf_name_to_tag(name: str) -> str:
    """Turn a PDF filename into a clean, searchable tag.

    - removes the extension
    - removes commas (tags are comma-separated)
    - collapses whitespace
    """
    base = os.path.splitext((name or "").strip())[0]
    base = re.sub(r"[\r\n\t]+", " ", base)
    base = base.replace(",", " ")
    base = re.sub(r"\s+", " ", base).strip()
    return base or "pdf"


def safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)

def toast(msg: str, icon: str = "✅") -> None:
    # st.toast exists in newer Streamlit; fallback to st.success.
    fn = getattr(st, "toast", None)
    if callable(fn):
        fn(msg, icon=icon)
    else:
        st.success(msg)

# =========================
# Gamification
# =========================
def level_from_xp(xp: int) -> Tuple[int, int, int]:
    xp = max(0, int(xp))
    level = xp // 10
    xp_in_level = xp % 10
    xp_need = 10
    return level, xp_in_level, xp_need


def copy_to_clipboard_button(text: str, label: str = "Copy text") -> None:
    """
    Renders a small button that copies `text` to clipboard (browser-side).
    """
    safe = (text or "").replace("\\", "\\\\").replace("`", "\\`")
    b64 = base64.b64encode((text or "").encode("utf-8")).decode("utf-8")
    components.html(
        f"""
<div style="display:flex; gap:10px; align-items:center; margin-top:6px;">
  <button id="copyBtn" style="
    padding:8px 12px; border-radius:12px; border:1px solid var(--line);
    background: var(--surface); color: var(--txt); cursor:pointer;">
    {label}
  </button>
  <span id="copyMsg" style="color: var(--mut); font-size: 13px;"></span>
</div>
<script>
(function() {{
  const btn = document.getElementById("copyBtn");
  const msg = document.getElementById("copyMsg");
  btn.onclick = async () => {{
    try {{
      const txt = atob("{b64}");
      await navigator.clipboard.writeText(txt);
      msg.textContent = "Copied ✓";
      setTimeout(()=>msg.textContent="", 1200);
    }} catch(e) {{
      msg.textContent = "Copy failed (browser blocked)";
      setTimeout(()=>msg.textContent="", 1800);
    }}
  }};
}})();
</script>
""",
        height=55,
    )



def carrots_and_croissants() -> Tuple[int, int, int]:
    carrots = int(st.session_state.get("xp", 0) or 0)
    carrots = max(0, carrots)
    croissants = carrots // 10
    toward = carrots % 10
    return carrots, croissants, toward

def bump_xp(amount: int) -> None:
    amount = int(amount)
    if amount <= 0:
        return

    today = iso_date(today_utc_date())
    last = st.session_state.get("last_xp_date", today)

    try:
        last_d = datetime.fromisoformat(last).date()
    except Exception:
        last_d = today_utc_date()

    if last_d == today_utc_date():
        pass
    elif last_d == today_utc_date() - timedelta(days=1):
        st.session_state.streak = int(st.session_state.get("streak", 1)) + 1
    else:
        st.session_state.streak = 1

    st.session_state.last_xp_date = today
    st.session_state.xp = int(st.session_state.get("xp", 0)) + amount

    try:
        set_user_state(
            xp=int(st.session_state.get("xp", 0) or 0),
            streak=int(st.session_state.get("streak", 1) or 1),
            last_xp_date=str(st.session_state.get("last_xp_date") or today),
        )
    except Exception:
        pass

def cigarettes_from_xp(xp: int):
    """5 croissants => 1 cigarette. (1 croissant = 10 carrots) so 1 cigarette = 50 carrots.
    Returns (cigarettes, croissants_toward_next_cigarette).
    """
    carrots = max(0, int(xp or 0))
    croissants = carrots // 10
    cigarettes = croissants // 5
    toward = croissants % 5
    return cigarettes, toward


# =========================
# DB Layer
# =========================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db() -> None:
    conn = db()
    cur = conn.cursor()

    # =========================
    # Users (multi-user auth)
    # =========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            pass_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )

    # =========================
    # Cards + Reviews
    # =========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            language TEXT NOT NULL DEFAULT 'fr',
            front TEXT NOT NULL,
            back TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            example TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            card_id INTEGER PRIMARY KEY,
            due_date TEXT NOT NULL,
            interval_days INTEGER NOT NULL DEFAULT 0,
            repetitions INTEGER NOT NULL DEFAULT 0,
            ease REAL NOT NULL DEFAULT 2.5,
            last_reviewed_at TEXT,
            last_quality INTEGER,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE
        );
        """
    )

    # Migration safety (older DB): reviews.last_quality
    try:
        cur.execute("PRAGMA table_info(reviews);")
        cols = [r[1] for r in cur.fetchall()]
        if "last_quality" not in cols:
            cur.execute("ALTER TABLE reviews ADD COLUMN last_quality INTEGER;")
    except Exception:
        pass

    # =========================
    # User state (per-user XP / streak)
    # =========================
    # Older DBs used a single-row (id=1) table. Migrate to per-user rows keyed by user_id.
    try:
        cur.execute("PRAGMA table_info(user_state);")
        cols = [r[1] for r in cur.fetchall()]
        if cols and "user_id" not in cols and "id" in cols:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_state_new (
                    user_id INTEGER PRIMARY KEY,
                    xp INTEGER NOT NULL DEFAULT 0,
                    streak INTEGER NOT NULL DEFAULT 1,
                    last_xp_date TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO user_state_new(user_id, xp, streak, last_xp_date)
                SELECT 1, xp, streak, last_xp_date FROM user_state WHERE id = 1;
                """
            )
            cur.execute("DROP TABLE user_state;")
            cur.execute("ALTER TABLE user_state_new RENAME TO user_state;")
    except Exception:
        pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_state (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER NOT NULL DEFAULT 0,
            streak INTEGER NOT NULL DEFAULT 1,
            last_xp_date TEXT NOT NULL
        );
        """
    )

    # =========================
    # Notebook PDF + Vocab
    # =========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            data BLOB NOT NULL,
            uploaded_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            book_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            meaning TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '',
            synonyms TEXT NOT NULL DEFAULT '',
            example TEXT NOT NULL DEFAULT '',
            page INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(book_id) REFERENCES pdf_books(id) ON DELETE CASCADE
        );
        """
    )

    # Migration safety (older DB) for pdf_vocab
    try:
        cur.execute("PRAGMA table_info(pdf_vocab);")
        cols = [r[1] for r in cur.fetchall()]
        if "synonyms" not in cols:
            cur.execute("ALTER TABLE pdf_vocab ADD COLUMN synonyms TEXT NOT NULL DEFAULT '';")
        if "example" not in cols:
            cur.execute("ALTER TABLE pdf_vocab ADD COLUMN example TEXT NOT NULL DEFAULT '';")
        if "user_id" not in cols:
            cur.execute("ALTER TABLE pdf_vocab ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1;")
    except Exception:
        pass

    # Best-effort: align vocab rows to their book owner (if possible)
    try:
        cur.execute(
            """
            UPDATE pdf_vocab
            SET user_id = (SELECT user_id FROM pdf_books b WHERE b.id = pdf_vocab.book_id)
            WHERE book_id IS NOT NULL;
            """
        )
    except Exception:
        pass

    # =========================
    # Grammar
    # =========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL,
            rule TEXT NOT NULL DEFAULT '',
            examples TEXT NOT NULL DEFAULT '[]',
            traps TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS grammar_mistakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            category TEXT NOT NULL DEFAULT '',
            wrong TEXT NOT NULL,
            correct TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            topic_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(topic_id) REFERENCES grammar_topics(id) ON DELETE SET NULL
        );
        """
    )

    # Best-effort: align mistakes to their topic owner (if possible)
    try:
        cur.execute(
            """
            UPDATE grammar_mistakes
            SET user_id = (SELECT user_id FROM grammar_topics t WHERE t.id = grammar_mistakes.topic_id)
            WHERE topic_id IS NOT NULL;
            """
        )
    except Exception:
        pass

    # =========================
    # App settings (global)
    # =========================
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()

# =========================
# Auth (multi-user)
# =========================
def current_user_id() -> Optional[int]:
    """Return logged-in user's id (or None)."""
    uid = st.session_state.get("auth_user_id", None)
    try:
        return int(uid) if uid is not None else None
    except Exception:
        return None

def current_username() -> str:
    return str(st.session_state.get("auth_username") or "")

def current_user_is_admin() -> bool:
    return bool(st.session_state.get("auth_is_admin") or False)

def ensure_user_state(user_id: int) -> None:
    """Ensure user_state row exists for this user."""
    uid = int(user_id)
    conn = db()
    conn.execute(
        """
        INSERT OR IGNORE INTO user_state(user_id, xp, streak, last_xp_date)
        VALUES(?, 0, 1, ?)
        """,
        (uid, iso_date(today_utc_date())),
    )
    conn.commit()
    conn.close()

def _pw_hash(password: str, salt_hex: Optional[str] = None, iterations: int = 200_000) -> str:
    """PBKDF2-SHA256 hash. Stored format: pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>"""
    pw = (password or "").encode("utf-8")
    if salt_hex is None:
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
    else:
        salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", pw, salt, int(iterations))
    return f"pbkdf2_sha256${int(iterations)}${salt_hex}${dk.hex()}"

def _pw_verify(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = (stored or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        test = _pw_hash(password, salt_hex=salt_hex, iterations=int(iters))
        return secrets.compare_digest(test, stored)
    except Exception:
        return False

def users_count() -> int:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users;")
    n = int(cur.fetchone()[0] or 0)
    conn.close()
    return n

def create_user(username: str, password: str, is_admin: bool = False) -> int:
    u = norm_word(username)
    if not u:
        raise ValueError("Username is required.")
    if len(password or "") < 4:
        raise ValueError("Password must be at least 4 characters.")
    now = datetime.utcnow().isoformat(timespec="seconds")
    ph = _pw_hash(password)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users(username, pass_hash, is_admin, created_at) VALUES(?,?,?,?);",
        (u, ph, 1 if is_admin else 0, now),
    )
    uid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    ensure_user_state(uid)
    return uid

def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    u = norm_word(username)
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, pass_hash, is_admin FROM users WHERE username=? LIMIT 1;", (u,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    uid, uname, pass_hash, is_admin = row
    if not _pw_verify(password, str(pass_hash)):
        return None
    return {"id": int(uid), "username": str(uname), "is_admin": bool(int(is_admin or 0))}

def set_logged_in(user: Dict[str, Any]) -> None:
    # Canonical auth keys
    st.session_state["auth_user_id"] = int(user["id"])
    st.session_state["auth_username"] = str(user["username"])
    st.session_state["auth_is_admin"] = bool(user.get("is_admin", False))

    # Backwards-compat aliases used throughout the original app
    st.session_state["username"] = st.session_state["auth_username"]
    st.session_state["is_admin"] = st.session_state["auth_is_admin"]

    # Pull XP/streak for this user into session
    try:
        sync_session_from_db()
    except Exception:
        pass

def logout() -> None:
    # Clear auth
    st.session_state["auth_user_id"] = None
    st.session_state["auth_username"] = None
    st.session_state["auth_is_admin"] = False
    st.session_state["auth_prev_user_id"] = None

    # Clear aliases
    st.session_state["username"] = ""
    st.session_state["is_admin"] = False


def require_login_ui() -> bool:
    """Render login / first-admin-setup UI. Returns True if logged in."""
    init_db()  # ensure tables exist
    if current_user_id() is not None:
        return True

    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown(f"## {APP_TITLE} — Login")
    # st.caption("This is a shared server. Each account has isolated data.")

    if users_count() == 0:
        st.info("First run: create the admin account.")
        with st.form("first_admin"):
            u = st.text_input("Admin username", value="admin")
            p = st.text_input("Admin password", type="password")
            p2 = st.text_input("Repeat password", type="password")
            ok = st.form_submit_button("Create admin", type="primary")
        if ok:
            if p != p2:
                st.error("Passwords do not match.")
            else:
                try:
                    create_user(u, p, is_admin=True)
                    st.success("Admin created. Please log in.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not create admin: {e}")
        st.markdown("</div>", unsafe_allow_html=True)
        return False

    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Login", type="primary")
    if ok:
        user = authenticate(u, p)
        if not user:
            st.error("Invalid username or password.")
        else:
            set_logged_in(user)
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    return False

# Compatibility wrappers (older parts of the app call these names)
def login_screen() -> None:
    # Render login UI; if user logs in it will st.rerun() inside require_login_ui()
    require_login_ui()

def logout_button(label: str = "Logout") -> None:
    if st.button(label, use_container_width=True):
        logout()
        st.rerun()

# =========================
# Password management
# =========================
def _get_user_pass_hash(user_id: int) -> Optional[str]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT pass_hash FROM users WHERE id=? LIMIT 1;", (int(user_id),))
    row = cur.fetchone()
    conn.close()
    return (str(row[0]) if row and row[0] is not None else None)

def set_user_password(user_id: int, new_password: str) -> None:
    if len(new_password or "") < 4:
        raise ValueError("Password must be at least 4 characters.")
    ph = _pw_hash(new_password)
    conn = db()
    conn.execute("UPDATE users SET pass_hash=? WHERE id=?;", (ph, int(user_id)))
    conn.commit()
    conn.close()

def change_password(user_id: int, current_password: str, new_password: str) -> None:
    stored = _get_user_pass_hash(int(user_id))
    if not stored:
        raise ValueError("User not found.")
    if not _pw_verify(current_password or "", stored):
        raise ValueError("Current password is incorrect.")
    set_user_password(int(user_id), new_password)

def list_users_basic() -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY LOWER(username) ASC;")
    rows = [
        {"id": int(r[0]), "username": str(r[1]), "is_admin": bool(int(r[2] or 0)), "created_at": str(r[3])}
        for r in cur.fetchall()
    ]
    conn.close()
    return rows

def change_password_section_ui() -> None:
    """Self-service password change, plus admin reset."""
    uid = int(current_user_id() or 0)
    if uid <= 0:
        st.info("You must be logged in to change password.")
        return

    st.markdown("#### Change password")
    with st.form("change_password_form"):
        cur_pw = st.text_input("Current password", type="password")
        new_pw = st.text_input("New password", type="password")
        new_pw2 = st.text_input("Repeat new password", type="password")
        ok = st.form_submit_button("Update password", type="primary")
    if ok:
        try:
            if new_pw != new_pw2:
                raise ValueError("New passwords do not match.")
            change_password(uid, cur_pw, new_pw)
            toast("Password updated.", icon="🔐")
            st.success("Password updated.")
        except Exception as e:
            st.error(str(e))

    # Admin-only: reset any user's password
    if bool(st.session_state.get("is_admin")):
        with st.expander("Admin: reset a user's password"):
            users = list_users_basic()
            if not users:
                st.info("No users found.")
            else:
                labels = [
                    f"{u['username']}" + (" (admin)" if u.get("is_admin") else "")
                    for u in users
                ]
                pick = st.selectbox("User", options=list(range(len(users))), format_func=lambda i: labels[i])
                target = users[int(pick)]
                with st.form("admin_reset_pw"):
                    npw = st.text_input("New password for selected user", type="password")
                    npw2 = st.text_input("Repeat new password", type="password")
                    ok2 = st.form_submit_button("Reset password", type="primary")
                if ok2:
                    try:
                        if npw != npw2:
                            raise ValueError("Passwords do not match.")
                        set_user_password(int(target["id"]), npw)
                        toast("Password reset.", icon="🛡️")
                        st.success(f"Password reset for {target['username']}.")
                    except Exception as e:
                        st.error(str(e))






def activity_dates_between(start: date, days: int) -> set:
    """
    Return a set of ISO dates (YYYY-MM-DD) where the user did *anything*:
      - created a card
      - reviewed a card (reviews.last_reviewed_at)
      - added a PDF vocab entry
      - created grammar topic
      - created grammar mistake

    You can expand this list later if you add more "activity" tables.
    """
    start_d = start
    end_d = start + timedelta(days=max(0, int(days) - 1))

    conn = db()
    cur = conn.cursor()

    # We union all activity sources, normalize to YYYY-MM-DD, then distinct.
    cur.execute(
        """
        SELECT DISTINCT day FROM (
            SELECT substr(created_at, 1, 10) AS day
            FROM cards
            WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
              AND user_id = ?

            UNION ALL

            SELECT substr(COALESCE(r.last_reviewed_at, ''), 1, 10) AS day
            FROM reviews r
            JOIN cards c ON c.id = r.card_id
            WHERE r.last_reviewed_at IS NOT NULL
              AND substr(r.last_reviewed_at, 1, 10) BETWEEN ? AND ?
              AND c.user_id = ?

            UNION ALL

            SELECT substr(created_at, 1, 10) AS day
            FROM pdf_vocab
            WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
              AND user_id = ?

            UNION ALL

            SELECT substr(created_at, 1, 10) AS day
            FROM grammar_topics
            WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
              AND user_id = ?

            UNION ALL

            SELECT substr(created_at, 1, 10) AS day
            FROM grammar_mistakes
            WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
              AND user_id = ?
        )
        """,
        (
            start_d.isoformat(), end_d.isoformat(), int(current_user_id() or 1),
            start_d.isoformat(), end_d.isoformat(), int(current_user_id() or 1),
            start_d.isoformat(), end_d.isoformat(), int(current_user_id() or 1),
            start_d.isoformat(), end_d.isoformat(), int(current_user_id() or 1),
            start_d.isoformat(), end_d.isoformat(), int(current_user_id() or 1),
        ),
    )

    out = {str(r[0]) for r in cur.fetchall() if r and r[0]}
    conn.close()
    return out


def get_setting(key: str, default: str = "") -> str:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key=?;", (key,))
    row = cur.fetchone()
    conn.close()
    if not row or row[0] is None:
        return default
    return str(row[0])

def set_setting(key: str, value: str) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO app_settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
        (key, str(value)),
    )
    conn.commit()
    conn.close()

def get_user_state() -> Dict[str, Any]:
    uid = current_user_id() or 1
    ensure_user_state(uid)
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT xp, streak, last_xp_date FROM user_state WHERE user_id=?;", (int(uid),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"xp": 0, "streak": 1, "last_xp_date": iso_date(today_utc_date())}
    xp, streak, last_xp_date = row
    return {
        "xp": int(xp or 0),
        "streak": int(streak or 1),
        "last_xp_date": str(last_xp_date or iso_date(today_utc_date())),
    }


def set_user_state(xp: int, streak: int, last_xp_date: str) -> None:
    xp_i = int(xp)
    streak_i = int(streak)
    last_s = str(last_xp_date)

    last_err: Optional[Exception] = None
    for _ in range(3):
        try:
            conn = db()
            conn.execute(
                """
                INSERT INTO user_state(user_id, xp, streak, last_xp_date)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    xp=excluded.xp,
                    streak=excluded.streak,
                    last_xp_date=excluded.last_xp_date;
                """,
                (int(current_user_id() or 1), xp_i, streak_i, last_s),
            )
            conn.commit()
            conn.close()
            return
        except Exception as e:
            last_err = e
            try:
                conn.close()
            except Exception:
                pass
            import time as _time
            _time.sleep(0.05)
    if last_err:
        raise last_err

def sync_session_from_db() -> None:
    """Sync xp/streak/last_xp_date from DB into session.

    IMPORTANT: When multiple users can log in from the same browser session (logout/login),
    we must *overwrite* session values when the logged-in user changes. Otherwise the UI can
    show the previous user's XP/Level/Cigarettes.
    """
    uid = current_user_id() or 1

    # Detect user switch inside the same Streamlit session.
    prev_uid = st.session_state.get("auth_prev_user_id", None)
    user_switched = (prev_uid is None and uid is not None) or (prev_uid is not None and int(prev_uid) != int(uid))
    st.session_state["auth_prev_user_id"] = int(uid)

    s = get_user_state()
    db_xp = int(s.get("xp", 0) or 0)
    db_streak = int(s.get("streak", 1) or 1)
    db_last = str(s.get("last_xp_date") or iso_date(today_utc_date()))

    if user_switched:
        # On user switch: hard overwrite.
        st.session_state.xp = db_xp
        st.session_state.streak = db_streak
        st.session_state.last_xp_date = db_last
        return

    # Normal refresh (same user): keep session consistent with DB.
    st.session_state.xp = db_xp
    st.session_state.streak = db_streak
    st.session_state.last_xp_date = db_last


def count_cards_db() -> int:
    try:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cards WHERE user_id=?;", (int(current_user_id() or 1),))
        n = cur.fetchone()[0]
        conn.close()
        return int(n or 0)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return 0

def reconcile_carrots_with_cards() -> None:
    """Ensure carrots (XP) is at least the number of cards ever created."""
    try:
        total_cards = count_cards_db()
        cur_xp = int(st.session_state.get("xp", 0) or 0)
        if total_cards > cur_xp:
            st.session_state.xp = total_cards
            today = iso_date(today_utc_date())
            st.session_state.setdefault("streak", 1)
            st.session_state.setdefault("last_xp_date", today)
            set_user_state(
                xp=int(st.session_state.get("xp", 0) or 0),
                streak=int(st.session_state.get("streak", 1) or 1),
                last_xp_date=str(st.session_state.get("last_xp_date") or today),
            )
    except Exception:
        pass

def upsert_review_defaults(card_id: int) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT card_id FROM reviews WHERE card_id=?", (card_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            """
            INSERT INTO reviews(card_id, due_date, interval_days, repetitions, ease, last_reviewed_at)
            VALUES(?, ?, 0, 0, 2.5, NULL)
            """,
            (card_id, iso_date(today_utc_date())),
        )
    
    conn.commit()
    conn.close()

def create_card(language: str, front: str, back: str, tags: str, example: str, notes: str) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cards(user_id, language, front, back, tags, example, notes, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(current_user_id() or 1), norm_text(language), norm_text(front), norm_text(back), norm_text(tags),
         norm_text(example), norm_text(notes), now, now),
    )
    card_id = int(cur.lastrowid)
    
    conn.commit()
    conn.close()
    upsert_review_defaults(card_id)
    return card_id

def update_card(card_id: int, language: str, front: str, back: str, tags: str, example: str, notes: str) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = db()
    conn.execute(
        """
        UPDATE cards
        SET language=?, front=?, back=?, tags=?, example=?, notes=?, updated_at=?
        WHERE id=? AND user_id=?
        """,
        (norm_text(language), norm_text(front), norm_text(back), norm_text(tags),
         norm_text(example), norm_text(notes), now, card_id, int(current_user_id() or 1)),
    )
    
    conn.commit()
    conn.close()
    upsert_review_defaults(card_id)

def delete_card(card_id: int) -> None:
    conn = db()
    conn.execute("DELETE FROM cards WHERE id=? AND user_id=?", (card_id, int(current_user_id() or 1)))
    
    conn.commit()
    conn.close()

def fetch_cards(filter_text: str = "", tag: str = "", order_by: str = "updated_desc") -> List[Dict[str, Any]]:
    """Fetch cards with optional free-text filter, tag filter, and stable ordering.

    order_by:
      - updated_desc (default)
      - due_asc
      - created_desc
      - front_asc
    """
    conn = db()
    cur = conn.cursor()
    q = """
    SELECT c.id, c.language, c.front, c.back, c.tags, c.example, c.notes, c.created_at, c.updated_at,
           r.due_date, r.interval_days, r.repetitions, r.ease, r.last_quality, r.last_reviewed_at
    FROM cards c
    LEFT JOIN reviews r ON r.card_id = c.id
    WHERE 1=1
    """
    params: List[Any] = []
    q += " AND c.user_id = ?"
    params.append(int(current_user_id() or 1))
    if norm_text(filter_text):
        q += " AND (c.front LIKE ? OR c.back LIKE ? OR c.example LIKE ? OR c.notes LIKE ?)"
        like = f"%{norm_text(filter_text)}%"
        params.extend([like, like, like, like])
    if norm_text(tag):
        q += " AND (',' || REPLACE(c.tags,' ', '') || ',') LIKE ?"
        params.append(f"%,{norm_text(tag).replace(' ', '')},%")

    order_sql = {
        "updated_desc": "c.updated_at DESC, c.id DESC",
        "created_desc": "c.created_at DESC, c.id DESC",
        "due_asc": "date(COALESCE(r.due_date, c.created_at)) ASC, c.id ASC",
        "front_asc": "LOWER(c.front) ASC, c.id ASC",
    }.get(norm_word(order_by), "c.updated_at DESC, c.id DESC")

    q += f" ORDER BY {order_sql}"
    cur.execute(q, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_card_by_id(card_id: int) -> Optional[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.language, c.front, c.back, c.tags, c.example, c.notes, c.created_at, c.updated_at,
               r.due_date, r.interval_days, r.repetitions, r.ease, r.last_quality, r.last_reviewed_at
        FROM cards c
        LEFT JOIN reviews r ON r.card_id = c.id
        WHERE c.id = ? AND c.user_id = ?
        LIMIT 1
        """,
        (card_id, int(current_user_id() or 1)),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    cols = [d[0] for d in cur.description]
    conn.close()
    return dict(zip(cols, row))

def fetch_cards_created_on(d: date) -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.language, c.front, c.back, c.tags, c.example, c.notes, c.created_at, c.updated_at,
               r.due_date, r.interval_days, r.repetitions, r.ease, r.last_quality, r.last_reviewed_at
        FROM cards c
        LEFT JOIN reviews r ON r.card_id = c.id
        WHERE substr(c.created_at, 1, 10) = ? AND c.user_id = ?
        ORDER BY c.created_at DESC
        """,
        (d.isoformat(), int(current_user_id() or 1)),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows

def fetch_due_cards(on_date: date) -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.language, c.front, c.back, c.tags, c.example, c.notes,
               r.due_date, r.interval_days, r.repetitions, r.ease, r.last_quality, r.last_reviewed_at
        FROM cards c
        JOIN reviews r ON r.card_id = c.id
        WHERE date(r.due_date) <= date(?) AND c.user_id = ?
        ORDER BY date(r.due_date) ASC, c.id ASC
        """,
        (iso_date(on_date), int(current_user_id() or 1)),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows

def update_review_state(card_id: int, due_date: date, interval_days: int, repetitions: int, ease: float, last_quality: Optional[int] = None) -> None:
    conn = db()
    conn.execute(
        """
        UPDATE reviews
        SET due_date=?, interval_days=?, repetitions=?, ease=?, last_quality=?, last_reviewed_at=?
        WHERE card_id=?
        """,
        (iso_date(due_date), int(interval_days), int(repetitions), float(ease),
         (None if last_quality is None else int(last_quality)),
         datetime.utcnow().isoformat(timespec="seconds"), card_id),
    )
    
    conn.commit()
    conn.close()

def all_tags() -> List[str]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT tags FROM cards WHERE user_id = ?", (int(current_user_id() or 1),))
    raw = [r[0] for r in cur.fetchall()]
    conn.close()
    tags = set()
    for t in raw:
        for part in (t or "").split(","):
            part = part.strip()
            if part:
                tags.add(part)
    return sorted(tags)
# =========================
# Notebook PDF helpers
# =========================
def pdf_book_upsert(name: str, data: bytes) -> int:
    """Insert a PDF book. If same name exists, replace its data."""
    name = norm_text(name) or "book.pdf"
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM pdf_books WHERE name=? AND user_id=? LIMIT 1;", (name, int(current_user_id() or 1)))
    row = cur.fetchone()
    if row:
        book_id = int(row[0])
        cur.execute("UPDATE pdf_books SET data=?, uploaded_at=? WHERE id=?;", (sqlite3.Binary(data), now, book_id))
    else:
        cur.execute("INSERT INTO pdf_books(user_id, name, data, uploaded_at) VALUES(?,?,?,?);", (int(current_user_id() or 1), name, sqlite3.Binary(data), now))
        book_id = int(cur.lastrowid)
    
    conn.commit()
    conn.close()
    return book_id

def pdf_books_list() -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, uploaded_at FROM pdf_books WHERE user_id=? ORDER BY uploaded_at DESC, id DESC;", (int(current_user_id() or 1),))
    rows = [{"id": int(r[0]), "name": str(r[1]), "uploaded_at": str(r[2])} for r in cur.fetchall()]
    conn.close()
    return rows

def pdf_book_get(book_id: int) -> Optional[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, data, uploaded_at FROM pdf_books WHERE id=? AND user_id=? LIMIT 1;", (int(book_id), int(current_user_id() or 1)))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return {"id": int(r[0]), "name": str(r[1]), "data": bytes(r[2]), "uploaded_at": str(r[3])}

def pdf_book_delete(book_id: int) -> None:
    conn = db()
    conn.execute("DELETE FROM pdf_books WHERE id=? AND user_id=?;", (int(book_id), int(current_user_id() or 1)))
    
    conn.commit()
    conn.close()

def pdf_vocab_add(book_id: int, word: str, meaning: str, context: str, synonyms: str, example: str, page: Optional[int]) -> int:
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pdf_vocab(user_id, book_id, word, meaning, context, synonyms, example, page, created_at) VALUES(?,?,?,?,?,?,?,?,?);",
        (int(current_user_id() or 1), int(book_id), norm_text(word), norm_text(meaning), norm_text(context), norm_text(synonyms), norm_text(example), (None if page is None else int(page)), now),
    )
    vid = int(cur.lastrowid)
    
    conn.commit()
    conn.close()
    return vid

def pdf_vocab_list(book_id: int, q: str = "") -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    qn = norm_text(q)
    sql = "SELECT id, book_id, word, meaning, context, synonyms, example, page, created_at FROM pdf_vocab WHERE book_id=? AND user_id=?"
    params: List[Any] = [int(book_id), int(current_user_id() or 1)]
    if qn:
        sql += " AND (word LIKE ? OR meaning LIKE ? OR context LIKE ? OR synonyms LIKE ? OR example LIKE ?)"
        like = f"%{qn}%"
        params.extend([like, like, like, like, like])
    sql += " ORDER BY created_at DESC, id DESC"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows

def pdf_vocab_delete(vocab_id: int) -> None:
    conn = db()
    conn.execute("DELETE FROM pdf_vocab WHERE id=? AND user_id=?;", (int(vocab_id), int(current_user_id() or 1)))
    
    conn.commit()
    conn.close()

@st.cache_data(show_spinner=False)
def render_pdf_page_png(pdf_bytes: bytes, page: int, zoom: int) -> bytes:
    """Render a PDF page to PNG bytes (server-side) using PyMuPDF."""
    if fitz is None:
        return b""
    p = max(1, int(page)) - 1
    z = max(50, min(300, int(zoom))) / 100.0
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        p = min(p, max(0, doc.page_count - 1))
        pg = doc.load_page(p)
        pix = pg.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()

@st.cache_data(show_spinner=False)
def extract_pdf_page_text(pdf_bytes: bytes, page: int) -> str:
    """Extract selectable text from one PDF page using PyMuPDF."""
    if fitz is None:
        return ""
    p = max(1, int(page)) - 1
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        p = min(p, max(0, doc.page_count - 1))
        pg = doc.load_page(p)
        txt = pg.get_text("text") or ""
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        return txt
    finally:
        doc.close()


@st.cache_data(show_spinner=False)
def google_translate(text: str, source_lang: str = "fr", target_lang: str = "en") -> str:
    """Translate text using a lightweight Google Translate endpoint.

    This uses the public "translate_a/single" endpoint (no API key). It may break
    if Google changes it; the UI also provides a direct link to translate.google.com.
    """
    text = (text or "").strip()
    if not text:
        return ""
    sl = norm_word(source_lang) or "auto"
    tl = norm_word(target_lang) or "en"
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": sl,
                "tl": tl,
                "dt": "t",
                "q": text,
            },
            headers=HTTP_HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return ""
        data = r.json()
        # data[0] is a list of translated segments: [["translated","original",...], ...]
        if not isinstance(data, list) or not data:
            return ""
        segs = data[0]
        if not isinstance(segs, list):
            return ""
        out = "".join([(s[0] if isinstance(s, list) and s else "") for s in segs])
        return (out or "").strip()
    except Exception:
        return ""

def _extract_first_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON extraction from a model reply."""
    if not text:
        return {}
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}



def _wiktionary_fetch_page_wikitext(title: str) -> str:
    """Fetch raw wikitext for a French Wiktionary page (no key)."""
    title = (title or "").strip()
    if not title:
        return ""
    try:
        r = requests.get(
            "https://fr.wiktionary.org/w/api.php",
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
                "formatversion": "2",
            },
            headers={"User-Agent": "CharlotGrammer/1.0"},
            timeout=15,
        )
        if r.status_code >= 400:
            return ""
        data = r.json() or {}
        return ((data.get("parse") or {}).get("wikitext") or "")
    except Exception:
        return ""


def _wiktionary_extract_section(wikitext: str, section_names: List[str]) -> str:
    """
    Extract a section body by heading name from Wiktionary wikitext.
    We look for headings like === Synonymes === or ==== Exemples ====.
    """
    if not wikitext:
        return ""
    # Normalize headings: headings are like === Title ===
    for name in section_names:
        # match === name === or ==== name ====
        m = re.search(r"(?m)^={2,5}\s*%s\s*={2,5}\s*$" % re.escape(name), wikitext)
        if not m:
            continue
        start = m.end()
        # next heading at same or higher level
        n = re.search(r"(?m)^={2,5}[^=].*?={2,5}\s*$", wikitext[start:])
        end = start + (n.start() if n else len(wikitext[start:]))
        return wikitext[start:end].strip()
    return ""


def _wiktionary_parse_bullets(block: str, max_items: int = 6) -> List[str]:
    """Parse Wiktionary bullet lists into clean strings.

    Handles common Wiktionary templates like {{l|fr|...}}, {{m|fr|...}}, {{lien|fr|...}}
    and synonym templates like {{syn|fr|a|b|c}}.
    """
    if not block:
        return []
    out: List[str] = []

    def _push(item: str) -> None:
        item = (item or "").strip()
        if not item:
            return
        if item not in out:
            out.append(item)

    for raw in block.splitlines():
        line = (raw or "").strip()
        if not line:
            continue

        # Keep bullet-ish lines only.
        if not (line.startswith("*") or line.startswith("#") or line.startswith(":*") or line.startswith("#*")):
            continue

        # Remove leading bullet markers.
        line = re.sub(r"^[:#\*]+\s*", "", line).strip()
        if not line:
            continue

        # If this is a {{syn|fr|...}} template line, extract params directly.
        if "{{syn" in line:
            m = re.search(r"\{\{syn\|fr\|([^}]+)\}\}", line)
            if m:
                parts = [p.strip() for p in m.group(1).split("|") if p.strip()]
                for p in parts:
                    # syn template params may contain wiki links.
                    p = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", p)
                    p = re.sub(r"\[\[([^\]]+)\]\]", r"\1", p)
                    p = re.sub(r"\s+", " ", p).strip(" -;:,.•")
                    _push(p)
                if len(out) >= max_items:
                    return out
                continue

        # Replace wiki links [[...|...]] / [[...]]
        line = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", line)
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)

        # Preserve common link templates: {{l|fr|mot}}, {{m|fr|mot}}, {{lien|fr|mot}}
        line = re.sub(r"\{\{(?:l|m|lien)\|fr\|([^|}]+)(?:\|[^}]*)?\}\}", r"\1", line)

        # Remove remaining templates {{...}} (best-effort)
        line = re.sub(r"\{\{[^}]+\}\}", "", line)

        # Strip HTML tags
        line = re.sub(r"<[^>]+>", "", line)

        # Collapse whitespace
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue

        # Split by separators; Wiktionary sometimes packs multiple items per line.
        parts = [p.strip() for p in re.split(r"[,;/•]",
                                            line) if p.strip()]
        for p in parts:
            p = re.sub(r"\s+", " ", p).strip(" -;:,.•")
            _push(p)
            if len(out) >= max_items:
                return out

    return out



def _tatoeba_example_fr(query: str) -> str:
    """Fetch one French example sentence from Tatoeba (no key)."""
    q = (query or "").strip()
    if not q:
        return ""
    try:
        r = requests.get(
            "https://tatoeba.org/en/api_v0/search",
            params={"from": "fra", "query": q},
            headers={"User-Agent": "CharlotGrammer/1.0"},
            timeout=15,
        )
        if r.status_code >= 400:
            return ""
        data = r.json() or {}
        results = data.get("results") or []
        for item in results:
            text_fr = (item.get("text") or "").strip()
            if text_fr:
                return text_fr
        return ""
    except Exception:
        return ""


def ai_vocab_helper(word: str) -> Tuple[str, List[str], str]:
    """
    FREE helper for Notes (no API key, no paid credits):
      - English translation via google_translate()
      - French synonyms via fr.wiktionary.org (best-effort)
      - French example via Wiktionary or Tatoeba (fallback)

    Returns: (translation_en, synonyms_fr_list, example_fr)

    On failure, returns partial results if possible and writes a message to:
      st.session_state["ai_last_error"]
    """
    st.session_state["ai_last_error"] = ""
    w = (word or "").strip()
    if not w:
        st.session_state["ai_last_error"] = "Empty input."
        return "", [], ""

    # 1) Translation (EN) — already used elsewhere in your app
    tr_en = ""
    try:
        tr_en = google_translate(w, "fr", "en") or ""
    except Exception:
        tr_en = ""

    # 2) Wiktionary for synonyms/examples
    wikitext = _wiktionary_fetch_page_wikitext(w)
    syns: List[str] = []
    ex_fr = ""

    if wikitext:
        syn_block = _wiktionary_extract_section(wikitext, ["Synonymes", "Synonymes et antonymes", "Synonymie"])
        syns = _wiktionary_parse_bullets(syn_block, max_items=6)

        ex_block = _wiktionary_extract_section(wikitext, ["Exemples", "Exemple", "Citations"])
        exs = _wiktionary_parse_bullets(ex_block, max_items=2)
        # pick the first sentence-like example
        for ex in exs:
            if len(ex) >= 8:
                ex_fr = ex
                break

    # 3) Fallback example from Tatoeba if Wiktionary had none
    if not ex_fr:
        ex_fr = _tatoeba_example_fr(w)

    if not (tr_en or syns or ex_fr):
        st.session_state["ai_last_error"] = (
            "No result from free sources (Wiktionary/Tatoeba). "
            "Try a single base form (e.g., infinitive / singular), or use Google Translate."
        )

    return tr_en, syns, ex_fr

def sm2_next(review: Dict[str, Any], quality: int) -> Tuple[int, int, float]:
    q = clamp_int(quality, 0, 5)
    reps = int(review.get("repetitions", 0) or 0)
    interval = int(review.get("interval_days", 0) or 0)
    ease = float(review.get("ease", 2.5) or 2.5)
    if q < 3:
        reps = 0
        interval = 1
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = int(round(interval * ease)) if interval > 0 else int(round(6 * ease))



    ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    ease = max(1.3, ease)
    return interval, reps, ease


def pdf_selectable_viewer(pdf_bytes: bytes, page: int = 1, zoom: int = 100, height: int = 820) -> None:
    """
    Render a selectable PDF page inside Streamlit using PDF.js (text layer enabled),
    so the user can highlight/copy text directly from the PDF view.

    Notes:
    - Works when the PDF actually contains text (not only scanned images).
    - Uses a JS renderer to avoid Chrome blocking data: PDFs in iframes.
    """
    try:
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    except Exception:
        st.error("Could not load PDF bytes for preview.")
        return

    pg = max(1, int(page))
    zm = max(50, min(300, int(zoom)))
    h = int(height)

    # PDF.js viewer (single-page) with selectable text layer
    components.html(
        f"""
<div id="pdfjs-root" style="width:100%; height:{h}px; position:relative; border-radius:16px; overflow:hidden; border:1px solid rgba(255,255,255,.10);">
  <div id="pdfjs-scroll" style="width:100%; height:100%; overflow:auto; background: rgba(0,0,0,.02);">
    <div id="pdfjs-pagewrap" style="position:relative; margin:16px auto; width:fit-content;">
      <canvas id="pdfjs-canvas" style="display:block;"></canvas>
      <div id="pdfjs-textLayer" class="textLayer" style="position:absolute; inset:0;"></div>
    </div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script>
(async () => {{
  const b64 = "{b64}";
  const pageNum = {pg};
  const scale = {zm} / 100.0;

  // Configure worker
  if (window['pdfjsLib']) {{
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  }} else {{
    const root = document.getElementById("pdfjs-root");
    root.innerHTML = "<div style='padding:16px; font-family:system-ui;'>PDF.js failed to load.</div>";
    return;
  }}

  // Decode base64 → Uint8Array
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

  const loadingTask = pdfjsLib.getDocument({{ data: bytes }});
  const pdf = await loadingTask.promise;
  const page = await pdf.getPage(pageNum);

  const viewport = page.getViewport({{ scale }});
  const canvas = document.getElementById("pdfjs-canvas");
  const ctx = canvas.getContext("2d", {{ alpha: false }});

  // HiDPI / devicePixelRatio handling for crisp rendering AND correct text-layer alignment.
  const outputScale = window.devicePixelRatio || 1;

  // Set actual pixel buffer size
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);

  // Set CSS size (layout size in CSS pixels)
  canvas.style.width = Math.floor(viewport.width) + "px";
  canvas.style.height = Math.floor(viewport.height) + "px";

  // Scale drawing operations to match CSS pixels
  ctx.setTransform(outputScale, 0, 0, outputScale, 0, 0);

  // Render page to canvas
  await page.render({{ canvasContext: ctx, viewport }}).promise;

  // Render selectable text layer
  const textLayer = document.getElementById("pdfjs-textLayer");
  textLayer.innerHTML = "";
  textLayer.style.width = Math.floor(viewport.width) + \"px\";
  textLayer.style.height = Math.floor(viewport.height) + \"px\";

  const textContent = await page.getTextContent();
  await pdfjsLib.renderTextLayer({{
    textContent,
    container: textLayer,
    viewport,
    textDivs: []
  }}).promise;

}})().catch((err) => {{
  const root = document.getElementById("pdfjs-root");
  root.innerHTML = "<div style='padding:16px; font-family:system-ui;'>Could not render PDF page: " + String(err) + "</div>";
}});
</script>

<style>
/* IMPORTANT:
   - Canvas is the readable page.
   - TextLayer sits on top for selection/copy.
   - We hide glyph paint (transparent text), but keep the layer interactive. */
#pdfjs-canvas {{ pointer-events: none; }}

.textLayer {{
  opacity: 1;                 /* must be visible for selection in some browsers */
  line-height: 1.0;
  transform-origin: 0 0;
  pointer-events: auto;       /* allow click/drag selection */
  user-select: text;
}}

.textLayer span {{
  position: absolute;
  white-space: pre;
  transform-origin: 0% 0%;
  color: transparent !important;                 /* hide text paint */
  -webkit-text-fill-color: transparent !important;
}}

.textLayer ::selection {{
  background: rgba(88, 204, 2, 0.28);
}}
</style>
        """,
        height=h,
    )

def difficulty_bucket(card_row: Dict[str, Any]) -> str:
    q = card_row.get("last_quality", None)
    if q is None:
        return "new"
    try:
        q = int(q)
    except Exception:
        return "new"
    if q <= 0:
        return "difficult"
    if q >= 4:
        return "difficult"
    if q == 3:
        return "meh"
    return "easy"

# =========================
# Dictionary backends
# =========================
@st.cache_data(show_spinner=False)
def dictapi_lookup(lang: str, word: str) -> Tuple[bool, Any, int]:
    lang = norm_word(lang)
    word = norm_text(word)
    if not lang or not word:
        return False, {"error": "Missing lang or word"}, 0
    url = f"{DICTAPI_BASE}/{lang}/{word}"
    try:
        r = requests.get(url, timeout=10)
        status = r.status_code
        try:
            payload = r.json()
        except Exception:
            payload = {"raw_text": r.text}
        return (status == 200), payload, status
    except Exception as e:
        return False, {"error": str(e)}, 0

def parse_dictapi_payload(payload: Any) -> Dict[str, Any]:
    out = {"phonetics": [], "meanings": []}
    if not isinstance(payload, list) or not payload:
        return out
    entry = payload[0]
    if not isinstance(entry, dict):
        return out
    for p in (entry.get("phonetics", []) or []):
        if isinstance(p, dict):
            out["phonetics"].append({"text": p.get("text") or "", "audio": p.get("audio") or ""})
    for m in (entry.get("meanings", []) or []):
        if not isinstance(m, dict):
            continue
        defs: List[Dict[str, Any]] = []
        for d in (m.get("definitions", []) or []):
            if not isinstance(d, dict):
                continue
            defs.append(
                {"definition": d.get("definition") or "", "example": d.get("example") or "", "synonyms": d.get("synonyms") or []}
            )
        out["meanings"].append({"partOfSpeech": m.get("partOfSpeech") or "", "definitions": defs})
    return out

@st.cache_data(show_spinner=False)
def wiktionary_summary(lang: str, word: str) -> Tuple[bool, Dict[str, Any]]:
    lang = norm_word(lang)
    word = norm_text(word)
    if not lang or not word:
        return False, {"error": "Missing lang or word"}
    base = WIKTIONARY_BASE.get(lang, WIKTIONARY_BASE["fr"])
    title_enc = requests.utils.quote(word, safe="")
    url = f"{base}/api/rest_v1/page/summary/{title_enc}"
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=12)
        status = r.status_code
        try:
            j = r.json()
        except Exception:
            return False, {"error": f"Non-JSON response (status={status})", "raw_text": r.text[:2000], "source": url}
        if status != 200:
            return False, {"error": f"HTTP {status}", "raw": j, "source": url}
        title = j.get("title") or word
        extract = (j.get("extract") or "").strip()
        if not extract:
            return False, {"error": "Empty extract", "raw": j, "source": url}
        return True, {"title": title, "extract": extract, "source": url}
    except Exception as e:
        return False, {"error": str(e), "source": url}

@st.cache_data(show_spinner=False)
def wiktionary_extract(lang: str, word: str) -> Tuple[bool, Dict[str, Any]]:
    lang = norm_word(lang)
    word = norm_text(word)
    if not lang or not word:
        return False, {"error": "Missing lang or word"}
    base = WIKTIONARY_BASE.get(lang, WIKTIONARY_BASE["fr"])
    api = f"{base}/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts",
        "explaintext": 1,
        "exsectionformat": "plain",
        "redirects": 1,
        "titles": word,
    }
    try:
        r = requests.get(api, params=params, headers=HTTP_HEADERS, timeout=12)
        status = r.status_code
        try:
            j = r.json()
        except Exception:
            return False, {"error": f"Non-JSON response (status={status})", "raw_text": r.text[:2000], "source": api}
        if status != 200:
            return False, {"error": f"HTTP {status}", "raw": j, "source": api}
        pages = (j.get("query", {}) or {}).get("pages", {}) or {}
        if not pages:
            return False, {"error": "No pages in response", "raw": j, "source": api}
        page = next(iter(pages.values()))
        if not isinstance(page, dict):
            return False, {"error": "Bad page format", "raw": j, "source": api}
        if "missing" in page:
            return False, {"error": "Not found", "raw": page, "source": api}
        title = page.get("title") or word
        extract = (page.get("extract") or "").strip()
        if not extract:
            return False, {"error": "Empty extract", "raw": page, "source": api}
        return True, {"title": title, "extract": extract, "source": api}
    except Exception as e:
        return False, {"error": str(e), "source": api}

def summarize_extract(extract: str, max_lines: int = 18, max_chars: int = 1400) -> str:
    text = (extract or "").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    snippet = "\n".join(lines[:max_lines]).strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip() + "…"
    return snippet

def best_dictionary_result(lang: str, word: str) -> Tuple[str, Dict[str, Any]]:
    lang = norm_word(lang)
    word = norm_text(word)

    if lang == "en":
        ok, payload, status = dictapi_lookup(lang, word)
        parsed = parse_dictapi_payload(payload) if ok else {"phonetics": [], "meanings": []}
        if ok and parsed["meanings"]:
            return "dictapi", {"status": status, "raw": payload, "parsed": parsed}

    ok, data = wiktionary_summary(lang, word)
    if ok:
        return "wiktionary_summary", data

    ok2, data2 = wiktionary_extract(lang, word)
    if ok2:
        return "wiktionary_extract", data2

    ok3, payload3, status3 = dictapi_lookup(lang, word)
    parsed3 = parse_dictapi_payload(payload3) if ok3 else {"phonetics": [], "meanings": []}
    if ok3 and parsed3["meanings"]:
        return "dictapi", {"status": status3, "raw": payload3, "parsed": parsed3}

    return "none", {"errors": {"wiktionary_summary": data, "wiktionary_extract": data2, "dictapi": {"status": status3, "raw": payload3}}}

# =========================
# UI helpers
# =========================
def chip(icon: str, label: str, value: str) -> str:
    return f"<span class='chip'>{icon} <b>{label}</b> {value}</span>"

def badge_row(items: List[Tuple[str, str]]) -> None:
    html = " ".join([f"<span class='chip'>{ic} <b>{txt}</b></span>" for ic, txt in items])
    st.markdown(html, unsafe_allow_html=True)


def app_header(bp: str) -> None:
    carrots, croissants, toward = carrots_and_croissants()
    streak = int(st.session_state.get("streak", 1))
    level, xp_in, xp_need = level_from_xp(carrots)
    total_cards = count_cards_db()
    due_today = len(fetch_due_cards(today_utc_date()))
    cigarettes, cig_toward = cigarettes_from_xp(carrots)

    # Header
    with st.container():
        st.markdown(
            f"""
<div class="card" style="padding:14px 14px; margin-bottom:8px;">
  <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
    <div>
      <div style="display:flex; align-items:center; gap:10px;">
  <div style="
    width:40px; height:40px; border-radius:14px;
    display:flex; align-items:center; justify-content:center;
    background: linear-gradient(180deg, rgba(0,0,100,.1), rgba(0,0,10,.5));
    border: 1px solid var(--line);
    box-shadow: var(--sh2);
    font-size:22px;
  ">💁‍♀️</div>
  <div style="font-weight:800; font-size:30px; letter-spacing:.2px; line-height:1;">Charlot</div>
</div>
      <div class="h-sub">Dictionary • Flashcards • Review • Notes</div>
    </div>
    <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;">
      {chip("🥕","XP", str(carrots))}
      {chip("🥐","Level", str(level))}
      {chip("🚬","Cig", str(cigarettes))}
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_quick_find_results(query: str) -> None:
    q = query.strip()
    cards = fetch_cards(q.replace("tag:", "").strip() if q.startswith("tag:") else q)

    # Special: #id direct open
    if q.startswith("#"):
        try:
            cid = int(q[1:])
            c = fetch_card_by_id(cid)
            if c:
                st.session_state.selected_card_id = cid
                st.session_state.nav_pending = "Cards"
                st.rerun()
        except Exception:
            pass

    # Tag quick filter
    if q.lower().startswith("tag:"):
        tag = q.split(":", 1)[1].strip()
        cards = fetch_cards("", tag)

    if not cards:
        st.caption("No matches.")
        return

    st.caption(f"Matches: {min(len(cards), 8)} / {len(cards)}")
    for c in cards[:8]:
        title = (c.get("front") or "").strip() or f"Card #{c['id']}"
        cols = st.columns([1.0, 3.0, 1.0])
        with cols[0]:
            st.markdown(f"<span class='chip'>#{c['id']}</span>", unsafe_allow_html=True)
        with cols[1]:
            st.write(title)
            if c.get("tags"):
                st.caption(c.get("tags"))
        with cols[2]:
            if st.button("Open", key=f"qf_open_{c['id']}", use_container_width=True):
                st.session_state.selected_card_id = int(c["id"])
                st.session_state.nav_pending = "Cards"
                st.rerun()

def top_nav(bp: str) -> str:
    """Unified navigation state + reliable widget sync.

    Key points:
    - `st.session_state["nav"]` is the single source of truth for the current page.
    - The nav widgets (radio/selectbox) store *their own* values under their `key`.
      If we change `nav` programmatically (Home CTA buttons, etc.), we must reset the
      widget key so the UI highlights the correct page.
    - We MUST NOT overwrite the widget key on every rerun, otherwise user clicks
      can get "stuck" (their selection is immediately overwritten).
    """
    page_names = [name for _, name in PAGES]
    page_labels = [f"{ic} {name}" for ic, name in PAGES]
    name_to_label = {name: f"{ic} {name}" for ic, name in PAGES}
    label_to_name = {f"{ic} {name}": name for ic, name in PAGES}

    # 1) Apply any pending nav request (e.g., Home CTA buttons)
    force_sync = False
    pending = st.session_state.get("nav_pending", None)
    if pending:
        st.session_state["nav"] = pending
        st.session_state["nav_pending"] = None
        force_sync = True

    # 2) Sanitize current nav
    cur = st.session_state.get("nav", "Home")
    if cur not in page_names:
        cur = "Home"
        st.session_state["nav"] = cur

    desired_label = name_to_label.get(cur, page_labels[0])

    # 3) If nav changed programmatically, reset widget state so the UI follows.
    if force_sync:
        st.session_state.pop("nav_desktop_radio", None)
        st.session_state.pop("nav_mobile_select", None)

    # 4) Render the nav widget without clobbering user selection.
    if bp == "m":
        # Only seed the widget key if it doesn't exist yet (first run / after reset).
        if "nav_mobile_select" not in st.session_state:
            st.session_state["nav_mobile_select"] = desired_label

        def _on_mobile_change() -> None:
            pick = st.session_state.get("nav_mobile_select", desired_label)
            st.session_state["nav"] = label_to_name.get(pick, "Home")

        with st.expander("☰ Menu", expanded=False):
            pick = st.selectbox(
                "Menu",
                page_labels,
                label_visibility="collapsed",
                key="nav_mobile_select",
                on_change=_on_mobile_change,
            )
        # Ensure nav reflects the *current* widget value on this run too.
        st.session_state["nav"] = label_to_name.get(pick, "Home")

    else:
        if "nav_desktop_radio" not in st.session_state:
            st.session_state["nav_desktop_radio"] = desired_label

        def _on_desktop_change() -> None:
            pick = st.session_state.get("nav_desktop_radio", desired_label)
            st.session_state["nav"] = label_to_name.get(pick, "Home")

        pick = st.radio(
            "Navigation",
            page_labels,
            horizontal=True,
            label_visibility="collapsed",
            key="nav_desktop_radio",
            on_change=_on_desktop_change,
        )
        st.session_state["nav"] = label_to_name.get(pick, "Home")

    return st.session_state["nav"]

# =========================
# Flashcard renderer
# =========================
def render_flashcard_html(front: str, back: str, meta_left: str = "", meta_right: str = "", height: int = 380, theme: str = "Dark") -> None:
    t = THEMES.get(theme, THEMES["Dark"])

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    cid = f"fc_{abs(hash((front, back, meta_left, meta_right, theme))) % 10_000_000}"
    front_html = esc(front)
    back_html = esc(back).replace("\n", "<br/>")
    meta_left = esc(meta_left)
    meta_right = esc(meta_right)

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  :root {{
    --txt: {t["txt"]};
    --mut: {t["mut"]};
    --line: {t["line"]};
    --brand: {t["brand"]};
    --brand2: {t["brand2"]};
    --surface: {t["surface"]};
    --surface2: {t["surface2"]};
    --sh: {t["shadow"]};
  }}
  html, body {{
    margin:0; padding:0;
    background: transparent;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    color: var(--txt);
  }}
  @keyframes enter {{
    from {{ opacity:0; transform: translateY(10px) scale(.992); }}
    to   {{ opacity:1; transform: translateY(0) scale(1); }}
  }}

  .wrap {{ display:flex; justify-content:center; animation: enter .18s ease-out; }}
  .flip {{
    width: min(860px, 100%);
    height: 320px;
    perspective: 1400px;
    margin: 8px auto 6px auto;
  }}
  .flip input {{
    position:absolute; opacity:0; pointer-events:none; width:1px; height:1px;
  }}
  .flip-card {{
    width:100%; height:100%;
    position:relative;
    transform-style:preserve-3d;
    transition: transform .58s cubic-bezier(.2,.9,.2,1);
  }}
  .flip input:checked + .flip-card {{ transform: rotateY(180deg); }}

  .face {{
    position:absolute; inset:0;
    border-radius: 28px;
    border: 1px solid var(--line);
    box-shadow: var(--sh);
    backface-visibility:hidden;
    overflow:hidden;
  }}
  .front {{
    background:
      radial-gradient(600px 260px at 18% 10%, rgba(28,176,246,.20), transparent 60%),
      radial-gradient(620px 280px at 86% 86%, rgba(88,204,2,.14), transparent 62%),
      linear-gradient(180deg, var(--surface), var(--surface2));
  }}
  .back {{
    transform: rotateY(180deg);
    background:
      radial-gradient(650px 300px at 20% 20%, rgba(88,204,2,.18), transparent 62%),
      radial-gradient(650px 300px at 86% 86%, rgba(28,176,246,.14), transparent 62%),
      linear-gradient(180deg, var(--surface), var(--surface2));
  }}

  .inner {{
    height:100%;
    padding: 22px 24px;
    display:flex;
    flex-direction:column;
    justify-content:center;
    gap: 12px;
  }}
  .top {{
    display:flex; justify-content:space-between; align-items:center;
    color: var(--mut);
    font-size: 13px;
    margin-bottom: 4px;
    font-weight: 800;
  }}
  .pill {{
    display:inline-flex; align-items:center; gap:8px;
    padding: 7px 11px;
    border-radius: 999px;
    background: rgba(0,0,0,.06);
    border: 1px solid var(--line);
  }}

  .title {{
    font-size: clamp(28px, 3.2vw, 48px);
    font-weight: 1000;
    letter-spacing: .2px;
    line-height: 1.05;
  }}
  .body {{
    font-size: 16px;
    color: var(--txt);
    line-height: 1.55;
  }}
  .hint {{
    display:inline-flex; align-items:center; gap:8px;
    color: var(--mut);
    font-size: 13px;
    padding-top: 8px;
    font-weight: 800;
  }}
  kbd {{
    background: rgba(0,0,0,.12);
    border:1px solid var(--line);
    border-bottom-color: rgba(0,0,0,.22);
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 12px;
    color: var(--txt);
  }}
</style>
</head>
<body>
  <div class="wrap">
    <label class="flip" for="{cid}" title="Click to flip">
      <input id="{cid}" type="checkbox"/>
      <div class="flip-card">
        <div class="face front">
          <div class="inner">
            <div class="top">
              <span class="pill">🏷️ {meta_left}</span>
              <span class="pill">⏳ {meta_right}</span>
            </div>
            <div class="title">{front_html}</div>
            <div class="hint">Tap to flip <kbd>Space</kbd> or click</div>
          </div>
        </div>

        <div class="face back">
          <div class="inner">
            <div class="top">
              <span class="pill">✅ Answer</span>
              <span class="pill">🧠 Recall</span>
            </div>
            <div class="body">{back_html}</div>
            <div class="hint">Tap to flip back</div>
          </div>
        </div>
      </div>
    </label>
  </div>
</body>
</html>"""
    components.html(html, height=height, scrolling=False)

def select_card(card_id: int) -> None:
    st.session_state.selected_card_id = int(card_id)
    st.session_state.scroll_to_selected_card = True

def render_selected_card_viewer(title: str = "Selected card") -> None:
    cid = st.session_state.get("selected_card_id")
    if not cid:
        return
    card = fetch_card_by_id(int(cid))
    if not card:
        st.session_state.selected_card_id = None
        return

    anchor_id = f"card_viewer_{card['id']}"
    st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)

    if st.session_state.get("scroll_to_selected_card", False):
        st.session_state.scroll_to_selected_card = False  # one-shot
        components.html(
            f"""
<script>
(function() {{
  const id = "{anchor_id}";
  function go() {{
    const el = window.parent.document.getElementById(id) || document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({{ behavior: "smooth", block: "start" }});
    setTimeout(() => window.parent.scrollBy(0, -80), 120);
  }}
  setTimeout(go, 60);
}})();
</script>
            """,
            height=0,
        )

    st.markdown(f"### {title} • #{card['id']}")
    st.caption(f"lang: {card.get('language','')} • created: {card.get('created_at','—')[:19]} • due: {card.get('due_date','—')}")
    if card.get("tags"):
        st.markdown(f"<span class='chip'>🏷️ <b>{card['tags']}</b></span>", unsafe_allow_html=True)

    if st.button("Close", key=f"close_card_{card['id']}_viewer"):
        st.session_state.selected_card_id = None
        st.rerun()

    meta_left = f"#{card['id']} • {card.get('language','fr')}"
    meta_right = f"due {card.get('due_date','—')}"
    render_flashcard_html(front=card.get("front", "") or "", back=card.get("back", "") or "", meta_left=meta_left, meta_right=meta_right, height=360, theme=st.session_state.get("theme", "Dark"))

    extra = []
    if (card.get("example") or "").strip():
        extra.append(("Example", card.get("example", "")))
    if (card.get("notes") or "").strip():
        extra.append(("Notes", card.get("notes", "")))
    if extra:
        with st.expander("More", expanded=False):
            for k, v in extra:
                st.markdown(f"**{k}**")
                st.write(v)

# =========================
# Pages
# =========================
def progress_ring_html(pct: int, label: str, sub: str) -> str:
    pct = max(0, min(100, int(pct)))
    return f"""
<div style="display:flex; align-items:center; gap:14px;">
  <div style="
      width:64px; height:64px; border-radius:999px;
      background: conic-gradient(var(--brand) {pct}%, rgba(0,0,0,.10) 0);
      display:grid; place-items:center;
      box-shadow: var(--sh2);
      border:1px solid var(--line);
  ">
    <div style="
        width:48px; height:48px; border-radius:999px;
        background: linear-gradient(180deg, var(--surface), var(--surface2));
        display:grid; place-items:center;
        font-weight:1000;
    ">{pct}%</div>
  </div>
  <div>
    <div style="font-weight:1000; font-size:16px;">{label}</div>
    <div class="small">{sub}</div>
  </div>
</div>
"""

def build_due_calendar_html(days: int = 14) -> str:
    start = today_utc_date()

    # NEW: precompute which dates have activity (fast: one SQL query)
    active_days = activity_dates_between(start, days)

    counts = []
    maxc = 1
    for i in range(days):
        d = start + timedelta(days=i)
        c = len(fetch_due_cards(d))
        counts.append((d, c))
        maxc = max(maxc, c)

    t = THEMES.get(st.session_state.get("theme", "Dark"), THEMES["Dark"])

    items = []
    for d, c in counts:
        size = 8 + int(14 * (c / maxc)) if maxc > 0 else 8
        op = 0.30 + 0.60 * (c / maxc) if maxc > 0 else 0.30
        label = d.strftime("%a %d")

        iso = d.isoformat()
        is_active = iso in active_days

        # NEW: green if active else red
        dot_bg = (
            "radial-gradient(circle at 30% 30%, rgba(12,255,120,.95), rgba(35,200,35,.95))"
            if is_active
            else "radial-gradient(circle at 30% 30%, rgba(128,128,128,.95), rgba(128,128,128,.95))"
        )

        tip = f"{label}: {c} due" + (" • active ✅" if is_active else " • no activity ❌")

        items.append(
            f"""
<div class="cell" title="{tip}">
  <div class="day">{label}</div>
  <div class="dot" style="width:{size}px;height:{size}px;opacity:{op};background:{dot_bg};"></div>
  <div class="num">{c}</div>
</div>
            """
        )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  :root {{
    --txt: {t["txt"]};
    --mut: {t["mut"]};
    --line: {t["line"]};
    --surface: {t["surface"]};
    --surface2: {t["surface2"]};
  }}
  html, body {{ margin:0; padding:0; background: transparent; font-family: ui-sans-serif, system-ui; color: var(--txt); }}
  .grid {{
    display:grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 10px;
    padding: 8px 6px;
  }}
  .cell {{
    background: linear-gradient(180deg, var(--surface), var(--surface2));
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 10px 8px;
    text-align:center;
  }}
  .day {{ font-size: 12px; color: var(--mut); margin-bottom: 6px; font-weight: 900; }}
  .dot {{
    margin: 0 auto;
    border-radius: 999px;
    box-shadow: 0 10px 22px rgba(0,0,0,.14);
  }}
  .num {{ margin-top: 6px; font-size: 12px; color: var(--mut); font-weight: 900; }}
</style></head>
<body>
  <div class="grid">
    {''.join(items)}
  </div>
</body></html>
"""
    return html

def home_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Home")

    cards_total = count_cards_db()
    due_today = len(fetch_due_cards(today_utc_date()))
    carrots = int(st.session_state.get("xp", 0) or 0)
    cigarettes, cig_toward = cigarettes_from_xp(carrots)
    level, xp_in, xp_need = level_from_xp(carrots)
    pct = 0 if xp_need <= 0 else int(100 * (xp_in / xp_need))

    left, right = st.columns([1.35, 1.0], gap="small")

    with left:
        st.markdown(
            f"""
<div class="card">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
    <div>
      <div class="h-title">Today’s plan</div>
      <div class="h-sub">Keep momentum with small, consistent actions.</div>
    </div>
    <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;">
      <span class="chip">🗂️ <b>Total</b> {cards_total}</span>
      <span class="chip">📌 <b>Due</b> {due_today}</span>
    </div>
  </div>
  <hr/>
  {progress_ring_html(pct, f"🥐 Level {level}", f"{xp_in}/{xp_need} 🥕 to next 🥐")}
</div>
""",
            unsafe_allow_html=True,
        )

        # Spacer so the primary actions don’t visually “stick” to the card above.
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1.1, 1.1, 1.0])
        with c1:
            if st.button("Start review", type="primary", use_container_width=True, key="home_btn_start_review"):
                st.session_state.nav_pending = "Review"
                st.session_state.review_idx = 0
                st.rerun()
        with c2:
            if st.button("Add a new card", use_container_width=True, key="home_btn_add_card"):
                st.session_state.nav_pending = "Cards"
                st.session_state.edit_card_id = None
                st.session_state.scroll_to_editor = True
                st.rerun()
        with c3:
            if st.button("Dictionary", use_container_width=True, key="home_btn_dictionary"):
                st.session_state.nav_pending = "Dictionary"
                st.rerun()

        st.markdown("")
        st.markdown(
            """
<div class="card">
  <div class="h-title">Review calendar</div>
  <div class="h-sub">How many cards are due each day (next 14 days).</div>
</div>
""",
            unsafe_allow_html=True,
        )
        components.html(build_due_calendar_html(14), height=220, scrolling=False)

    with right:
        carrots, croissants, _ = carrots_and_croissants()
        cigarettes, _cig_toward = cigarettes_from_xp(carrots)
        st.markdown(
            f"""
<div class="card">
  <div class="h-title">Stats</div>
  <div class="h-sub">A quick snapshot.</div>
  <hr/>
  <div style="display:flex; flex-direction:column; gap:12px;">
    <div>
      <div class="statline"><span class="statlabel">🔥 Streak</span><span class="statvalue">{int(st.session_state.get("streak", 1) or 1)}</span></div>
      <div class="small">Consecutive days you earned at least 1 🥕.</div>
    </div>
    <div>
      <div class="statline"><span class="statlabel">🥕 Carrots</span><span class="statvalue">{carrots}</span></div>
      <div class="small">Your XP — you earn 🥕 mainly by creating new cards.</div>
    </div>
    <div>
      <div class="statline"><span class="statlabel">🥐 Croissants</span><span class="statvalue">{croissants}</span></div>
      <div class="small">Every 10 🥕 becomes 1 🥐 (level-up).</div>
    </div>
    <div>
      <div class="statline"><span class="statlabel">🚬 Cigarettes</span><span class="statvalue">{cigarettes}</span></div>
      <div class="small">Every 5 🥐 becomes 1 🚬 (50 🥕 total).</div>
    </div>
    <div>
      <div class="statline"><span class="statlabel">📌 Due today</span><span class="statvalue">{due_today}</span></div>
      <div class="small">Cards scheduled to review today.</div>
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

def dictionary_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Dictionary")

    st.markdown(
        """
<div class="card">
  <div class="h-title">Lookup a word</div>
  <div class="h-sub">Fast definitions + save as flashcards.</div>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.form("dict_search_form", clear_on_submit=False):
        colA, colB, colC = st.columns([2.2, 1.0, 1.0])
        with colA:
            word = st.text_input("Word / expression", placeholder="ex: faire, pourtant, un peu…")
        with colB:
            lang = st.selectbox("Language", ["fr", "en"], index=0, help="Lookup language.")
        with colC:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            do = st.form_submit_button("Search", type="primary", use_container_width=True)

    if word.strip():
        w = requests.utils.quote(word.strip())
        st.markdown(
            f"""
<div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">
  <a href="https://www.wordreference.com/fren/{w}" target="_blank" style="text-decoration:none;"><span class="chip">WordReference ↗</span></a>
  <a href="https://context.reverso.net/translation/french-english/{w}" target="_blank" style="text-decoration:none;"><span class="chip">Reverso ↗</span></a>
  <a href="https://www.larousse.fr/dictionnaires/francais/{w}" target="_blank" style="text-decoration:none;"><span class="chip">Larousse ↗</span></a>
</div>
""",
            unsafe_allow_html=True,
        )

    if not (do and word.strip()):
        return

    with st.spinner("Looking up…"):
        source, data = best_dictionary_result(lang, word)

    st.markdown("---")
    if source == "dictapi":
        parsed = data["parsed"]
        st.success("Source: dictionaryapi.dev")

        if parsed["phonetics"]:
            st.markdown("### 🔊 Pronunciation")
            for p in parsed["phonetics"][:5]:
                cols = st.columns([1, 2])
                with cols[0]:
                    if p["text"]:
                        st.write(f"`{p['text']}`")
                with cols[1]:
                    if p["audio"]:
                        st.audio(p["audio"])

        st.markdown("### 📌 Meanings")
        primary_def = ""
        for m in parsed["meanings"]:
            st.markdown(f"**{m['partOfSpeech'] or '—'}**")
            defs = m["definitions"] or []
            for i, d in enumerate(defs[:6], start=1):
                st.markdown(f"**{i}.** {d['definition']}")
                if d["example"]:
                    st.markdown(f"> _{d['example']}_")
            if not primary_def and defs:
                primary_def = defs[0]["definition"]

        st.markdown("### ➕ Save as flashcard")
        with st.form("add_from_dictapi", clear_on_submit=False):
            front = st.text_input("Front", value=word.strip())
            back = st.text_area("Back", value=primary_def, height=110)
            tags = st.text_input("Tags (comma-separated)", value="dictionary")
            example = st.text_area("Example sentence", value="", height=70)
            notes = st.text_area("Notes", value="", height=70)
            submitted = st.form_submit_button("Add flashcard", type="primary")
            if submitted:
                if not front.strip() or not back.strip():
                    st.warning("Front and Back are required.")
                else:
                    cid = create_card(lang, front, back, tags, example, notes)
                    bump_xp(1)
                    toast(f"Saved card #{cid}. +1 🥕", icon="🥕")
        return

    if source.startswith("wiktionary"):
        st.success(f"Source: Wiktionary ({'REST summary' if source=='wiktionary_summary' else 'extract'})")
        title = data.get("title") or word.strip()
        extract = data.get("extract") or ""
        snippet = summarize_extract(extract)

        st.markdown(f"### {title}")
        st.write(snippet)
        with st.expander("Show full text"):
            st.write(extract)
        st.caption(f"Endpoint: {data.get('source','')}")

        st.markdown("### ➕ Save as flashcard")
        with st.form("add_from_wiktionary", clear_on_submit=False):
            front = st.text_input("Front", value=word.strip())
            back = st.text_area("Back", value=snippet, height=140)
            tags = st.text_input("Tags (comma-separated)", value="wiktionary")
            example = st.text_area("Example sentence", value="", height=70)
            notes = st.text_area("Notes", value=f"Source: {data.get('source','Wiktionary')}", height=70)
            submitted = st.form_submit_button("Add flashcard", type="primary")
            if submitted:
                if not front.strip() or not back.strip():
                    st.warning("Front and Back are required.")
                else:
                    cid = create_card(lang, front, back, tags, example, notes)
                    bump_xp(1)
                    toast(f"Saved card #{cid}. +1 🥕", icon="🥕")
        return

    st.error("No result from any dictionary backend.")
    st.code(safe_json(data), language="json")

def review_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Review")

    # Which bucket list (if any) the user is browsing in Review.
    st.session_state.setdefault("review_bucket_view", "")

    allc = fetch_cards()
    buckets: Dict[str, List[Dict[str, Any]]] = {"new": [], "difficult": [], "meh": [], "easy": []}
    for row in allc:
        buckets.setdefault(difficulty_bucket(row), []).append(row)

    badge_row([
        ("🆕", f"New {len(buckets['new'])}"),
        ("😵", f"Difficult {len(buckets['difficult'])}"),
        ("😐", f"Meh {len(buckets['meh'])}"),
        ("😌", f"Easy {len(buckets['easy'])}"),
    ])

    
    # Browse buckets (tabs)
    due_today = fetch_due_cards(today_utc_date())

    def _render_bucket_list(cards: List[Dict[str, Any]], key_prefix: str, empty_msg: str):
        q = st.text_input("Find", value="", placeholder="Type to filter…", key=f"{key_prefix}_q")
        qn = q.strip().lower()
        shown = 0
        for r in cards:
            front = (r.get("front", "") or "").strip()
            back = (r.get("back", "") or "").strip()
            tags = (r.get("tags", "") or "").strip()
            title = front if front else f"Card #{r.get('id')}"
            example = (r.get("example", "") or "").strip()
            notes = (r.get("notes", "") or "").strip()
            hay = f"{front} {back} {tags} {example} {notes}".lower()
            if qn and qn not in hay:
                continue
            shown += 1
            cols = st.columns([1.6, 1.0, 0.7])
            with cols[0]:
                st.markdown(f"**{title}**")
                if back:
                    st.caption(textwrap.shorten(back, width=140, placeholder="…"))
            with cols[1]:
                st.caption(f"#{r.get('id')} • {tags or '—'}")
            with cols[2]:
                if st.button("Open", key=f"{key_prefix}_open_{r.get('id')}", use_container_width=True):
                    select_card(int(r.get("id")))
                    st.rerun()
            st.divider()
        if shown == 0:
            st.info(empty_msg)

    tabs = st.tabs([
        f"All due ({len(due_today)})",
        f"🆕 New ({len(buckets['new'])})",
        f"😵 Difficult ({len(buckets['difficult'])})",
        f"😐 Meh ({len(buckets['meh'])})",
        f"😌 Easy ({len(buckets['easy'])})",
    ])

    with tabs[0]:
        _render_bucket_list(
            due_today,
            "tab_due",
            "No cards are due right now."
        )

    with tabs[1]:
        _render_bucket_list(
            buckets.get("new", []),
            "tab_new",
            "No cards in New."
        )

    with tabs[2]:
        _render_bucket_list(
            buckets.get("difficult", []),
            "tab_diff",
            "No cards in Difficult."
        )

    with tabs[3]:
        _render_bucket_list(
            buckets.get("meh", []),
            "tab_meh",
            "No cards in Meh."
        )

    with tabs[4]:
        _render_bucket_list(
            buckets.get("easy", []),
            "tab_easy",
            "No cards in Easy."
        )


    st.markdown("")
    colA, colB, colC = st.columns([1.6, 1.0, 1.0])
    with colA:
        created_on = st.date_input("Browse cards created on", value=today_utc_date())
    with colB:
        st.write("")
        if st.button("Restart queue", use_container_width=True):
            st.session_state.review_idx = 0
            toast("Review queue restarted.", icon="🔁")
            st.rerun()
    with colC:
        st.write("")
        if st.button("Go to Cards", use_container_width=True):
            st.session_state.nav_pending = "Cards"
            st.rerun()

    with st.expander(f"📅 Cards created on {created_on.isoformat()} ({len(fetch_cards_created_on(created_on))})", expanded=False):
        created_cards = fetch_cards_created_on(created_on)
        if not created_cards:
            st.info("No cards were created on this date.")
        else:
            for r in created_cards[:200]:
                label = (r.get("front", "") or "").strip() or f"Card #{r.get('id')}"
                if st.button(label, key=f"created_open_{r.get('id')}", use_container_width=True):
                    select_card(int(r.get("id")))
                    st.rerun()
                st.caption(f"#{r.get('id')} • tags: {r.get('tags','')} • created: {r.get('created_at','—')[:19]}")
                st.divider()

    if st.session_state.get("selected_card_id"):
        render_selected_card_viewer(title="Selected card")

    st.markdown("---")

    due = fetch_due_cards(today_utc_date())
    if not due:
        st.success("No cards due. 🎉")
        st.caption("Add more words in Dictionary or Cards.")
        return

    idx = int(st.session_state.review_idx)
    idx = max(0, min(idx, len(due) - 1))
    card = due[idx]

    badge_row([
        ("📌", f"Queue {len(due)}"),
        ("🧾", f"Card {idx+1}/{len(due)}"),
        ("⏱️", f"Interval {card.get('interval_days',0)}d"),
        ("⚖️", f"Ease {float(card.get('ease',2.5)):.2f}"),
    ])

    meta_left = f"#{card['id']} • {card.get('language','fr')}"
    meta_right = f"due {card.get('due_date','')}"
    render_flashcard_html(front=card["front"], back=card["back"], meta_left=meta_left, meta_right=meta_right, height=390, theme=st.session_state.get("theme", "Dark"))

    if (card.get("example") or "").strip() or (card.get("notes") or "").strip():
        c1, c2 = st.columns([1.2, 1.2])
        with c1:
            if (card.get("example") or "").strip():
                st.markdown("**Example**")
                st.markdown(f"> _{card['example']}_")
        with c2:
            if (card.get("notes") or "").strip():
                st.markdown("**Notes**")
                st.write(card["notes"])

    st.markdown("### 🎯 Grade your recall")
    st.caption("5 = very difficult • 1 = very easy (we convert it internally to SM‑2 quality).")
    q_user = st.radio("Difficulty", [1, 2, 3, 4, 5], index=2, horizontal=True)
    q_sm2 = 6 - int(q_user)

    st.markdown('<div class="sticky-bottom">', unsafe_allow_html=True)
    b1, b2, b3, b4 = st.columns([1.2, 1.1, 1.1, 1.0])
    with b1:
        if st.button("Submit grade", type="primary", use_container_width=True):
            interval, reps, ease = sm2_next(card, q_sm2)
            next_due = today_utc_date() + timedelta(days=interval)
            update_review_state(card["id"], next_due, interval, reps, ease, last_quality=int(q_user))
            bump_xp(1)

            st.session_state.review_idx = idx + 1
            if st.session_state.review_idx >= len(due):
                st.balloons()
                st.session_state.review_idx = 0
                toast("Queue complete!", icon="🎉")
            st.rerun()
    with b2:
        if st.button("Skip", use_container_width=True):
            st.session_state.review_idx = idx + 1
            if st.session_state.review_idx >= len(due):
                st.session_state.review_idx = 0
            st.rerun()
    with b3:
        if st.button("Back", use_container_width=True):
            st.session_state.review_idx = max(0, idx - 1)
            st.rerun()
    with b4:
        if st.button("Open card", use_container_width=True):
            select_card(int(card["id"]))
            st.session_state.nav_pending = "Cards"
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)



def manage_cards_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Cards")
    st.caption("Search, filter, and manage your flashcards. Tip: type **#123** or **tag:food** in the search box.")

    bp = detect_breakpoint(760)
    is_mobile = (bp == "m")

    tags_list = [""] + all_tags()
    sort_labels = {
        "Recently updated": "updated_desc",
        "Due soon": "due_asc",
        "Newest": "created_desc",
        "A → Z (front)": "front_asc",
    }

    with st.container(border=True):
        f1, f2, f3, f4, f5 = st.columns([2.2, 1.2, 1.1, 1.1, 1.0])
        with f1:
            q = st.text_input(
                "Search",
                placeholder="front/back/example/notes…  (examples: #42, tag:verbs)",
                key="cards_search",
            )
        with f2:
            tag = st.selectbox("Tag", tags_list, index=0, key="cards_tag")
        with f3:
            sort_pick = st.selectbox("Sort", list(sort_labels.keys()), index=0, key="cards_sort")
            order_by = sort_labels.get(sort_pick, "updated_desc")
        with f4:
            st.session_state.cards_page_size = st.selectbox(
                "Page size",
                [12, 18, 24, 36],
                index=[12, 18, 24, 36].index(int(st.session_state.get("cards_page_size", 18))),
                key="cards_page_size_sel",
            )
        with f5:
            st.write("")
            if st.button("＋ New", type="primary", use_container_width=True):
                st.session_state.edit_card_id = None
                st.session_state.selected_card_id = None
                st.session_state.delete_confirm_id = None
                st.session_state.scroll_to_editor = True
                st.rerun()

    # Reset pagination if filters changed
    prev = st.session_state.get("_cards_filters_prev", None)
    cur = (q, tag, order_by, int(st.session_state.get("cards_page_size", 18)))
    if prev != cur:
        st.session_state.cards_page = 1
        st.session_state._cards_filters_prev = cur

    # Quick jump / quick tag filter
    q_eff = q.strip()
    if q_eff.startswith("#"):
        try:
            cid = int(q_eff[1:])
            c = fetch_card_by_id(cid)
            if c:
                select_card(cid)
                st.session_state.edit_card_id = None
                st.session_state.cards_search = ""
                toast(f"Opened card #{cid}.", icon="📌")
        except Exception:
            pass
        q_eff = ""
    elif q_eff.lower().startswith("tag:"):
        tag_from_q = q_eff.split(":", 1)[1].strip()
        if tag_from_q:
            st.session_state.cards_tag = tag_from_q
            tag = tag_from_q
        q_eff = ""

    cards = fetch_cards(q_eff, tag, order_by=order_by)
    total = len(cards)

    # Pagination
    page_size = int(st.session_state.get("cards_page_size", 18))
    pages = max(1, (total + page_size - 1) // page_size)
    st.session_state.cards_page = max(1, min(int(st.session_state.get("cards_page", 1)), pages))

    top_row = st.columns([1.0, 2.4, 1.0])
    with top_row[0]:
        if st.button("◀ Prev", use_container_width=True, disabled=(st.session_state.cards_page <= 1)):
            st.session_state.cards_page -= 1
            st.rerun()
    with top_row[1]:
        if total == 0:
            st.markdown("<div class='small' style='text-align:center; padding-top:6px;'>No cards found.</div>", unsafe_allow_html=True)
        else:
            a = (st.session_state.cards_page - 1) * page_size + 1
            b = min(total, st.session_state.cards_page * page_size)
            st.markdown(
                f"<div class='small' style='text-align:center; padding-top:6px;'>Showing <b>{a}</b>–<b>{b}</b> of <b>{total}</b> • Page <b>{st.session_state.cards_page}</b> / {pages}</div>",
                unsafe_allow_html=True,
            )
    with top_row[2]:
        if st.button("Next ▶", use_container_width=True, disabled=(st.session_state.cards_page >= pages)):
            st.session_state.cards_page += 1
            st.rerun()

    start = (st.session_state.cards_page - 1) * page_size
    end = min(total, start + page_size)
    rows = cards[start:end]

    def editor_panel() -> None:
        editor_anchor_id = "cards_editor_anchor"
        st.markdown(f"<div id='{editor_anchor_id}'></div>", unsafe_allow_html=True)

        # One-shot smooth scroll (triggered by ＋ New)
        if st.session_state.get("scroll_to_editor", False):
            st.session_state.scroll_to_editor = False
            components.html(
                f"""
<script>
(function() {{
  const id = "{editor_anchor_id}";
  function go() {{
    const el = window.parent.document.getElementById(id) || document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({{ behavior: "smooth", block: "start" }});
    // compensate for Streamlit header spacing
    setTimeout(() => window.parent.scrollBy(0, -80), 120);
  }}
  setTimeout(go, 60);
}})();
</script>
""",
                height=0,
            )

        st.markdown("### ✍️ Editor")
        edit_id = st.session_state.get("edit_card_id", None)
        if edit_id is None:
            st.caption("Create a new card.")
            editor_card = {"id": None, "language": "fr", "front": "", "back": "", "tags": "", "example": "", "notes": ""}
        else:
            editor_card = fetch_card_by_id(int(edit_id))
            if not editor_card:
                st.warning("Card not found.")
                st.session_state.edit_card_id = None
                st.rerun()

        form_key = f"card_editor__{edit_id if edit_id is not None else 'new'}__cards_page_v10"
        with st.form(key=form_key, clear_on_submit=False):
            language = st.selectbox("Language", ["fr", "en"], index=0 if editor_card.get("language") == "fr" else 1)
            front = st.text_input("Front", value=editor_card.get("front", ""))
            back = st.text_area("Back", value=editor_card.get("back", ""), height=110)
            tags = st.text_input("Tags (comma-separated)", value=editor_card.get("tags", ""))
            example = st.text_area("Example sentence", value=editor_card.get("example", ""), height=70)
            notes = st.text_area("Notes", value=editor_card.get("notes", ""), height=70)

            submitted = st.form_submit_button("Save", type="primary")
            if submitted:
                if not front.strip() or not back.strip():
                    st.warning("Front and Back are required.")
                else:
                    if editor_card["id"] is None:
                        cid = create_card(language, front, back, tags, example, notes)
                        bump_xp(1)
                        toast(f"Created card #{cid}. +1 🥕", icon="🥕")
                        select_card(cid)
                    else:
                        update_card(int(editor_card["id"]), language, front, back, tags, example, notes)
                        bump_xp(1)
                        toast("Updated. +1 🥕", icon="🥕")
                        select_card(int(editor_card["id"]))
                    st.session_state.edit_card_id = None
                    st.rerun()

    def inspector_panel() -> None:
        with st.container(border=True):
            st.markdown("### Inspector")
            if st.session_state.get("selected_card_id"):
                render_selected_card_viewer(title="Selected card")
            else:
                st.caption("Select a card to preview it here.")
                st.markdown(
                    "<div class='small'>Pro tips:<br/>• Search <b>#id</b> to jump<br/>• Search <b>tag:xxx</b> to filter<br/>• Keep fronts short; put context in example/notes</div>",
                    unsafe_allow_html=True,
                )
            st.markdown("---")
            editor_panel()

    def render_tile(c: Dict[str, Any], key_prefix: str = "") -> None:
        title = (c.get("front", "") or "").strip() or f"Card #{c['id']}"
        due = c.get("due_date") or "—"
        lang = c.get("language", "fr")

        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(f"#{c['id']} • {lang} • due: {due}")

            if c.get("tags"):
                st.markdown(f"<span class='chip'>🏷️ <b>{c['tags']}</b></span>", unsafe_allow_html=True)

            back = (c.get("back") or "").strip()
            if back:
                st.markdown("<div class='small' style='margin-top:8px; font-weight:850;'>Back</div>", unsafe_allow_html=True)
                st.write(back[:180] + ("…" if len(back) > 180 else ""))

            confirm_id = st.session_state.get("delete_confirm_id")
            if confirm_id == c["id"]:
                st.warning("Delete this card? This cannot be undone.")
                d1, d2 = st.columns(2)
                with d1:
                    if st.button("Yes, delete", key=f"{key_prefix}confirm_del_{c['id']}", use_container_width=True):
                        delete_card(c["id"])
                        st.session_state.delete_confirm_id = None
                        if st.session_state.get("selected_card_id") == c["id"]:
                            st.session_state.selected_card_id = None
                        toast("Deleted.", icon="🗑️")
                        st.rerun()
                with d2:
                    if st.button("Cancel", key=f"{key_prefix}cancel_del_{c['id']}", use_container_width=True):
                        st.session_state.delete_confirm_id = None
                        st.rerun()
            else:
                # On mobile widths, short labels + icons prevent awkward wrapping.
                # Desktop keeps full labels.
                if is_mobile:
                    st.markdown('<div class="card-action-row">', unsafe_allow_html=True)
                    a1, a2, a3 = st.columns([1, 1, 1], gap="small")
                    with a1:
                        if st.button("🟢 Open", help="Open this card", key=f"{key_prefix}cards_open_{c['id']}", type="primary", use_container_width=True):
                            select_card(int(c["id"]))
                            st.session_state.edit_card_id = None
                            st.rerun()
                    with a2:
                        if st.button("✏️ Edit", help="Edit this card", key=f"{key_prefix}cards_edit_{c['id']}", use_container_width=True):
                            st.session_state.edit_card_id = int(c["id"])
                            select_card(int(c["id"]))
                            st.session_state.delete_confirm_id = None
                            st.rerun()
                    with a3:
                        if st.button("🗑️ Del", help="Delete (confirm)", key=f"{key_prefix}cards_del_{c['id']}", use_container_width=True):
                            st.session_state.delete_confirm_id = int(c["id"])
                            st.rerun()

                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    a1, a2, a3 = st.columns([1.2, 1.0, 1.0])
                    with a1:
                        if st.button("Open", key=f"{key_prefix}cards_open_{c['id']}", type="primary", use_container_width=True):
                            select_card(int(c["id"]))
                            st.session_state.edit_card_id = None
                            st.rerun()
                    with a2:
                        if st.button("Edit", key=f"{key_prefix}cards_edit_{c['id']}", use_container_width=True):
                            st.session_state.edit_card_id = int(c["id"])
                            select_card(int(c["id"]))
                            st.session_state.delete_confirm_id = None
                            st.rerun()
                    with a3:
                        if st.button("Delete", key=f"{key_prefix}cards_del_{c['id']}", use_container_width=True):
                            st.session_state.delete_confirm_id = int(c["id"])
                            st.rerun()

    def grid_panel() -> None:
        if not rows:
            st.info("No cards matched your filters. Create your first one with **＋ New**.")
            return
        ncol = 1 if is_mobile else 3
        for i in range(0, len(rows), ncol):
            cols = st.columns(ncol, gap="large")
            for j in range(ncol):
                k = i + j
                if k >= len(rows):
                    break
                with cols[j]:
                    render_tile(rows[k], key_prefix=f"t_{rows[k]['id']}_")

    # UX change: keep Cards as the primary content.
    # Inspector + Editor appear *under* the grid (not as a right-side column).
    grid_panel()
    st.markdown("---")
    inspector_panel()


# =========================
# Grammar (Topics + Mistakes)
# =========================

def _now_utc_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def create_grammar_topic(title: str, rule: str, examples: List[str], traps: str, tags: str = "") -> int:
    title = norm_text(title)
    if not title:
        raise ValueError("Topic title is required.")
    rule = norm_text(rule)
    traps = norm_text(traps)
    tags = norm_text(tags)
    examples = [norm_text(x) for x in (examples or []) if norm_text(x)]
    now = _now_utc_iso()

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO grammar_topics(user_id, title, rule, examples, traps, tags, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(current_user_id() or 1), title, rule, safe_json(examples), traps, tags, now, now),
    )
    topic_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return topic_id


def update_grammar_topic(topic_id: int, title: str, rule: str, examples: List[str], traps: str, tags: str = "") -> None:
    title = norm_text(title)
    if not title:
        raise ValueError("Topic title is required.")
    rule = norm_text(rule)
    traps = norm_text(traps)
    tags = norm_text(tags)
    examples = [norm_text(x) for x in (examples or []) if norm_text(x)]
    now = _now_utc_iso()

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE grammar_topics
        SET title=?, rule=?, examples=?, traps=?, tags=?, updated_at=?
        WHERE id=? AND user_id=?
        """,
        (title, rule, safe_json(examples), traps, tags, now, int(topic_id)),
    )
    conn.commit()
    conn.close()


def delete_grammar_topic(topic_id: int) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM grammar_topics WHERE id=? AND user_id=?;", (int(topic_id), int(current_user_id() or 1)))
    conn.commit()
    conn.close()


def list_grammar_topics() -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, rule, examples, traps, tags, created_at, updated_at
        FROM grammar_topics
        WHERE user_id = ?
        ORDER BY updated_at DESC, id DESC
        """,
        (int(current_user_id() or 1),),
    )
    rows = cur.fetchall()
    conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        ex_raw = r[3] or "[]"
        try:
            ex = json.loads(ex_raw)
            if not isinstance(ex, list):
                ex = []
        except Exception:
            ex = []
        out.append(
            {
                "id": int(r[0]),
                "title": r[1] or "",
                "rule": r[2] or "",
                "examples": ex,
                "traps": r[4] or "",
                "tags": r[5] or "",
                "created_at": r[6] or "",
                "updated_at": r[7] or "",
            }
        )
    return out


def create_grammar_mistake(category: str, wrong: str, correct: str, note: str, topic_id: Optional[int] = None) -> int:
    wrong = norm_text(wrong)
    if not wrong:
        raise ValueError("Wrong sentence is required.")
    category = norm_text(category)
    correct = norm_text(correct)
    note = norm_text(note)

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO grammar_mistakes(user_id, category, wrong, correct, note, topic_id, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (int(current_user_id() or 1), category, wrong, correct, note, (int(topic_id) if topic_id else None), _now_utc_iso()),
    )
    mid = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return mid


def delete_grammar_mistake(mistake_id: int) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM grammar_mistakes WHERE id=? AND user_id=?;", (int(mistake_id), int(current_user_id() or 1)))
    conn.commit()
    conn.close()


def list_grammar_mistakes(limit: int = 100) -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.id, m.category, m.wrong, m.correct, m.note, m.topic_id, m.created_at, t.title
        FROM grammar_mistakes m
        LEFT JOIN grammar_topics t ON t.id = m.topic_id
        WHERE m.user_id = ?
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (int(current_user_id() or 1), int(limit)),
    )
    rows = cur.fetchall()
    conn.close()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "category": r[1] or "",
                "wrong": r[2] or "",
                "correct": r[3] or "",
                "note": r[4] or "",
                "topic_id": (int(r[5]) if r[5] is not None else None),
                "created_at": r[6] or "",
                "topic_title": r[7] or "",
            }
        )
    return out


def search_grammar(q: str, limit: int = 50) -> Dict[str, List[Dict[str, Any]]]:
    qn = norm_text(q)
    if not qn:
        return {"topics": [], "mistakes": []}

    like = f"%{qn}%"
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, rule, examples, traps, tags, created_at, updated_at
        FROM grammar_topics
        WHERE title LIKE ? OR rule LIKE ? OR traps LIKE ? OR tags LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (like, like, like, like, int(limit)),
    )
    topic_rows = cur.fetchall()

    cur.execute(
        """
        SELECT m.id, m.category, m.wrong, m.correct, m.note, m.topic_id, m.created_at, t.title
        FROM grammar_mistakes m
        LEFT JOIN grammar_topics t ON t.id = m.topic_id
        WHERE m.category LIKE ? OR m.wrong LIKE ? OR m.correct LIKE ? OR m.note LIKE ?
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (like, like, like, like, int(limit)),
    )
    mistake_rows = cur.fetchall()
    conn.close()

    topics: List[Dict[str, Any]] = []
    for r in topic_rows:
        ex_raw = r[3] or "[]"
        try:
            ex = json.loads(ex_raw)
            if not isinstance(ex, list):
                ex = []
        except Exception:
            ex = []
        topics.append(
            {
                "id": int(r[0]),
                "title": r[1] or "",
                "rule": r[2] or "",
                "examples": ex,
                "traps": r[4] or "",
                "tags": r[5] or "",
                "created_at": r[6] or "",
                "updated_at": r[7] or "",
            }
        )

    mistakes: List[Dict[str, Any]] = []
    for r in mistake_rows:
        mistakes.append(
            {
                "id": int(r[0]),
                "category": r[1] or "",
                "wrong": r[2] or "",
                "correct": r[3] or "",
                "note": r[4] or "",
                "topic_id": (int(r[5]) if r[5] is not None else None),
                "created_at": r[6] or "",
                "topic_title": r[7] or "",
            }
        )

    return {"topics": topics, "mistakes": mistakes}



# -------------------------
# Verb conjugation (Free Reverso + optional Ultralingua ULAPI)
# -------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def free_conjugations(verb: str, language: str = "fr") -> Dict[str, Any]:
    """Free conjugations provider.

    Preferred: mlconjug3 (offline, no key) — stable and fast once installed.
      pip install mlconjug3

    Fallback: Reverso-API (unofficial wrapper) — may break if upstream changes.
      pip install Reverso-API

    Returns a normalized dict:
      {
        "provider": "mlconjug3" | "reverso",
        "verb": "<input>",
        "conjugations": <nested dict or raw payload>
      }
    """
    v = (verb or "").strip()
    if not v:
        raise ValueError("Empty verb")

    # 1) Offline provider: mlconjug3
    if mlconjug3 is not None:
        conj = mlconjug3.Conjugator(language=language)
        vb = conj.conjugate(v)
        # vb.conjug_info is: mood -> tense -> person -> form
        return {
            "provider": "mlconjug3",
            "verb": v,
            "conjugations": getattr(vb, "conjug_info", None) or {},
        }

    # 2) Fallback: unofficial Reverso wrapper
    if ReversoAPI is not None:
        api = ReversoAPI()
        if hasattr(api, "get_conjugation"):
            payload = api.get_conjugation(v, language)
        elif hasattr(api, "conjugate"):
            payload = api.conjugate(v, language)
        else:
            raise RuntimeError("Your Reverso-API version does not expose get_conjugation/conjugate.")
        return {"provider": "reverso", "verb": v, "conjugations": payload}

    raise RuntimeError("No free conjugation provider is available. Install mlconjug3: pip install mlconjug3")




def _render_conjugations_any(payload: Any) -> None:
    """Render conjugations in a human UI (not raw JSON).

    Supports:
      - Normalized payload: {provider, verb, conjugations}
      - Conjugation maps shaped like: mood -> tense -> person -> form
        (mlconjug3 uses this structure; some Reverso payloads also resemble it)

    Falls back to st.json() only when the structure is not recognized.
    """
    if payload is None:
        st.info("No data returned.")
        return

    # Unwrap normalized payload
    provider = None
    verb = None
    conj = payload
    if isinstance(payload, dict) and set(payload.keys()) >= {"provider", "verb", "conjugations"}:
        provider = str(payload.get("provider") or "").strip()
        verb = str(payload.get("verb") or "").strip()
        conj = payload.get("conjugations")

        # Small header row
        cols = st.columns([0.22, 0.78])
        with cols[0]:
            st.markdown("**Verb**")
            st.markdown(f"`{verb}`" if verb else "—")
        with cols[1]:
            st.markdown("**Provider**")
            st.markdown(f"`{provider}`" if provider else "—")
        st.divider()

    def _is_scalar(x: Any) -> bool:
        return isinstance(x, (str, int, float, bool)) or x is None

    def _person_label(p: str) -> str:
        p = (p or "").strip()
        if not p:
            return ""
        # Common keys from various sources
        mapping = {
            "je": "je",
            "j'": "je",
            "tu": "tu",
            "il": "il / elle / on",
            "elle": "il / elle / on",
            "on": "il / elle / on",
            "il (elle, on)": "il / elle / on",
            "nous": "nous",
            "vous": "vous",
            "ils": "ils / elles",
            "elles": "ils / elles",
            "ils (elles)": "ils / elles",
            "1s": "je",
            "2s": "tu",
            "3s": "il / elle / on",
            "1p": "nous",
            "2p": "vous",
            "3p": "ils / elles",
            "firstsingular": "je",
            "secondsingular": "tu",
            "thirdsingular": "il / elle / on",
            "firstplural": "nous",
            "secondplural": "vous",
            "thirdplural": "ils / elles",
        }
        return mapping.get(p.lower(), p)

    def _person_sort_key(label: str) -> int:
        order = ["je", "tu", "il", "il / elle / on", "nous", "vous", "ils", "ils / elles"]
        lab = (label or "").strip().lower()
        for i, k in enumerate(order):
            if lab == k:
                return i
        # push unknown persons to bottom, but keep stable
        return 99

    def _render_tense_table(person_map: Dict[str, Any]) -> None:
        rows = []
        for p, form in (person_map or {}).items():
            if not _is_scalar(form):
                continue
            pl = _person_label(str(p))
            fv = "" if form is None else str(form).strip()
            if not fv:
                continue
            rows.append({"Person": pl, "Form": fv})
        if not rows:
            st.caption("No forms.")
            return
        rows.sort(key=lambda r: _person_sort_key(r["Person"]))
        st.dataframe(rows, use_container_width=True, hide_index=True)

    def _looks_like_mood_map(d: Dict[str, Any]) -> bool:
        # mood -> tense -> person -> form
        if not isinstance(d, dict) or not d:
            return False
        # pick a sample value
        sample = next(iter(d.values()))
        if not isinstance(sample, dict) or not sample:
            return False
        sample2 = next(iter(sample.values()))
        return isinstance(sample2, dict) and sample2 and all(_is_scalar(v) for v in sample2.values())

    # Primary UI path: mood -> (tense -> person -> form) OR mood -> (person -> form)
    if isinstance(conj, dict):
        # Detect a "mood map" even if some moods don't have tenses (e.g., Infinitif/Participe/Imperatif).
        MOOD_HINTS = {
            "indicatif","subjonctif","conditionnel","imperatif","impératif",
            "infinitif","participe","gérondif","gerondif"
        }
        keys_lc = {str(k).strip().lower() for k in conj.keys()}

        def _is_person_map(d: Any) -> bool:
            # person -> scalar form
            return isinstance(d, dict) and d and all(_is_scalar(v) for v in d.values())

        def _is_tense_map(d: Any) -> bool:
            # tense -> person_map
            if not isinstance(d, dict) or not d:
                return False
            sample = next(iter(d.values()))
            return _is_person_map(sample)

        looks_like_moods = bool(keys_lc & MOOD_HINTS)

        # Case A: clean mood -> tense -> person
        if _looks_like_mood_map(conj):
            for mood, tenses in conj.items():
                mood_title = str(mood).strip() or "Mood"
                with st.expander(mood_title, expanded=(mood_title.lower() in {"indicatif", "indicative"})):
                    if not isinstance(tenses, dict) or not tenses:
                        st.caption("No tenses.")
                        continue
                    tense_names = [str(k) for k in tenses.keys()]
                    if len(tense_names) <= 8:
                        tabs = st.tabs(tense_names)
                        for i, tn in enumerate(tense_names):
                            with tabs[i]:
                                person_map = tenses.get(tn, {})
                                if isinstance(person_map, dict):
                                    _render_tense_table(person_map)
                                else:
                                    st.json(person_map)
                    else:
                        for tn, person_map in tenses.items():
                            with st.expander(str(tn), expanded=False):
                                if isinstance(person_map, dict):
                                    _render_tense_table(person_map)
                                else:
                                    st.json(person_map)
            return

        # Case B: mixed moods: some moods are person-maps, others are tense-maps (mlconjug3 does this).
        if looks_like_moods and any(_is_tense_map(v) for v in conj.values()):
            for mood, blob in conj.items():
                mood_title = str(mood).strip() or "Mood"
                with st.expander(mood_title, expanded=(mood_title.lower() in {"indicatif", "indicative"})):
                    if _is_person_map(blob):
                        # No tenses for this mood → render directly
                        _render_tense_table(blob)
                        continue
                    if _is_tense_map(blob):
                        tenses = blob
                        tense_names = [str(k) for k in tenses.keys()]
                        if len(tense_names) <= 8:
                            tabs = st.tabs(tense_names)
                            for i, tn in enumerate(tense_names):
                                with tabs[i]:
                                    person_map = tenses.get(tn, {})
                                    if isinstance(person_map, dict):
                                        _render_tense_table(person_map)
                                    else:
                                        st.json(person_map)
                        else:
                            for tn, person_map in tenses.items():
                                with st.expander(str(tn), expanded=False):
                                    if isinstance(person_map, dict):
                                        _render_tense_table(person_map)
                                    else:
                                        st.json(person_map)
                        continue

                    # Unknown structure for this mood
                    st.json(blob)
            return
    # Secondary UI path: tense -> person -> form (no moods)
    if isinstance(conj, dict):
        # Guard: if this looks like a mood-map, don't misinterpret it as tenses.
        MOOD_HINTS = {
            "indicatif","subjonctif","conditionnel","imperatif","impératif",
            "infinitif","participe","gérondif","gerondif"
        }
        keys_lc = {str(k).strip().lower() for k in conj.keys()}
        if not (keys_lc & MOOD_HINTS):
            # if values are person maps
            sample = next(iter(conj.values())) if conj else None
            if isinstance(sample, dict) and sample and all(_is_scalar(v) for v in sample.values()):
                for tn, person_map in conj.items():
                    with st.expander(str(tn), expanded=False):
                        if isinstance(person_map, dict):
                            _render_tense_table(person_map)
                        else:
                            st.json(person_map)
                return

    # Fallback: keep raw but avoid rendering scalars with st.json
    if isinstance(conj, dict):
        st.json(conj)
    elif isinstance(conj, list):
        st.json(conj)
    else:
        st.write(conj)


# -------------------------
# Verb conjugation (Ultralingua ULAPI)
# -------------------------
_ULAPI_BASE = "https://api.ultralingua.com/api/2.0"

_PERSON_PRONOUN_FR = {
    "firstsingular": "je",
    "secondsingular": "tu",
    "thirdsingular": "il/elle",
    "firstplural": "nous",
    "secondplural": "vous",
    "thirdplural": "ils/elles",
    "secondsingularformal": "vous",
    "secondpluralformal": "vous",
    "first": "je/nous",
    "second": "tu/vous",
    "third": "il/elle/ils/elles",
}

def _ulapi_build_url(endpoint_path: str, api_key: str) -> str:
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("Missing Ultralingua API key. Add it in Grammar → Conjugator.")
    if endpoint_path.startswith("/"):
        endpoint_path = endpoint_path[1:]
    return f"{_ULAPI_BASE}/{endpoint_path}?key={api_key}"

@st.cache_data(show_spinner=False, ttl=3600)
def ulapi_conjugations(language: str, verb: str, api_key: str) -> Dict[str, Any]:
    """Fetch conjugations from Ultralingua ULAPI.
    Docs: https://ultralingua.com/ulapi-http-reference (endpoint /conjugations/<language>/<verb>?key=...)
    """
    language = (language or "fr").strip().lower()
    verb = (verb or "").strip()
    url = _ulapi_build_url(f"conjugations/{language}/{requests.utils.quote(verb)}", api_key)

    r = requests.get(url, timeout=20)
    if r.status_code == 401:
        raise ValueError("ULAPI: Not authorized (bad API key or free quota exhausted).")
    if r.status_code == 403:
        raise ValueError("ULAPI: Forbidden (your API key does not allow this dataset/language).")
    if r.status_code == 404:
        raise ValueError("ULAPI: Verb not found or endpoint missing.")
    if r.status_code != 200:
        raise ValueError(f"ULAPI error: HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    # ULAPI example response is a list with one object: [{infinitive:..., conjugations:[...]}]
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise ValueError("ULAPI: Unexpected response format.")

def ulapi_group_conjugations(conj_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group conjugations by tense id."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in (conj_list or []):
        pos = item.get("partofspeech") or {}
        tense = (pos.get("tense") or "").strip() or "unknown"
        grouped.setdefault(tense, []).append(item)
    return grouped



def grammar_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Grammar")

    topics = list_grammar_topics()
    topic_by_id = {t["id"]: t for t in topics}
    topic_options = ["(None)"] + [f'{t["title"]}  ·  #{t["id"]}' for t in topics]
    topic_ids = [None] + [t["id"] for t in topics]

    tabs = st.tabs(["📌 Topics", "🧯 My mistakes", "🔎 Search", "🔤 Conjugator"])

    # -------------------------
    # Topics tab
    # -------------------------
    with tabs[0]:
        left, right = st.columns([0.42, 0.58], gap="large")

        with left:
            st.caption("Your personal grammar playbooks: rules, examples, traps.")
            pick_label = st.selectbox("Select a topic", topic_options, index=0, key="gr_pick_topic")
            pick_idx = topic_options.index(pick_label) if pick_label in topic_options else 0
            pick_id = topic_ids[pick_idx]

            with st.expander("＋ New topic", expanded=False):
                title = st.text_input("Title", key="gr_new_title", placeholder="e.g., Passé composé vs imparfait")
                tags = st.text_input("Tags (comma separated)", key="gr_new_tags", placeholder="e.g., tense, past, narration")
                rule = st.text_area("Rule / explanation", key="gr_new_rule", height=140)
                ex1 = st.text_input("Example 1 (FR)", key="gr_new_ex1")
                ex2 = st.text_input("Example 2 (FR)", key="gr_new_ex2")
                ex3 = st.text_input("Example 3 (FR)", key="gr_new_ex3")
                traps = st.text_area("Common mistakes / traps", key="gr_new_traps", height=110)

                if st.button("Save topic", type="primary", use_container_width=True, key="gr_new_save"):
                    try:
                        create_grammar_topic(title, rule, [ex1, ex2, ex3], traps, tags=tags)
                        toast("Saved topic.", icon="📘")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        with right:
            if pick_id and pick_id in topic_by_id:
                t = topic_by_id[pick_id]
                st.markdown(f"### {t['title']}")
                st.caption(f"Updated: {t.get('updated_at','')}")

                # Editable form
                ex = t.get("examples") or []
                ex = (ex + ["", "", ""])[:3]

                with st.form(f"gr_edit_topic_{pick_id}", clear_on_submit=False):
                    title = st.text_input("Title", value=t.get("title",""), key=f"gr_e_title_{pick_id}")
                    tags = st.text_input("Tags (comma separated)", value=t.get("tags",""), key=f"gr_e_tags_{pick_id}")
                    rule = st.text_area("Rule / explanation", value=t.get("rule",""), height=160, key=f"gr_e_rule_{pick_id}")
                    ex1 = st.text_input("Example 1 (FR)", value=ex[0], key=f"gr_e_ex1_{pick_id}")
                    ex2 = st.text_input("Example 2 (FR)", value=ex[1], key=f"gr_e_ex2_{pick_id}")
                    ex3 = st.text_input("Example 3 (FR)", value=ex[2], key=f"gr_e_ex3_{pick_id}")
                    traps = st.text_area("Common mistakes / traps", value=t.get("traps",""), height=120, key=f"gr_e_traps_{pick_id}")

                    c1, c2 = st.columns([0.7, 0.3])
                    with c1:
                        saved = st.form_submit_button("Save changes", type="primary", use_container_width=True)
                    with c2:
                        # deletion is handled outside submit for clarity
                        st.write("")

                if saved:
                    try:
                        update_grammar_topic(pick_id, title, rule, [ex1, ex2, ex3], traps, tags=tags)
                        toast("Updated topic.", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

                danger = st.expander("Delete topic", expanded=False)
                with danger:
                    st.warning("This will delete the topic. Linked mistakes will keep but lose the topic link.")
                    if st.button("Delete this topic", use_container_width=True, key=f"gr_del_topic_{pick_id}"):
                        delete_grammar_topic(pick_id)
                        toast("Deleted topic.", icon="🗑️")
                        st.rerun()

                # Read-only preview blocks
                st.markdown("---")
                if t.get("rule"):
                    st.markdown("**Rule**")
                    st.write(t["rule"])
                if any((x or "").strip() for x in t.get("examples", [])):
                    st.markdown("**Examples**")
                    for i, x in enumerate(t.get("examples", [])[:10], start=1):
                        if (x or "").strip():
                            st.markdown(f"- {x}")
                if t.get("traps"):
                    st.markdown("**Common traps**")
                    st.write(t["traps"])
                if t.get("tags"):
                    st.markdown("**Tags**")
                    st.code(t["tags"])
            else:
                st.info("Pick a topic from the left, or create a new one.")

    # -------------------------
    # Mistakes tab
    # -------------------------
    with tabs[1]:
        st.caption("Log your recurring mistakes so they stop recurring.")
        cats = ["Articles/Gender", "Prepositions", "Tense", "Pronouns (en/y)", "Word order", "Agreement", "Other"]
        colA, colB = st.columns([0.6, 0.4], gap="large")

        with colA:
            category = st.selectbox("Category", cats, index=0, key="gr_m_cat")
            wrong = st.text_area("Wrong sentence", key="gr_m_wrong", height=90)
            correct = st.text_area("Correct sentence", key="gr_m_correct", height=90)
            note = st.text_input("Why was it wrong? (short)", key="gr_m_note", placeholder="e.g., 'depuis' uses present for ongoing actions")

        with colB:
            topic_pick = st.selectbox("Link to topic (optional)", topic_options, index=0, key="gr_m_topic")
            topic_idx = topic_options.index(topic_pick) if topic_pick in topic_options else 0
            linked_topic_id = topic_ids[topic_idx]

            if st.button("Save mistake", type="primary", use_container_width=True, key="gr_m_save"):
                try:
                    create_grammar_mistake(category, wrong, correct, note, topic_id=linked_topic_id)
                    toast("Saved mistake.", icon="🧯")
                    st.session_state.gr_m_wrong = ""
                    st.session_state.gr_m_correct = ""
                    st.session_state.gr_m_note = ""
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

        st.markdown("### Recent mistakes")
        mistakes = list_grammar_mistakes(limit=80)
        if not mistakes:
            st.info("No mistakes yet. Add one above.")
        else:
            for m in mistakes:
                with st.container(border=True):
                    top = f"**{m['category'] or 'Mistake'}** · {m.get('created_at','')}"
                    if m.get("topic_title"):
                        top += f" · linked: _{m['topic_title']}_"
                    st.markdown(top)
                    if m.get("wrong"):
                        st.markdown("**Wrong:**")
                        st.write(m["wrong"])
                    if m.get("correct"):
                        st.markdown("**Correct:**")
                        st.write(m["correct"])
                    if m.get("note"):
                        st.caption(m["note"])

                    if st.button("Delete", key=f"gr_del_m_{m['id']}", use_container_width=False):
                        delete_grammar_mistake(m["id"])
                        toast("Deleted mistake.", icon="🗑️")
                        st.rerun()

    # -------------------------
    # Search tab
    # -------------------------
    with tabs[2]:
        q = st.text_input("Search grammar", key="gr_search", placeholder="Type: subjonctif, depuis, y, en, passé composé…")
        res = search_grammar(q, limit=50) if q.strip() else {"topics": [], "mistakes": []}

        c1, c2 = st.columns(2, gap="large")

        with c1:
            st.markdown("### Topic matches")
            if not res["topics"]:
                st.caption("No topic matches.")
            else:
                for t in res["topics"]:
                    with st.container(border=True):
                        st.markdown(f"**{t['title']}**  ·  #{t['id']}")
                        if t.get("rule"):
                            st.write((t["rule"][:220] + "…") if len(t["rule"]) > 220 else t["rule"])
                        ex = [x for x in (t.get("examples") or []) if (x or "").strip()]
                        if ex:
                            st.caption("Examples: " + " · ".join(ex[:2]))

        with c2:
            st.markdown("### Mistake matches")
            if not res["mistakes"]:
                st.caption("No mistake matches.")
            else:
                for m in res["mistakes"]:
                    with st.container(border=True):
                        title = f"**{m['category'] or 'Mistake'}**  ·  #{m['id']}"
                        if m.get("topic_title"):
                            title += f"  ·  _{m['topic_title']}_"
                        st.markdown(title)
                        if m.get("wrong"):
                            st.write(m["wrong"])
                        if m.get("correct"):
                            st.caption("→ " + m["correct"])


    # -------------------------

    # -------------------------
    # Conjugator tab (Free Reverso + optional Ultralingua)
    # -------------------------
    with tabs[3]:
        st.caption("Conjugate French verbs. Default provider is free (Reverso, no key). Optionally use Ultralingua if you have a key.")
        provider = st.radio(
            "Provider",
            ["Free (Offline)", "Ultralingua (API key)"],
            index=0 if st.session_state.get("conj_provider", "Free (Offline)") == "Free (Offline)" else 1,
            horizontal=True,
            key="conj_provider",
        )

        verb = st.text_input("Verb (any form)", key="conj_verb", placeholder="e.g., parler / parlez / suis / allé")
        col1, col2 = st.columns([1, 1])
        with col1:
            show_raw = st.checkbox("Show raw JSON", value=False, key="conj_show_raw")
        with col2:
            st.write("")

        if provider == "Ultralingua (API key)":
            api_key = st.text_input(
                "Ultralingua API key",
                value=st.session_state.get("ulapi_key", ""),
                type="password",
                key="ulapi_key_input",
                help="Saved in Settings (SQLite).",
            )
            if api_key != st.session_state.get("ulapi_key", ""):
                st.session_state.ulapi_key = api_key
                set_setting("ulapi_key", api_key)

            group_mode = st.selectbox("Group by", ["tense", "tense + person"], index=0, key="ulapi_group_mode_v2")
            show_unknown = st.checkbox("Show 'unknown' forms", value=False, key="ulapi_show_unknown_v2")

            if st.button("Conjugate", type="primary", use_container_width=True, key="btn_conj_ulapi"):
                v = (verb or "").strip()
                if not v:
                    st.warning("Type a verb first.")
                else:
                    try:
                        with st.spinner("Fetching conjugations…"):
                            payload = ulapi_conjugations("fr", v, st.session_state.get("ulapi_key", ""))
                        infinitive = payload.get("infinitive") or ""
                        conj_list = payload.get("conjugations") or []
                        if infinitive:
                            st.markdown(f"### Infinitive: **{infinitive}**")
                        if show_raw:
                            st.json(payload)
                        if not conj_list:
                            st.info("No conjugations returned.")
                        else:
                            grouped = ulapi_group_conjugations(conj_list)
                            if not show_unknown:
                                grouped.pop("unknown", None)

                            for tense_id, items in grouped.items():
                                st.markdown(f"#### {tense_id}")
                                rows = []
                                for it in items:
                                    pos = it.get("partofspeech") or {}
                                    person = (pos.get("person") or "").strip()
                                    pron = _PERSON_PRONOUN_FR.get(person, person or "")
                                    sf = it.get("surfaceform") or ""
                                    rows.append(
                                        {
                                            "Pronoun/Person": (pron or "").strip(),
                                            "Person id": person,
                                            "Form": sf,
                                        }
                                    )
                                if rows:
                                    st.dataframe(rows, use_container_width=True, hide_index=True)

                    except Exception as e:
                        st.error(str(e))

        else:
            # Provider diagnostics
            free_ok = (mlconjug3 is not None) or (ReversoAPI is not None)
            if not free_ok:
                st.info("No free conjugation provider is available in *this* Python environment.")
                with st.expander("Show diagnostics / fix (recommended)", expanded=True):
                    st.write("**Streamlit is running with:**")
                    st.code(sys.executable)
                    st.write("**Try installing into that exact Python:**")
                    st.code(f"\"{sys.executable}\" -m pip install -U mlconjug3", language="bash")
                    st.caption("If you installed with a different `python` / `pip`, Streamlit won’t see it.")
                    if _MLCONJUG3_ERR:
                        st.write("**mlconjug3 status:**")
                        st.error(_MLCONJUG3_ERR)
                    if _REVERSO_ERR:
                        st.write("**Reverso-API status:**")
                        st.error(_REVERSO_ERR)
                    st.write("**sys.path (first 12 entries):**")
                    st.code("\\n".join(sys.path[:12]))
            else:
                if mlconjug3 is not None:
                    st.success("Free provider ready: **mlconjug3 (offline)**")
                elif ReversoAPI is not None:
                    st.warning("Free provider ready: **Reverso-API (online, unofficial)**")
            if st.button("Conjugate", type="primary", use_container_width=True, key="btn_conj_free"):
                v = (verb or "").strip()
                if not v:
                    st.warning("Type a verb first.")
                else:
                    try:
                        with st.spinner("Fetching conjugations…"):
                            payload = free_conjugations(v, "fr")
                        if show_raw:
                            st.json(payload)
                        else:
                            _render_conjugations_any(payload)
                    except Exception as e:
                        st.error(str(e))




def notebook_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Notebook")

    tabs = st.tabs(["📄 PDF reader", "📝 Notes from cards"])

    with tabs[0]:
        st.caption("Upload a PDF book, read it here, and save vocabulary as you go.")

        up = st.file_uploader("Upload a PDF", type=["pdf"], key="nb_pdf_uploader")
        if up is not None:
            data = up.read()
            if data:
                book_id = pdf_book_upsert(up.name, data)
                st.session_state.nb_pdf_book_id = book_id
                st.session_state.nb_pdf_page = 1
                toast(f"Saved PDF: {up.name}", icon="📄")

        books = pdf_books_list()
        if not books:
            st.info("No PDF uploaded yet. Upload one above.")
            return

        book_labels = [f"{b['name']}  ·  {b['uploaded_at'][:19]}" for b in books]
        id_by_label = {label: b["id"] for label, b in zip(book_labels, books)}
        cur_id = st.session_state.get("nb_pdf_book_id") or books[0]["id"]
        cur_idx = next((i for i, b in enumerate(books) if b["id"] == cur_id), 0)
        pick = st.selectbox("Library", book_labels, index=cur_idx, key="nb_pdf_pick")
        st.session_state.nb_pdf_book_id = int(id_by_label[pick])

        book = pdf_book_get(int(st.session_state.nb_pdf_book_id))
        if not book:
            st.warning("Could not load that PDF.")
            return

        # Default "Tags for cards" to the current PDF name (so it's easy to filter in Review/Cards).
        pdf_tag = pdf_name_to_tag(book.get("name", ""))
        if int(st.session_state.get("_nb_last_book_id", -1)) != int(book["id"]):
            st.session_state._nb_last_book_id = int(book["id"])
            cur_tag = (st.session_state.get("nb_vocab_tags", "") or "").strip()
            if (not cur_tag) or (cur_tag.lower() == "pdf"):
                st.session_state.nb_vocab_tags = pdf_tag
        else:
            # Same book: if user never edited tags (still empty/"pdf"), keep syncing it.
            cur_tag = (st.session_state.get("nb_vocab_tags", "") or "").strip()
            if (not cur_tag) or (cur_tag.lower() == "pdf"):
                st.session_state.nb_vocab_tags = pdf_tag


        # Helpers (callbacks) — keep Prev/Next reliable even with widgets on the same row
        def _nb_prev() -> None:
            st.session_state.nb_pdf_page = max(1, int(st.session_state.get("nb_pdf_page", 1)) - 1)

        def _nb_next() -> None:
            st.session_state.nb_pdf_page = int(st.session_state.get("nb_pdf_page", 1)) + 1

        # Controls row
        # NOTE: Remove +/- micro-buttons; keep only Prev/Next + direct page input + zoom dropdown.
        c1, c2, c3, c4, c5 = st.columns([0.95, 0.95, 1.35, 1.45, 1.05], gap="small")
        with c1:
            st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
            st.button("◀ Prev", use_container_width=True, on_click=_nb_prev)
        with c2:
            st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
            st.button("Next ▶", use_container_width=True, on_click=_nb_next)
        with c3:
            st.markdown("<div class='ctl-label'>Page</div>", unsafe_allow_html=True)
            st.number_input(
                "Page",
                min_value=1,
                step=1,
                key="nb_pdf_page",
                label_visibility="collapsed",
            )
        with c4:
            st.markdown("<div class='ctl-label'>Zoom</div>", unsafe_allow_html=True)
            zoom_opts = [80, 90, 100, 110, 125, 140, 160]
            curz = int(st.session_state.get("nb_pdf_zoom", 100))
            if curz not in zoom_opts:
                st.session_state.nb_pdf_zoom = 100
                curz = 100
            st.selectbox(
                "Zoom",
                zoom_opts,
                index=zoom_opts.index(int(st.session_state.get("nb_pdf_zoom", curz))),
                key="nb_pdf_zoom",
                label_visibility="collapsed",
            )
        with c5:
            st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
            if st.button("Delete PDF", use_container_width=True):
                pdf_book_delete(int(book["id"]))
                st.session_state.nb_pdf_book_id = None
                st.session_state.nb_pdf_extracted_text = ""
                st.session_state.nb_pdf_text_cache_page = None
                st.rerun()

        # Clamp page after any controls/callbacks
        page = max(1, int(st.session_state.get("nb_pdf_page", 1)))
        # NOTE: do NOT assign to st.session_state.nb_pdf_page here (it is bound to the number_input widget).
        zoom = int(st.session_state.get("nb_pdf_zoom", 100))

        use_native = st.toggle(
            "Selectable PDF view (copy directly from the PDF)",
            value=st.session_state.get("nb_pdf_use_native", True),
            key="nb_pdf_use_native",
            help="Shows the original PDF in your browser so you can highlight/copy text without extracting. Works only if the PDF has a text layer.",
        )

        if use_native:
            pdf_selectable_viewer(book["data"], page=page, zoom=zoom, height=820)
        else:
            png = render_pdf_page_png(book["data"], page, zoom)
            if png:
                st.image(png, use_container_width=True)
            else:
                st.warning("PNG preview needs PyMuPDF. Install it with: `pip install pymupdf`")

        st.markdown("### Selectable text (copy)")
        if fitz is None:
            st.caption("Install PyMuPDF to extract text: `pip install pymupdf`")
        else:
            if st.button("Extract text from this page", use_container_width=True):
                st.session_state.nb_pdf_text_cache_page = page
                st.session_state.nb_pdf_extracted_text = extract_pdf_page_text(book["data"], page)

            extracted = st.session_state.get("nb_pdf_extracted_text", "")
            if extracted and st.session_state.get("nb_pdf_text_cache_page") == page:
                st.text_area("Page text", value=extracted, height=220)
                st.download_button(
                    "Download extracted text (.txt)",
                    data=extracted.encode("utf-8"),
                    file_name=f"{book['name']}_page_{page}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

            # (Google Translate UI is rendered below, always visible)
            else:
                st.caption("Click the button to extract text from the current page (optional).")

        # === Google Translate (always available; independent of Extract Text) ===
        st.markdown("#### Google Translate")
        st.caption("Translate any word/phrase and auto-fill the Save Vocab form.")

        tcol1, tcol2, tcol3 = st.columns([1.45, 0.6, 0.95], gap="small")
        with tcol1:
            st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
            to_translate = st.text_input(
                "Text to translate",
                value=st.session_state.get("nb_translate_text", ""),
                key="nb_translate_text",
                placeholder="ex: pourtant / se rendre compte / une fois…",
                label_visibility="collapsed",
            )
        with tcol2:
            st.markdown("<div class='ctl-label'>Target</div>", unsafe_allow_html=True)
            tgt = st.selectbox(
                "Target",
                ["en", "de", "fr", "fa"],
                index=0,
                key="nb_translate_tgt",
                label_visibility="collapsed",
            )
        with tcol3:
            st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
            do_tr = st.button("Translate", key="nb_translate_btn", type="primary", use_container_width=True)

        if do_tr and to_translate.strip():
            translation = google_translate(to_translate, source_lang="fr", target_lang=tgt)
            st.session_state.nb_translate_last = (translation or "").strip()
            if translation:
                st.success(translation)

                # Auto-fill "Save vocab" inputs so the user can save/tag immediately.
                st.session_state["nb_vocab_word"] = to_translate.strip()
                st.session_state["nb_vocab_meaning"] = translation.strip()
                st.session_state["nb_vocab_page"] = int(page)
            else:
                st.info("Could not fetch an instant translation. Use the Google Translate link below.")

        if to_translate.strip():
            import urllib.parse as _urlparse
            q = _urlparse.quote(to_translate.strip())
            st.markdown(
                f"[Open in Google Translate ↗](https://translate.google.com/?sl=fr&tl={tgt}&text={q}&op=translate)",
                unsafe_allow_html=False,
            )


        st.markdown("#### Helper")
        st.caption("Generate synonyms (FR), translation (EN) and an example sentence (FR).")
        if str(st.session_state.get("ai_notes_enabled", "1")) not in ("1", "true", "True"):
            st.info("helper is disabled in Settings.")
        else:
            acol1, acol2 = st.columns([1.6, 0.7], gap="small")
            with acol1:
                st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
                ai_text = st.text_input(
                    "Word",
                    value=st.session_state.get("nb_ai_text", st.session_state.get("nb_translate_text", "")),
                    key="nb_ai_text",
                    placeholder="ex: pourtant / se rendre compte / une fois…",
                    label_visibility="collapsed",
                )
            with acol2:
                st.markdown("<div class='ctl-label'>&nbsp;</div>", unsafe_allow_html=True)
                do_ai = st.button("Assist", key="nb_ai_btn", use_container_width=True)

            # Show last Assist result (kept after reruns) so the user can still see what was filled.
            prev = st.session_state.get("nb_ai_preview", None)
            if isinstance(prev, dict) and (prev.get("tr_en") or prev.get("syns") or prev.get("ex_fr")):
                if prev.get("tr_en"):
                    st.success(prev.get("tr_en"))
                syns_prev = prev.get("syns") or []
                if syns_prev:
                    st.markdown("**Synonyms (FR)**")
                    st.write(", ".join(syns_prev))
                if prev.get("ex_fr"):
                    st.markdown("**Example (FR)**")
                    st.markdown(f"> _{prev.get('ex_fr')}_")

            if do_ai and ai_text.strip():
                with st.spinner("Looking it up…"):
                    tr_en, syns, ex_fr = ai_vocab_helper(ai_text.strip())

                    if not (tr_en or syns or ex_fr):
                        err = st.session_state.get("ai_last_error","").strip()
                        if err:
                            st.error("AI error: " + err)
                        else:
                            st.info("No AI result. Try again, or verify your model/key.")
                    else:
                        if tr_en:
                            st.success(tr_en)
                        if syns:
                            st.markdown("**Synonyms (FR)**")
                            st.write(", ".join(syns))
                        if ex_fr:
                            st.markdown("**Example (FR)**")
                            st.markdown(f"> _{ex_fr}_")

                        # Auto-fill the Save Vocab form so the user can save/tag immediately.
                        st.session_state["nb_vocab_word"] = ai_text.strip()
                        if tr_en:
                            st.session_state["nb_vocab_meaning"] = tr_en
                        st.session_state["nb_vocab_synonyms"] = ", ".join(syns) if syns else ""
                        st.session_state["nb_vocab_example"] = ex_fr or ""
                        st.session_state["nb_vocab_page"] = int(page)

                        # Persist the last Assist output so it stays visible after reruns.
                        st.session_state["nb_ai_preview"] = {"tr_en": tr_en, "syns": syns, "ex_fr": ex_fr}

                        # Force a rerun so the form fields reliably show the updated values.
                        st.rerun()

        st.markdown("---")
        st.markdown("### 📌 Save vocabulary from this PDF")
        with st.form("nb_vocab_form", clear_on_submit=True):
            colA, colB = st.columns([1.0, 1.2])
            with colA:
                word = st.text_input(
                    "Word / expression",
                    placeholder="ex: pourtant, se rendre compte…",
                    key="nb_vocab_word",
                    value=st.session_state.get("nb_vocab_word", ""),
                )
                meaning = st.text_input(
                    "Meaning (EN)",
                    placeholder="quick meaning…",
                    key="nb_vocab_meaning",
                    value=st.session_state.get("nb_vocab_meaning", ""),
                )
            with colB:
                context = st.text_area(
                    "Context / sentence (optional)",
                    height=90,
                    placeholder="Paste the sentence from the book…",
                    key="nb_vocab_context",
                    value=st.session_state.get("nb_vocab_context", ""),
                )
            synonyms = st.text_input(
                "Synonyms (FR) (optional)",
                placeholder="ex: cependant, pourtant, toutefois…",
                key="nb_vocab_synonyms",
                value=st.session_state.get("nb_vocab_synonyms", ""),
            )
            example_fr = st.text_area(
                "Example (FR) (optional)",
                height=90,
                placeholder="Write or generate a simple example sentence…",
                key="nb_vocab_example",
                value=st.session_state.get("nb_vocab_example", ""),
            )

            page_in = st.number_input(
                "Page (auto)",
                min_value=1,
                value=int(st.session_state.get("nb_vocab_page", page)),
                step=1,
                key="nb_vocab_page",
            )
            tags_for_cards = st.text_input("Tags for cards (optional)", value=st.session_state.get("nb_vocab_tags", "pdf"), key="nb_vocab_tags")
            save = st.form_submit_button("Save vocab", type="primary")
            if save:
                if not word.strip():
                    st.warning("Word is required.")
                else:
                    pdf_vocab_add(int(book["id"]), word, meaning, context, synonyms, example_fr, int(page_in))
                    toast("Saved vocab", icon="📌")

        st.markdown("### 📚 Saved vocabulary")
        q = st.text_input("Search vocab", value=st.session_state.get("nb_vocab_q", ""), key="nb_vocab_q")
        rows = pdf_vocab_list(int(book["id"]), q=q)
        if not rows:
            st.caption("No vocabulary saved yet for this PDF.")
        else:
            for r in rows[:200]:
                with st.container(border=True):
                    top = st.columns([1.6, 1.1, 0.8, 0.6])
                    with top[0]:
                        st.markdown(f"**{r.get('word','')}**")
                        if (r.get("meaning") or "").strip():
                            st.caption(r.get("meaning"))
                    with top[1]:
                        st.caption(f"p. {r.get('page') or '—'} • {str(r.get('created_at',''))[:19]}")
                    with top[2]:
                        if st.button("➕ Card", key=f"v2c_{r['id']}", use_container_width=True):
                            front = (r.get("word") or "").strip()
                            meaning = (r.get("meaning") or "").strip()
                            example = (r.get("example") or "").strip()
                            syn = (r.get("synonyms") or "").strip()
                            ctx = (r.get("context") or "").strip()

                            # Card "back" is the meaning, but we also append synonyms so they are searchable
                            # in Review/Cards even if the UI filter only looks at front/back.
                            back = (meaning or "—").strip()
                            if syn and ("Synonyms" not in back):
                                back = (back + "\n\nSynonyms (FR): " + syn).strip()

                            notes_parts = []
                            if syn:
                                notes_parts.append(f"Synonyms (FR): {syn}")
                            if ctx:
                                notes_parts.append(f"Context: {ctx}")
                            notes = "\n\n".join(notes_parts).strip()

                            cid = create_card("fr", front, back, norm_text(tags_for_cards), example, notes)
                            bump_xp(1)
                            toast(f"Created card #{cid}. +1 🥕", icon="🥕")
                    with top[3]:
                        if st.button("🗑️", key=f"vdel_{r['id']}", use_container_width=True):
                            pdf_vocab_delete(int(r["id"]))
                            st.rerun()

                    if (r.get("synonyms") or "").strip():
                        st.markdown("**Synonyms (FR)**")
                        st.write(r.get("synonyms"))
                    if (r.get("example") or "").strip():
                        st.markdown("**Example (FR)**")
                        st.markdown(f"> _{r.get('example')}_")
                    if (r.get("context") or "").strip():
                        st.markdown("**Context**")
                        st.write(r.get("context"))

    with tabs[1]:
        st.caption("A clean view of saved examples + notes from your flashcards.")
        q = st.text_input("Search notebook", placeholder="type anything…", key="nb_search")
        only_with_notes = st.checkbox("Only show items that have example/notes", value=True)

        cards = fetch_cards(q)
        shown = 0
        for c in cards[:500]:
            has_any = bool((c.get("example") or "").strip() or (c.get("notes") or "").strip())
            if only_with_notes and not has_any:
                continue
            shown += 1
            with st.container(border=True):
                st.markdown(f"**{c['front']}**")
                st.caption(f"#{c['id']} • tags: {c.get('tags','')} • due: {c.get('due_date','—')}")
                cols = st.columns(2)
                with cols[0]:
                    if c.get("example"):
                        st.markdown("**Example**")
                        st.markdown(f"> _{c['example']}_")
                with cols[1]:
                    if c.get("notes"):
                        st.markdown("**Notes**")
                        st.write(c["notes"])
                if st.button("Open", key=f"nb_open_{c['id']}"):
                    select_card(int(c["id"]))
                    st.session_state.nav_pending = "Cards"
                    st.rerun()

        if shown == 0:
            st.info("No notebook entries matched your filters.")

def import_export_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Import / Export (CSV)")
    st.caption("CSV columns: language, front, back, tags, example, notes")

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("### Export")
        cards = fetch_cards()
        if st.button("Generate CSV export", type="primary", use_container_width=True):
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["language", "front", "back", "tags", "example", "notes"])
            for c in cards:
                w.writerow([c.get("language", "fr"), c["front"], c["back"], c.get("tags", ""), c.get("example", ""), c.get("notes", "")])
            st.download_button(
                "Download CSV",
                data=out.getvalue().encode("utf-8"),
                file_name="charlot_cards.csv",
                mime="text/csv",
                use_container_width=True,
            )

    with col2:
        st.markdown("### Import")
        up = st.file_uploader("Upload CSV", type=["csv"])
        if up is not None:
            try:
                content = up.read().decode("utf-8")
                r = csv.DictReader(io.StringIO(content))
                rows = list(r)
                st.write(f"Rows detected: {len(rows)}")
                if st.button("Import now", type="primary", use_container_width=True):
                    created = 0
                    for row in rows:
                        language = norm_text(row.get("language") or "fr") or "fr"
                        front = norm_text(row.get("front") or "")
                        back = norm_text(row.get("back") or "")
                        if not front or not back:
                            continue
                        tags = norm_text(row.get("tags") or "")
                        example = norm_text(row.get("example") or "")
                        notes = norm_text(row.get("notes") or "")
                        create_card(language, front, back, tags, example, notes)
                        created += 1
                    bump_xp(min(80, created))
                    toast(f"Imported {created} cards. (+XP)", icon="📥")
                    st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

def settings_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## Settings")

    st.markdown("### Appearance")
    theme_pick = st.selectbox("Theme", ["Light", "Dark"], index=0 if st.session_state.get("theme") == "Light" else 1)
    if theme_pick != st.session_state.get("theme"):
        st.session_state.theme = theme_pick
        st.rerun()


    # st.markdown("---")
    # st.markdown("### AI (optional)")
    # st.caption("Used only for the Notes → AI helper. Your key is stored locally in the app settings DB.")
    # k = st.text_input(
    #     "OpenAI API key",
    #     value=st.session_state.get("openai_api_key", ""),
    #     type="password",
    #     placeholder="sk-…",
    # )
    # m = st.text_input(
    #     "OpenAI model",
    #     value=st.session_state.get("openai_model", "gpt-5.2"),
    #     help="Example: gpt-5.2",
    # )
    # enabled = st.toggle(
    #     "Enable AI helper in Notes",
    #     value=str(st.session_state.get("ai_notes_enabled", "1")) in ("1", "true", "True"),
    # )
    # if st.button("Save AI settings", use_container_width=True):
    #     st.session_state.openai_api_key = k.strip()
    #     st.session_state.openai_model = m.strip() or "gpt-5.2"
    #     st.session_state.ai_notes_enabled = "1" if enabled else "0"
    #     set_setting("openai_api_key", st.session_state.openai_api_key)
    #     set_setting("openai_model", st.session_state.openai_model)
    #     set_setting("ai_notes_enabled", st.session_state.ai_notes_enabled)
    #     toast("Saved AI settings.", icon="🤖")

    st.markdown("---")
    st.markdown("### Database")
    st.write(f"DB file: `{DB_PATH}`")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("Initialize DB", use_container_width=True):
            init_db()
            toast("Initialized.", icon="🗄️")
    with c2:
        if st.button("Clear Streamlit cache", use_container_width=True):
            st.cache_data.clear()
            toast("Cache cleared.", icon="🧹")
    with c3:
        st.info("Tip: DB is local. If you deploy, use persistent storage (volume / cloud DB).")

    st.markdown("---")
    st.markdown("### Integrations")
    st.caption("Optional: provide an Ultralingua ULAPI key if you want a paid/stable conjugation source. The free Reverso conjugator does not need a key.")
    ul_key = st.text_input("Ultralingua API key (optional)", value=st.session_state.get("ulapi_key",""), type="password", key="settings_ulapi_key")
    if ul_key != st.session_state.get("ulapi_key",""):
        st.session_state.ulapi_key = ul_key
        set_setting("ulapi_key", ul_key)
        toast("Saved Ultralingua key.", icon="🔑")

    st.markdown("---")
    st.markdown("### Gamification")
    c4, c5 = st.columns(2)
    with c4:
        if st.button("Reset XP / streak", use_container_width=True):
            st.session_state.xp = 0
            st.session_state.streak = 1
            st.session_state.last_xp_date = iso_date(today_utc_date())
            try:
                set_user_state(0, 1, st.session_state.last_xp_date)
            except Exception:
                pass
            toast("Reset.", icon="♻️")
            st.rerun()
    with c5:
        lvl, _, _ = level_from_xp(int(st.session_state.get("xp", 0)))
        st.markdown(
            f"{chip('🏅','Level', str(lvl))} {chip('🥕','Carrots', str(int(st.session_state.get('xp',0) or 0)))} {chip('🥐','Croissants', str(int(st.session_state.get('xp',0) or 0)//10))} {chip('🚬','Cigarettes', str(int(st.session_state.get('xp',0) or 0)//50))}",
            unsafe_allow_html=True,
        )



    st.markdown("---")
    st.markdown("### Account")
    st.write(f"Logged in as **{st.session_state.get('username','')}** (user_id={int(current_user_id() or 0)})")
    change_password_section_ui()

    logout_button()

    if bool(st.session_state.get("is_admin")):
        st.markdown("---")
        st.markdown("### Admin: Create user")
        with st.form("admin_create_user"):
            nu = st.text_input("New username").strip().lower()
            np = st.text_input("New password", type="password")
            is_ad = st.checkbox("Admin user", value=False)
            ok = st.form_submit_button("Create user")
        if ok:
            try:
                create_user(nu, np, is_admin=is_ad)
                st.success("User created.")
            except Exception as e:
                st.error(str(e))

def about_page() -> None:
    st.markdown('<div class="page">', unsafe_allow_html=True)
    st.markdown("## About")

    st.markdown(
        """
<div class="card">
  <div class="h-title">Charlot</div>
  <div class="h-sub">A lightweight French study hub: dictionary → flashcards → spaced repetition.</div>
  <hr/>
  <div class="small" style="margin-bottom:10px;">
    • Dictionary: Wiktionary + DictionaryAPI fallbacks<br/>
    • Flashcards: local SQLite storage<br/>
    • Review: SM‑2 scheduling (spaced repetition)<br/>
    • Gamification: 🥕 carrots (XP), 🥐 croissants (levels), 🔥 streak
  </div>
  <div class="small">Tip: keep cards short, add an example sentence, and review daily.</div>
</div>
""",
        unsafe_allow_html=True,
    )

# =========================
# Main
# =========================
def main() -> None:
    init_db()
    init_session_state()

    # # Require authentication before reading/writing per-user data.
    # if not current_user_id():
    #     login_screen()
    #     return

    sync_session_from_db()
    reconcile_carrots_with_cards()

    inject_global_css(st.session_state.get("theme", "Dark"))
    bp = detect_breakpoint(760)

    app_header(bp)
    nav = top_nav(bp)

    if nav == "Home":
        home_page()
    elif nav == "Dictionary":
        dictionary_page()
    elif nav == "Review":
        review_page()
    elif nav == "Cards":
        manage_cards_page()
    elif nav == "Notes":
        notebook_page()
    elif nav == "Grammar":
        grammar_page()
    elif nav == "Import/Export":
        import_export_page()
    elif nav == "Settings":
        settings_page()
    elif nav == "About":
        about_page()
    else:
        home_page()
if __name__ == "__main__":
    main()