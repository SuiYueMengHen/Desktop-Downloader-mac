"""
Unified theme-aware styling system.

All text colors in the app should go through this module.
Uses qfluentwidgets' setCustomStyleSheet internally, which
auto-switches between light/dark stylesheets on theme change.

Usage:
    from app.theme import apply_style

    # Themed text color
    apply_style(label, "font-size: 14px;", "muted")

    # Semantic status color (auto theme-aware)
    apply_style(label, "font-size: 12px;", ("#e74c3c", "#ff6b6b"))
    apply_style(label, "font-size: 12px;", "error")

    # No color — just base stylesheet (not theme-dependent)
    apply_style(label, "font-size: 14px; font-weight: 600;")
"""

from qfluentwidgets import setCustomStyleSheet


# ═══════════════════════════════════════════
# Color palette — single source of truth
# ═══════════════════════════════════════════

_COLORS: dict[str, dict[str, str]] = {
    # Text tones (used for secondary/muted/normal labels)
    "muted":       {"light": "#888888", "dark": "#999999"},
    "secondary":   {"light": "#999999", "dark": "#aaaaaa"},
    "normal":      {"light": "#555555", "dark": "#cccccc"},
    "body":        {"light": "#333333", "dark": "#dddddd"},
    # Semantic status colors
    "error":       {"light": "#e74c3c", "dark": "#ff6b6b"},
    "success":     {"light": "#27ae60", "dark": "#2ecc71"},
    "warning":     {"light": "#e67e22", "dark": "#f39c12"},
    "info":        {"light": "#3498db", "dark": "#5dade2"},
    "special":     {"light": "#9b59b6", "dark": "#af7ac5"},
    # Decorators
    "separator":   {"light": "#dddddd", "dark": "#555555"},
}


def _resolve_color(color):
    """Resolve a color specification to (light, dark) tuple."""
    if color is None:
        return None
    if isinstance(color, str):
        entry = _COLORS.get(color)
        if entry:
            return entry["light"], entry["dark"]
        return None  # unknown name
    if isinstance(color, (list, tuple)) and len(color) == 2:
        return color[0], color[1]
    return None


# Legacy helpers — still exported for backward compat with remaining uses.
# New code should use apply_style() instead.
def theme_color(light: str, dark: str) -> str:
    from qfluentwidgets import isDarkTheme
    return dark if isDarkTheme() else light


def muted_text_color() -> str:
    return theme_color("#888", "#999")


def secondary_text_color() -> str:
    return theme_color("#999", "#aaa")


def normal_text_color() -> str:
    return theme_color("#555", "#ccc")


# ═══════════════════════════════════════════
# Unified theme-aware stylesheet application
# ═══════════════════════════════════════════

def apply_style(widget, base_qss: str = "", color=None):
    """Apply a stylesheet that auto-adapts when the theme changes.

    Args:
        widget: The QWidget to style.
        base_qss: Base stylesheet WITHOUT a ``color`` property
                  (e.g. ``"font-size: 14px;"``).  May be empty.
        color:   One of:
                  - A string key from the palette (``"muted"``, ``"error"``, …)
                  - A ``(light_color, dark_color)`` tuple
                  - ``None`` (no color property — just apply base_qss verbatim)

    If *color* is provided, it is injected as a ``color`` declaration
    via ``setCustomStyleSheet``, which automatically flips between the
    light and dark value when the user switches theme.
    """
    pair = _resolve_color(color)
    if pair is None:
        # No themed color → plain stylesheet (static, applied once)
        if base_qss:
            widget.setStyleSheet(base_qss)
        return

    light_color, dark_color = pair
    light_qss = f"{base_qss} color: {light_color};" if base_qss else f"color: {light_color};"
    dark_qss = f"{base_qss} color: {dark_color};" if base_qss else f"color: {dark_color};"

    if light_qss != dark_qss:
        setCustomStyleSheet(widget, light_qss, dark_qss)
    elif light_qss:
        widget.setStyleSheet(light_qss)
