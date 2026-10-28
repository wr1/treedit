"""The theme menu, the early-paint choice, the CSS and setTheme's list stay in step."""

import re
from importlib import resources


def test_every_theme_is_offered_painted_and_accepted():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    select = re.search(r'<select id="theme">(.*?)</select>', src, re.S)
    options = re.findall(r'<option value="([a-z-]+)"', select.group(1))
    listed = re.findall(r"'([a-z-]+)'", re.search(r"const THEMES = \[(.*?)\];", src).group(1))
    painted = set(re.findall(r'html\[data-theme="([a-z-]+)"\]\{', src))
    early = re.search(r"dataset\.theme = \{(.*?)\}\[themeChoice\]", src).group(1)
    keys = set(re.findall(r"'?([a-z-]+)'?: 1", early))
    assert options == listed
    assert painted == set(options)
    assert keys == set(options) - {"system"}
    assert "github-dark" in options
