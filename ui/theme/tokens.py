from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------
# Each theme maps token names to hex colour strings or rgba() values.
# The keys must match exactly the attributes set on class C below.

THEMES: dict[str, dict[str, str]] = {
    'default': {
        'BG_DEEP':           '#09090C',
        'BG_BASE':           '#0F0F14',
        'BG_LAYER':          '#141418',
        'BG_RAISED':         '#1C1C22',
        'BG_FLOAT':          '#222228',
        'BG_HOVER':          '#2A2A33',
        'BG_PRESS':          '#32323E',
        'TEXT_PRIMARY':      '#E0E0E0',
        'TEXT_SECONDARY':    '#999999',
        'TEXT_MUTED':        '#666666',
        'ACCENT':            '#4A90D9',
        'ACCENT_HOVER':      '#5DA0E9',
        'ACCENT_PRESS':      '#3A80C9',
        'BORDER':            '#3A3A3A',
        'DANGER':            '#FF6B35',
        'SUCCESS':           '#2E7D32',
        'INPUT_BG':          '#222222',
        'INPUT_BORDER':      '#3A3A3A',
        'INPUT_PLACEHOLDER': 'rgba(224,224,224,0.4)',
        'CHECK_ACCENT':      '#3A5A8C',
        'TEXT_ON_ACCENT':    '#FFFFFF',
        'AVATAR_BG':         '#4A5568',
        'AVATAR_FG':         '#A0AEC0',
        'DIALOG_BG':         '#1A1A1A',
        'CARD_BG':           '#222222',
        'VERIFY_GREEN':      '#2E7D32',
        'VERIFY_GREEN_HOVER': '#388E3C',
        'DANGER_RED_BG':     '#2D1A1A',
        'DANGER_RED_BORDER': '#552222',
        'ACCENT_BLUE':       '#4A90D9',
        'ACCENT_BLUE_BG':    '#1A3A5C',
        'ACCENT_BLUE_BORDER':'#2A5A8C',
    },

    # ── Biophilic ── natural, earthy greens / sand / stone ──────────────
    'biophilic': {
        'BG_DEEP':           '#0D1A0E',
        'BG_BASE':           '#142016',
        'BG_LAYER':          '#1A2B1C',
        'BG_RAISED':         '#243326',
        'BG_FLOAT':          '#2D3D2E',
        'BG_HOVER':          '#3A4D3A',
        'BG_PRESS':          '#4A5D48',
        'TEXT_PRIMARY':      '#E8E4D9',
        'TEXT_SECONDARY':    '#A8A088',
        'TEXT_MUTED':        '#7A7260',
        'ACCENT':            '#6ABF69',
        'ACCENT_HOVER':     '#7DD07C',
        'ACCENT_PRESS':      '#5AA858',
        'BORDER':            '#4A5548',
        'DANGER':            '#D4654A',
        'SUCCESS':           '#4CAF50',
        'INPUT_BG':          '#1A2B1C',
        'INPUT_BORDER':      '#4A5548',
        'INPUT_PLACEHOLDER': 'rgba(232,228,217,0.4)',
        'CHECK_ACCENT':      '#3D6B3D',
        'TEXT_ON_ACCENT':    '#FFFFFF',
        'AVATAR_BG':         '#5A6B4A',
        'AVATAR_FG':         '#B8C4A0',
        'DIALOG_BG':         '#1A2B1C',
        'CARD_BG':           '#243326',
        'VERIFY_GREEN':      '#4CAF50',
        'VERIFY_GREEN_HOVER':'#66BB6A',
        'DANGER_RED_BG':     '#3A2218',
        'DANGER_RED_BORDER': '#5A3322',
        'ACCENT_BLUE':       '#6ABF69',
        'ACCENT_BLUE_BG':    '#1A3A2A',
        'ACCENT_BLUE_BORDER':'#2A5A3A',
    },

    # ── Frutiger Aero ── 2000s utopian tech, sky blue / white / green ──
    'frutiger_aero': {
        'BG_DEEP':           '#C8DEF0',
        'BG_BASE':           '#E0EEF8',
        'BG_LAYER':          '#E8F2FA',
        'BG_RAISED':         '#FFFFFF',
        'BG_FLOAT':          '#F5FAFF',
        'BG_HOVER':          '#C8DEF0',
        'BG_PRESS':          '#B0CCE8',
        'TEXT_PRIMARY':      '#1A3A5C',
        'TEXT_SECONDARY':    '#3A6585',
        'TEXT_MUTED':        '#6A8CA8',
        'ACCENT':            '#0088CC',
        'ACCENT_HOVER':     '#009AE8',
        'ACCENT_PRESS':      '#007AB8',
        'BORDER':            '#A0C0D8',
        'DANGER':            '#D03030',
        'SUCCESS':           '#2E8B57',
        'INPUT_BG':          '#FFFFFF',
        'INPUT_BORDER':      '#A0C0D8',
        'INPUT_PLACEHOLDER': 'rgba(26,58,92,0.4)',
        'CHECK_ACCENT':      '#0088CC',
        'TEXT_ON_ACCENT':    '#FFFFFF',
        'AVATAR_BG':         '#B8D4E8',
        'AVATAR_FG':         '#3A6585',
        'DIALOG_BG':         '#E8F2FA',
        'CARD_BG':           '#FFFFFF',
        'VERIFY_GREEN':      '#2E8B57',
        'VERIFY_GREEN_HOVER':'#3DA06A',
        'DANGER_RED_BG':      '#FDE0E0',
        'DANGER_RED_BORDER': '#E8A0A0',
        'ACCENT_BLUE':       '#0088CC',
        'ACCENT_BLUE_BG':    '#D0E8F8',
        'ACCENT_BLUE_BORDER':'#80B8D8',
    },

    # ── DORFic ── industrial minimalist, stark white/black + orange ────
    'dorfic': {
        'BG_DEEP':           '#000000',
        'BG_BASE':           '#0A0A0A',
        'BG_LAYER':          '#111111',
        'BG_RAISED':         '#1A1A1A',
        'BG_FLOAT':          '#222222',
        'BG_HOVER':          '#2A2A2A',
        'BG_PRESS':          '#333333',
        'TEXT_PRIMARY':      '#FFFFFF',
        'TEXT_SECONDARY':    '#AAAAAA',
        'TEXT_MUTED':        '#666666',
        'ACCENT':            '#FF6600',
        'ACCENT_HOVER':     '#FF7722',
        'ACCENT_PRESS':      '#E85500',
        'BORDER':            '#333333',
        'DANGER':            '#FF3333',
        'SUCCESS':           '#00CC66',
        'INPUT_BG':          '#111111',
        'INPUT_BORDER':      '#333333',
        'INPUT_PLACEHOLDER': 'rgba(255,255,255,0.4)',
        'CHECK_ACCENT':      '#CC5200',
        'TEXT_ON_ACCENT':    '#000000',
        'AVATAR_BG':         '#333333',
        'AVATAR_FG':         '#CCCCCC',
        'DIALOG_BG':         '#0A0A0A',
        'CARD_BG':           '#1A1A1A',
        'VERIFY_GREEN':      '#00CC66',
        'VERIFY_GREEN_HOVER':'#00E67A',
        'DANGER_RED_BG':     '#1A0A0A',
        'DANGER_RED_BORDER': '#3A1515',
        'ACCENT_BLUE':       '#FF6600',
        'ACCENT_BLUE_BG':    '#2A1500',
        'ACCENT_BLUE_BORDER':'#4A2800',
    },

    # ── Indigo Citrus ── deep midnight indigo + electric orange ────────
    'indigo_citrus': {
        'BG_DEEP':           '#0A0A2E',
        'BG_BASE':           '#10103A',
        'BG_LAYER':          '#16164A',
        'BG_RAISED':         '#1E1E58',
        'BG_FLOAT':          '#282868',
        'BG_HOVER':          '#32327A',
        'BG_PRESS':          '#3E3E8C',
        'TEXT_PRIMARY':      '#E8E0F8',
        'TEXT_SECONDARY':    '#A898D0',
        'TEXT_MUTED':        '#7060A0',
        'ACCENT':            '#FF7A2E',
        'ACCENT_HOVER':     '#FF9048',
        'ACCENT_PRESS':      '#E06820',
        'BORDER':            '#3A3A6A',
        'DANGER':            '#FF4444',
        'SUCCESS':           '#40C870',
        'INPUT_BG':          '#16164A',
        'INPUT_BORDER':      '#3A3A6A',
        'INPUT_PLACEHOLDER': 'rgba(232,224,248,0.4)',
        'CHECK_ACCENT':      '#6A4AAA',
        'TEXT_ON_ACCENT':    '#FFFFFF',
        'AVATAR_BG':         '#4A3A78',
        'AVATAR_FG':         '#B8A0D8',
        'DIALOG_BG':         '#10103A',
        'CARD_BG':           '#1E1E58',
        'VERIFY_GREEN':      '#40C870',
        'VERIFY_GREEN_HOVER':'#58DC88',
        'DANGER_RED_BG':     '#2A1428',
        'DANGER_RED_BORDER': '#4A2040',
        'ACCENT_BLUE':       '#FF7A2E',
        'ACCENT_BLUE_BG':    '#3A1A08',
        'ACCENT_BLUE_BORDER':'#5A3020',
    },

    # ── Y2K Futurism ── maximalist, hot pink / lime / cyber blue ──────
    'y2k_futurism': {
        'BG_DEEP':           '#0D0020',
        'BG_BASE':           '#140030',
        'BG_LAYER':          '#1C0048',
        'BG_RAISED':         '#280060',
        'BG_FLOAT':          '#340070',
        'BG_HOVER':          '#420088',
        'BG_PRESS':          '#5000A0',
        'TEXT_PRIMARY':      '#F0E0FF',
        'TEXT_SECONDARY':    '#D0A0E8',
        'TEXT_MUTED':        '#A060C0',
        'ACCENT':            '#FF2D95',
        'ACCENT_HOVER':     '#FF4DAF',
        'ACCENT_PRESS':      '#E01A80',
        'BORDER':            '#5000A0',
        'DANGER':            '#FF3333',
        'SUCCESS':           '#80FF00',
        'INPUT_BG':          '#1C0048',
        'INPUT_BORDER':      '#5000A0',
        'INPUT_PLACEHOLDER': 'rgba(240,224,255,0.4)',
        'CHECK_ACCENT':      '#9A00E0',
        'TEXT_ON_ACCENT':    '#FFFFFF',
        'AVATAR_BG':         '#5000A0',
        'AVATAR_FG':         '#D0A0E8',
        'DIALOG_BG':         '#140030',
        'CARD_BG':           '#280060',
        'VERIFY_GREEN':      '#80FF00',
        'VERIFY_GREEN_HOVER':'#99FF33',
        'DANGER_RED_BG':     '#300018',
        'DANGER_RED_BORDER': '#500028',
        'ACCENT_BLUE':       '#00D4FF',
        'ACCENT_BLUE_BG':    '#001830',
        'ACCENT_BLUE_BORDER':'#002850',
    },
}

THEME_NAMES: dict[str, str] = {
    'default':        'Default',
    'biophilic':      'Biophilic',
    'frutiger_aero':  'Frutiger Aero',
    'dorfic':         'DORFic',
    'indigo_citrus':  'Indigo Citrus',
    'y2k_futurism':   'Y2K Futurism',
}


class _ThemeManager(QObject):
    """Manages the active theme and notifies listeners on change."""

    theme_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._current: str = 'default'

    def apply(self, name: str) -> None:
        """Swap all C.* class attributes to the named theme."""
        if name not in THEMES:
            name = 'default'
        self._current = name
        for key, value in THEMES[name].items():
            setattr(C, key, value)
        self.theme_changed.emit()

    @property
    def current(self) -> str:
        return self._current


class C:
    """Colour tokens — values change with the active theme."""
    pass


class M:
    """Motion / animation timing — constant across all themes."""
    CARD_STAGGER_MS = 22
    CARD_HOVER_MS = 150
    PRESS_SCALE = 0.97
    HOVER_LIFT = 3


# Singleton theme manager — initialise C with default values
theme_manager = _ThemeManager()
theme_manager.apply('default')