#!/usr/bin/env python3
"""
################################################################################
# Website — Static-site analysis, audit, serve, and build tool
#
# USAGE EXAMPLES
# --------------
#   # Analyse a website directory and print a full report
#   python Website.py analyze ./
#
#   # Run a full SEO / accessibility audit (dry-run preview)
#   python Website.py audit ./ --dry-run
#
#   # Start a local development server on port 8080
#   python Website.py serve ./ --port 8080
#
#   # Build (minify) assets — preview without writing files
#   python Website.py build ./ --dry-run
#
#   # Generate a single-file HTML report
#   python Website.py report ./ --output report.html
#
#   # Use a custom config file
#   python Website.py analyze ./ --config website.yaml
#
# DEPENDENCIES (pip install)
# --------------------------
#   pip install pyyaml tomllib-shim Pygments
#   # tomllib is built-in for Python >= 3.11
#   # All other dependencies are from the standard library.
#
################################################################################
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import http.server
import json
import logging
import mimetypes
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Optional third-party imports — gracefully degraded if not installed
# ---------------------------------------------------------------------------
try:
    import yaml  # pip install pyyaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

try:
    import tomllib  # built-in Python >= 3.11
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli  (fallback for < 3.11)

        _TOML_AVAILABLE = True
    except ImportError:
        tomllib = None  # type: ignore[assignment]
        _TOML_AVAILABLE = False
else:
    _TOML_AVAILABLE = True

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FMT = "%Y-%m-%dT%H:%M:%S"

logging.basicConfig(format=LOG_FORMAT, datefmt=LOG_DATE_FMT, stream=sys.stderr)
logger = logging.getLogger("website")


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_GENERAL_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_IO_ERROR = 3
EXIT_VALIDATION_FAILED = 4


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """Represents a single audit finding."""

    severity: str  # "error" | "warning" | "info"
    category: str
    message: str
    file: str = ""
    line: int = 0

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.file else ""
        prefix = f"[{loc}] " if loc else ""
        return f"{self.severity.upper():8s}  {self.category:20s}  {prefix}{self.message}"


@dataclass
class AssetInfo:
    """Metadata about a single static asset file."""

    path: Path
    size_bytes: int
    mime_type: str
    checksum: str
    last_modified: datetime


@dataclass
class HtmlReport:
    """Aggregated results of a full HTML-file parse."""

    path: Path
    title: str = ""
    lang: str = ""
    charset: str = ""
    viewport: str = ""
    description: str = ""
    links: List[str] = field(default_factory=list)
    scripts: List[str] = field(default_factory=list)
    stylesheets: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    headings: Dict[str, int] = field(default_factory=dict)
    forms: int = 0
    issues: List[Issue] = field(default_factory=list)


@dataclass
class SiteReport:
    """Top-level container for all analysis results."""

    root: Path
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    html_reports: List[HtmlReport] = field(default_factory=list)
    assets: List[AssetInfo] = field(default_factory=list)
    css_issues: List[Issue] = field(default_factory=list)
    js_issues: List[Issue] = field(default_factory=list)
    global_issues: List[Issue] = field(default_factory=list)

    # Aggregated stats
    @property
    def total_size_bytes(self) -> int:
        """Sum of all asset file sizes."""
        return sum(a.size_bytes for a in self.assets)

    @property
    def all_issues(self) -> List[Issue]:
        """Flat list of every issue across all sub-reports."""
        issues: List[Issue] = list(self.global_issues) + list(self.css_issues) + list(self.js_issues)
        for hr in self.html_reports:
            issues.extend(hr.issues)
        return issues

    @property
    def error_count(self) -> int:
        """Count of issues with severity == 'error'."""
        return sum(1 for i in self.all_issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        """Count of issues with severity == 'warning'."""
        return sum(1 for i in self.all_issues if i.severity == "warning")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
    },
    "build": {
        "output_dir": "dist",
        "minify_html": True,
        "minify_css": True,
        "minify_js": False,
    },
    "audit": {
        "check_links": True,
        "check_seo": True,
        "check_accessibility": True,
        "max_image_size_kb": 500,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration from an optional config file and merge with defaults.

    Supports .yaml / .yml, .toml, and .env files.  If *config_path* is None,
    the function probes the current working directory for ``website.yaml``,
    ``website.toml``, and ``website.env`` in that order.

    Parameters
    ----------
    config_path:
        Explicit path to a config file; auto-detected when *None*.

    Returns
    -------
    dict
        Merged configuration dictionary.

    Raises
    ------
    SystemExit
        With EXIT_CONFIG_ERROR when the file is present but unreadable or
        unsupported.
    """
    config = dict(DEFAULT_CONFIG)

    candidates: List[Path] = []
    if config_path is not None:
        candidates.append(config_path)
    else:
        cwd = Path.cwd()
        candidates = [
            cwd / "website.yaml",
            cwd / "website.yml",
            cwd / "website.toml",
            cwd / "website.env",
        ]

    found: Optional[Path] = None
    for candidate in candidates:
        if candidate.exists():
            found = candidate
            break

    if found is None:
        logger.debug("No config file found; using built-in defaults.")
        return config

    suffix = found.suffix.lower()
    logger.info("Loading config from %s", found)

    try:
        if suffix in {".yaml", ".yml"}:
            if not _YAML_AVAILABLE:
                logger.warning(
                    "pyyaml is not installed — skipping YAML config (%s).", found
                )
                return config
            with found.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            config = _deep_merge(config, raw)

        elif suffix == ".toml":
            if not _TOML_AVAILABLE or tomllib is None:
                logger.warning(
                    "tomllib/tomli is not installed — skipping TOML config (%s).", found
                )
                return config
            with found.open("rb") as fh:
                raw = tomllib.load(fh)
            config = _deep_merge(config, raw)

        elif suffix == ".env":
            config = _merge_env_file(found, config)

        else:
            logger.warning("Unsupported config format: %s", found.suffix)

    except (OSError, ValueError, KeyError) as exc:
        logger.error("Failed to parse config file %s: %s", found, exc)
        sys.exit(EXIT_CONFIG_ERROR)

    return config


def _merge_env_file(path: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a .env-style file and overlay matching keys onto *config*.

    Only keys matching ``WEBSITE__<SECTION>__<KEY>`` (double underscore as
    separator) are recognised.  All values are strings; booleans ("true" /
    "false") and integers are coerced automatically.

    Parameters
    ----------
    path:
        Path to the .env file.
    config:
        Base configuration dict to merge into.

    Returns
    -------
    dict
        Updated configuration dict.
    """
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key.upper().startswith("WEBSITE__"):
                continue
            parts = key.split("__")
            if len(parts) != 3:
                continue
            _, section, subkey = parts
            section = section.lower()
            subkey = subkey.lower()
            if section not in config:
                config[section] = {}
            # Type coercion
            if value.lower() == "true":
                config[section][subkey] = True
            elif value.lower() == "false":
                config[section][subkey] = False
            elif value.isdigit():
                config[section][subkey] = int(value)
            else:
                config[section][subkey] = value
    return config


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _file_checksum(path: Path, algorithm: str = "sha256") -> str:
    """
    Return the hex digest of *path* using *algorithm*.

    Parameters
    ----------
    path:
        File to hash.
    algorithm:
        Hash algorithm name supported by :mod:`hashlib`.

    Returns
    -------
    str
        Hex-encoded digest string.
    """
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def _human_bytes(num_bytes: int) -> str:
    """
    Format *num_bytes* as a human-readable string (e.g. ``"3.2 KB"``).

    Parameters
    ----------
    num_bytes:
        Byte count to format.

    Returns
    -------
    str
        Formatted string with appropriate unit.
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:5.1f} {unit}"
        num_bytes = int(num_bytes / 1024)
    return f"{num_bytes:.1f} PB"


def _collect_files(root: Path, extensions: Iterable[str]) -> List[Path]:
    """
    Recursively collect files under *root* with any of the given *extensions*.

    Parameters
    ----------
    root:
        Directory to walk.
    extensions:
        Iterable of lowercase file extensions (e.g. ``[".html", ".htm"]``).

    Returns
    -------
    list[Path]
        Sorted list of matching paths.

    Raises
    ------
    SystemExit
        With EXIT_IO_ERROR if *root* is not a directory.
    """
    if not root.is_dir():
        logger.error("Path is not a directory: %s", root)
        sys.exit(EXIT_IO_ERROR)
    exts = {e.lower() for e in extensions}
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in exts and p.is_file())


def _relative(path: Path, root: Path) -> str:
    """Return *path* relative to *root* as a POSIX string."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# HTML parser (stdlib only — no external dependencies)
# ---------------------------------------------------------------------------

# Regex patterns for lightweight HTML extraction
_RE_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*>", re.DOTALL)
_RE_ATTR = re.compile(r'\b([a-zA-Z][a-zA-Z0-9\-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))', re.DOTALL)
_RE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_RE_META = re.compile(r"<meta\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_RE_LINK = re.compile(r"<link\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_RE_SCRIPT = re.compile(r"<script\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_RE_IMG = re.compile(r"<img\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_RE_A = re.compile(r"<a\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_RE_FORM = re.compile(r"<form\b", re.IGNORECASE)
_RE_HEADING = re.compile(r"<(h[1-6])\b", re.IGNORECASE)
_RE_HTML_LANG = re.compile(r"<html\b([^>]*)>", re.IGNORECASE | re.DOTALL)


def _get_attr(tag_attrs: str, attr: str) -> str:
    """
    Extract the value of *attr* from a string of HTML tag attributes.

    Parameters
    ----------
    tag_attrs:
        Raw attribute string (content between ``<tagname`` and ``>``).
    attr:
        Attribute name to look up (case-insensitive).

    Returns
    -------
    str
        Attribute value, or empty string if not found.
    """
    for m in _RE_ATTR.finditer(tag_attrs):
        name = m.group(1).lower()
        if name == attr.lower():
            return m.group(2) or m.group(3) or m.group(4) or ""
    return ""


def parse_html_file(path: Path, root: Path) -> HtmlReport:
    """
    Parse *path* and return an :class:`HtmlReport` with structural metadata.

    Performs lightweight regex-based extraction of:
    - ``<title>``
    - ``<html lang>``
    - charset ``<meta>``
    - viewport ``<meta>``
    - ``<meta name="description">``
    - ``<link rel="stylesheet">`` hrefs
    - ``<script src>`` sources
    - ``<img src>`` sources and alt attributes
    - ``<a href>`` links
    - heading tags (h1–h6) counts
    - ``<form>`` count

    SEO/accessibility issues are annotated on the returned report.

    Parameters
    ----------
    path:
        Absolute path to the HTML file.
    root:
        Repository root (used for producing relative display paths).

    Returns
    -------
    HtmlReport
        Populated report object.
    """
    rel = _relative(path, root)
    report = HtmlReport(path=path)

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.issues.append(
            Issue("error", "io", f"Cannot read file: {exc}", file=rel)
        )
        return report

    # Strip HTML comments to avoid false positives
    clean = _RE_COMMENT.sub("", content)

    # ---- Title ---------------------------------------------------------------
    title_match = _RE_TITLE.search(clean)
    if title_match:
        report.title = re.sub(r"\s+", " ", title_match.group(1)).strip()
    else:
        report.issues.append(Issue("error", "seo", "Missing <title> tag.", file=rel))

    if report.title and len(report.title) > 60:
        report.issues.append(
            Issue(
                "warning",
                "seo",
                f"<title> is {len(report.title)} chars (recommended ≤ 60).",
                file=rel,
            )
        )

    # ---- <html lang> ---------------------------------------------------------
    html_match = _RE_HTML_LANG.search(clean)
    if html_match:
        report.lang = _get_attr(html_match.group(1), "lang")
    if not report.lang:
        report.issues.append(
            Issue("error", "accessibility", "Missing lang attribute on <html>.", file=rel)
        )

    # ---- Meta tags -----------------------------------------------------------
    for m in _RE_META.finditer(clean):
        attrs = m.group(1)
        charset = _get_attr(attrs, "charset")
        if charset:
            report.charset = charset
        name = _get_attr(attrs, "name").lower()
        http_equiv = _get_attr(attrs, "http-equiv").lower()
        content_val = _get_attr(attrs, "content")
        if name == "description":
            report.description = content_val
        elif name == "viewport":
            report.viewport = content_val
        elif http_equiv == "x-ua-compatible":
            report.issues.append(
                Issue(
                    "info",
                    "compatibility",
                    "Found X-UA-Compatible meta tag (may be unnecessary for modern browsers).",
                    file=rel,
                )
            )

    if not report.charset:
        report.issues.append(
            Issue("warning", "encoding", "No charset declaration found.", file=rel)
        )
    if not report.viewport:
        report.issues.append(
            Issue("warning", "responsive", "Missing viewport meta tag.", file=rel)
        )
    if not report.description:
        report.issues.append(
            Issue("warning", "seo", "Missing meta description.", file=rel)
        )
    elif len(report.description) > 160:
        report.issues.append(
            Issue(
                "warning",
                "seo",
                f"Meta description is {len(report.description)} chars (recommended ≤ 160).",
                file=rel,
            )
        )

    # ---- Stylesheets ---------------------------------------------------------
    for m in _RE_LINK.finditer(clean):
        attrs = m.group(1)
        if _get_attr(attrs, "rel").lower() == "stylesheet":
            href = _get_attr(attrs, "href")
            if href:
                report.stylesheets.append(href)

    # ---- Scripts -------------------------------------------------------------
    for m in _RE_SCRIPT.finditer(clean):
        attrs = m.group(1)
        src = _get_attr(attrs, "src")
        if src:
            report.scripts.append(src)
        defer = "defer" in attrs.lower()
        asyncattr = "async" in attrs.lower()
        if src and not defer and not asyncattr:
            report.issues.append(
                Issue(
                    "warning",
                    "performance",
                    f"Script '{src}' lacks defer/async — may block rendering.",
                    file=rel,
                )
            )

    # ---- Images --------------------------------------------------------------
    for m in _RE_IMG.finditer(clean):
        attrs = m.group(1)
        src = _get_attr(attrs, "src")
        alt = _get_attr(attrs, "alt")
        if src:
            report.images.append(src)
        if not alt and alt != "":
            # alt="" is valid for decorative images; missing attr is a bug
            report.issues.append(
                Issue(
                    "error",
                    "accessibility",
                    f"Image '{src or '?'}' is missing an alt attribute.",
                    file=rel,
                )
            )

    # ---- Anchors / links -----------------------------------------------------
    for m in _RE_A.finditer(clean):
        attrs = m.group(1)
        href = _get_attr(attrs, "href")
        if href:
            report.links.append(href)
            if href.startswith("javascript:"):
                report.issues.append(
                    Issue(
                        "warning",
                        "security",
                        f"Anchor uses javascript: href — consider an event listener instead.",
                        file=rel,
                    )
                )

    # ---- Headings ------------------------------------------------------------
    heading_counts: Dict[str, int] = defaultdict(int)
    for m in _RE_HEADING.finditer(clean):
        tag = m.group(1).lower()
        heading_counts[tag] += 1
    report.headings = dict(heading_counts)

    h1_count = heading_counts.get("h1", 0)
    if h1_count == 0:
        report.issues.append(
            Issue("warning", "seo", "No <h1> heading found.", file=rel)
        )
    elif h1_count > 1:
        report.issues.append(
            Issue("warning", "seo", f"Multiple <h1> headings ({h1_count}) found.", file=rel)
        )

    # ---- Forms ---------------------------------------------------------------
    report.forms = len(_RE_FORM.findall(clean))

    return report


# ---------------------------------------------------------------------------
# CSS analyser
# ---------------------------------------------------------------------------

_RE_CSS_RULE = re.compile(r"([^{]+)\{([^}]*)\}", re.DOTALL)
_RE_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_CSS_VAR_DECL = re.compile(r"--([a-zA-Z0-9\-]+)\s*:")
_RE_CSS_VAR_USE = re.compile(r"var\(--([a-zA-Z0-9\-]+)\)")
_RE_CSS_IMPORT = re.compile(r"@import\s+url\(['\"]?([^'\"\)]+)['\"]?\)", re.IGNORECASE)


def analyse_css(path: Path, root: Path) -> List[Issue]:
    """
    Perform a basic static analysis of a CSS file.

    Checks performed:
    - ``!important`` overuse
    - Duplicate selectors
    - Declared CSS custom properties that are never referenced
    - ``@import url()`` usage (network latency concern)
    - Empty rule-sets

    Parameters
    ----------
    path:
        Path to the ``.css`` file.
    root:
        Repository root for display paths.

    Returns
    -------
    list[Issue]
        All issues discovered.
    """
    rel = _relative(path, root)
    issues: List[Issue] = []

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [Issue("error", "io", f"Cannot read CSS: {exc}", file=rel)]

    # Remove comments
    clean = _RE_CSS_COMMENT.sub("", source)

    # @import check
    for m in _RE_CSS_IMPORT.finditer(clean):
        issues.append(
            Issue(
                "warning",
                "performance",
                f"CSS @import url('{m.group(1)}') blocks rendering; prefer <link> tags.",
                file=rel,
            )
        )

    # !important overuse
    important_count = clean.count("!important")
    if important_count > 5:
        issues.append(
            Issue(
                "warning",
                "maintainability",
                f"Found {important_count} uses of !important — consider refactoring specificity.",
                file=rel,
            )
        )

    # Selector analysis
    seen_selectors: Dict[str, int] = defaultdict(int)
    for m in _RE_CSS_RULE.finditer(clean):
        selector = re.sub(r"\s+", " ", m.group(1)).strip()
        body = m.group(2).strip()
        if selector.startswith("@"):
            continue  # skip at-rules like @keyframes
        seen_selectors[selector] += 1
        if not body:
            issues.append(
                Issue("info", "maintainability", f"Empty rule-set: '{selector}'.", file=rel)
            )

    for selector, count in seen_selectors.items():
        if count > 1:
            issues.append(
                Issue(
                    "warning",
                    "maintainability",
                    f"Duplicate selector '{selector}' appears {count} times.",
                    file=rel,
                )
            )

    # CSS custom property usage
    declared_vars = set(_RE_CSS_VAR_DECL.findall(clean))
    used_vars = set(_RE_CSS_VAR_USE.findall(clean))
    for var in sorted(declared_vars - used_vars):
        issues.append(
            Issue(
                "info",
                "maintainability",
                f"CSS custom property '--{var}' is declared but never used.",
                file=rel,
            )
        )

    return issues


# ---------------------------------------------------------------------------
# JavaScript analyser
# ---------------------------------------------------------------------------

_RE_JS_CONSOLE = re.compile(r"\bconsole\.(log|warn|error|debug|info)\b")
_RE_JS_EVAL = re.compile(r"\beval\s*\(")
_RE_JS_DOCUMENT_WRITE = re.compile(r"\bdocument\.write\s*\(")
_RE_JS_INNER_HTML = re.compile(r"\.innerHTML\s*=")
_RE_JS_VAR = re.compile(r"\bvar\b")
_RE_JS_STRICT = re.compile(r"""['"]use strict['"]""")


def analyse_js(path: Path, root: Path) -> List[Issue]:
    """
    Perform lightweight static analysis of a JavaScript file.

    Checks performed:
    - ``console.*`` calls left in production code
    - Use of ``eval()``
    - Use of ``document.write()``
    - Direct ``innerHTML`` assignment (XSS risk)
    - Use of legacy ``var`` declarations
    - Missing ``"use strict"`` directive

    Parameters
    ----------
    path:
        Path to the ``.js`` file.
    root:
        Repository root for display paths.

    Returns
    -------
    list[Issue]
        All issues discovered.
    """
    rel = _relative(path, root)
    issues: List[Issue] = []

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [Issue("error", "io", f"Cannot read JS: {exc}", file=rel)]

    lines = source.splitlines()

    if not _RE_JS_STRICT.search(source):
        issues.append(
            Issue("info", "quality", "'use strict' directive not found.", file=rel)
        )

    for lineno, line in enumerate(lines, start=1):
        if _RE_JS_EVAL.search(line):
            issues.append(
                Issue("error", "security", "Use of eval() detected.", file=rel, line=lineno)
            )
        if _RE_JS_DOCUMENT_WRITE.search(line):
            issues.append(
                Issue(
                    "warning",
                    "performance",
                    "document.write() blocks parsing and is deprecated.",
                    file=rel,
                    line=lineno,
                )
            )
        if _RE_JS_INNER_HTML.search(line):
            issues.append(
                Issue(
                    "warning",
                    "security",
                    "Direct innerHTML assignment may introduce XSS — use textContent or DOMPurify.",
                    file=rel,
                    line=lineno,
                )
            )
        if _RE_JS_VAR.search(line):
            issues.append(
                Issue(
                    "info",
                    "quality",
                    "Use of 'var' — prefer 'const' or 'let'.",
                    file=rel,
                    line=lineno,
                )
            )

    console_calls = [(m, i + 1) for i, line in enumerate(lines) for m in _RE_JS_CONSOLE.finditer(line)]
    if console_calls:
        issues.append(
            Issue(
                "warning",
                "quality",
                f"Found {len(console_calls)} console.* call(s) — remove before deploying.",
                file=rel,
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Asset inventory
# ---------------------------------------------------------------------------

_ASSET_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".ts",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".json", ".xml", ".txt", ".md",
    ".pdf", ".zip",
}


def collect_assets(root: Path) -> List[AssetInfo]:
    """
    Walk *root* and build a :class:`AssetInfo` record for every web asset.

    Parameters
    ----------
    root:
        Repository root directory.

    Returns
    -------
    list[AssetInfo]
        Sorted list of asset metadata objects.
    """
    assets: List[AssetInfo] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _ASSET_EXTENSIONS:
            continue
        # Skip hidden directories (e.g. .git)
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            stat = path.stat()
            mime, _ = mimetypes.guess_type(str(path))
            assets.append(
                AssetInfo(
                    path=path,
                    size_bytes=stat.st_size,
                    mime_type=mime or "application/octet-stream",
                    checksum=_file_checksum(path),
                    last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            )
        except OSError as exc:
            logger.warning("Cannot stat asset %s: %s", path, exc)
    return assets


# ---------------------------------------------------------------------------
# Local reference checker
# ---------------------------------------------------------------------------


def check_local_references(html_reports: List[HtmlReport], root: Path) -> List[Issue]:
    """
    Verify that every local asset reference (href, src) can be resolved.

    Only checks references that do *not* start with ``http://``,
    ``https://``, ``//``, ``#``, ``data:``, or ``mailto:``.

    Parameters
    ----------
    html_reports:
        List of parsed HTML reports whose links/scripts/images/stylesheets
        will be checked.
    root:
        Repository root directory.

    Returns
    -------
    list[Issue]
        Issues for any unresolved local references.
    """
    issues: List[Issue] = []
    _skip_prefixes = ("http://", "https://", "//", "#", "data:", "mailto:", "tel:")

    for report in html_reports:
        html_dir = report.path.parent
        refs: List[Tuple[str, str]] = (
            [(ref, "stylesheet") for ref in report.stylesheets]
            + [(ref, "script") for ref in report.scripts]
            + [(ref, "image") for ref in report.images]
            + [(ref, "link") for ref in report.links]
        )
        for ref, kind in refs:
            if any(ref.startswith(p) for p in _skip_prefixes):
                continue
            # Strip query string / fragment
            clean_ref = re.split(r"[?#]", ref)[0]
            if not clean_ref:
                continue
            # Resolve relative to HTML file's directory
            target = (html_dir / clean_ref).resolve()
            if not target.exists():
                issues.append(
                    Issue(
                        "error",
                        "broken-link",
                        f"{kind.capitalize()} '{ref}' not found.",
                        file=_relative(report.path, root),
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# Minifier (naive, stdlib-only)
# ---------------------------------------------------------------------------


def _minify_css(source: str) -> str:
    """
    Minify a CSS string by removing comments and collapsing whitespace.

    This is an intentionally simple implementation.  For production-grade
    minification use ``csscompressor`` or a dedicated build tool.

    Parameters
    ----------
    source:
        Raw CSS text.

    Returns
    -------
    str
        Minified CSS text.
    """
    # Remove comments
    result = _RE_CSS_COMMENT.sub("", source)
    # Collapse whitespace
    result = re.sub(r"\s+", " ", result)
    # Remove spaces around punctuation
    result = re.sub(r"\s*([{};:,>~+])\s*", r"\1", result)
    # Remove last semicolon before closing brace
    result = result.replace(";}", "}")
    return result.strip()


def _minify_html(source: str) -> str:
    """
    Minify an HTML string by collapsing inter-tag whitespace and removing comments.

    Does *not* minify inline ``<script>`` or ``<style>`` blocks.

    Parameters
    ----------
    source:
        Raw HTML text.

    Returns
    -------
    str
        Minified HTML text.
    """
    result = _RE_COMMENT.sub("", source)
    result = re.sub(r">\s+<", "><", result)
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip()


def build_site(
    root: Path,
    output_dir: Path,
    config: Dict[str, Any],
    dry_run: bool = False,
) -> None:
    """
    Copy all web assets from *root* to *output_dir*, optionally minifying
    HTML and CSS files.

    Parameters
    ----------
    root:
        Source directory.
    output_dir:
        Destination directory (created if absent).
    config:
        Configuration dict (``build`` section is used).
    dry_run:
        When *True* print planned actions without writing any files.

    Raises
    ------
    SystemExit
        With EXIT_IO_ERROR on filesystem errors.
    """
    build_cfg = config.get("build", {})
    minify_html = build_cfg.get("minify_html", True)
    minify_css = build_cfg.get("minify_css", True)

    if dry_run:
        print(f"[DRY-RUN] Would write build output to: {output_dir}")

    assets = collect_assets(root)
    if not assets:
        logger.warning("No assets found under %s", root)
        return

    copied = 0
    minified = 0
    for asset in assets:
        rel = asset.path.relative_to(root)
        dest = output_dir / rel
        action_label = "copy"

        source_text: Optional[str] = None
        if minify_html and asset.mime_type == "text/html":
            try:
                source_text = _minify_html(asset.path.read_text(encoding="utf-8", errors="replace"))
                action_label = "minify-html"
                minified += 1
            except OSError:
                pass
        elif minify_css and asset.mime_type == "text/css":
            try:
                source_text = _minify_css(asset.path.read_text(encoding="utf-8", errors="replace"))
                action_label = "minify-css"
                minified += 1
            except OSError:
                pass

        size_before = asset.size_bytes
        size_after = len(source_text.encode()) if source_text is not None else size_before
        saving = size_before - size_after

        if dry_run:
            print(
                f"  [{action_label:11s}] {rel}  "
                f"({_human_bytes(size_before)} → {_human_bytes(size_after)}"
                f"{f', saves {_human_bytes(saving)}' if saving > 0 else ''})"
            )
        else:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if source_text is not None:
                    dest.write_text(source_text, encoding="utf-8")
                else:
                    shutil.copy2(asset.path, dest)
                copied += 1
            except OSError as exc:
                logger.error("Failed to write %s: %s", dest, exc)
                sys.exit(EXIT_IO_ERROR)

    if not dry_run:
        logger.info("Build complete: %d files written (%d minified) → %s", copied, minified, output_dir)
    else:
        print(f"\n[DRY-RUN] Would process {len(assets)} files, minify {minified}.")


# ---------------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------------


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that suppresses per-request log output."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress default access log output to keep terminal clean."""
        pass

    def log_error(self, format: str, *args: Any) -> None:  # noqa: A002
        """Route errors through the module logger."""
        logger.error(format, *args)


def serve(root: Path, host: str, port: int) -> None:
    """
    Start a blocking HTTP development server rooted at *root*.

    Press ``Ctrl+C`` to stop the server.

    Parameters
    ----------
    root:
        Directory to serve as the web-root.
    host:
        Bind address (e.g. ``"127.0.0.1"`` or ``"0.0.0.0"``).
    port:
        TCP port to listen on.

    Raises
    ------
    SystemExit
        With EXIT_IO_ERROR if the port is already in use.
    """
    # Verify the port is free
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            logger.error("Port %d is already in use on %s.", port, host)
            sys.exit(EXIT_IO_ERROR)

    handler = lambda *args, **kwargs: _SilentHandler(*args, directory=str(root), **kwargs)  # noqa: E731
    server = http.server.HTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"Serving {root}  →  {url}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# Terminal report printer
# ---------------------------------------------------------------------------

_SEVERITY_COLOUR = {
    "error":   "\033[91m",  # bright red
    "warning": "\033[93m",  # yellow
    "info":    "\033[96m",  # cyan
}
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _colour(text: str, code: str, force: bool = False) -> str:
    """Wrap *text* in ANSI *code* only if stdout is a TTY (or *force*)."""
    if force or sys.stdout.isatty():
        return f"{code}{text}{_RESET}"
    return text


def print_site_report(report: SiteReport, verbose: bool = False) -> None:
    """
    Print a human-readable summary of *report* to stdout.

    Parameters
    ----------
    report:
        Fully populated :class:`SiteReport`.
    verbose:
        When *True*, print every issue (not just errors and warnings).
    """
    sep = "─" * 70
    print()
    print(_colour(f"{'WEBSITE ANALYSIS REPORT':^70}", _BOLD))
    print(sep)
    print(f"  Root      : {report.root}")
    print(f"  Generated : {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  HTML files: {len(report.html_reports)}")
    print(f"  Assets    : {len(report.assets)} ({_human_bytes(report.total_size_bytes)})")
    print(sep)

    # ---- Per-file summaries -------------------------------------------------
    for hr in report.html_reports:
        rel = _relative(hr.path, report.root)
        print(f"\n  {_colour(rel, _BOLD)}")
        print(f"    Title      : {hr.title or _colour('(none)', _DIM)}")
        print(f"    Lang       : {hr.lang or _colour('(none)', _DIM)}")
        print(f"    Description: {(hr.description[:80] + '…') if len(hr.description) > 80 else hr.description or _colour('(none)', _DIM)}")
        print(f"    Headings   : {dict(hr.headings) or _colour('(none)', _DIM)}")
        print(f"    Stylesheets: {len(hr.stylesheets)}  Scripts: {len(hr.scripts)}  Images: {len(hr.images)}  Links: {len(hr.links)}")
        _print_issues(hr.issues, verbose=verbose)

    # ---- CSS / JS issues ----------------------------------------------------
    if report.css_issues:
        print(f"\n  {_colour('CSS Issues', _BOLD)}")
        _print_issues(report.css_issues, verbose=verbose)

    if report.js_issues:
        print(f"\n  {_colour('JavaScript Issues', _BOLD)}")
        _print_issues(report.js_issues, verbose=verbose)

    if report.global_issues:
        print(f"\n  {_colour('Global Issues', _BOLD)}")
        _print_issues(report.global_issues, verbose=verbose)

    # ---- Summary ------------------------------------------------------------
    print()
    print(sep)
    err_col = _SEVERITY_COLOUR["error"] if report.error_count else ""
    warn_col = _SEVERITY_COLOUR["warning"] if report.warning_count else ""
    print(
        f"  {_colour(str(report.error_count) + ' error(s)', err_col or _DIM)}  "
        f"{_colour(str(report.warning_count) + ' warning(s)', warn_col or _DIM)}  "
        f"{len([i for i in report.all_issues if i.severity == 'info'])} info"
    )
    print(sep)
    print()


def _print_issues(issues: List[Issue], verbose: bool = False) -> None:
    """
    Print *issues* to stdout, filtering by severity when *verbose* is False.

    Parameters
    ----------
    issues:
        List of :class:`Issue` objects to display.
    verbose:
        Show ``info``-level issues when *True*.
    """
    for issue in issues:
        if issue.severity == "info" and not verbose:
            continue
        colour = _SEVERITY_COLOUR.get(issue.severity, "")
        loc = f" ({issue.file}:{issue.line})" if issue.file and issue.line else (f" ({issue.file})" if issue.file else "")
        sev_label = f"{issue.severity.upper():<8}"
        print(
            f"    {_colour(sev_label, colour)}  "
            f"{issue.category:20s}  {issue.message}{_colour(loc, _DIM)}"
        )


# ---------------------------------------------------------------------------
# HTML report generator
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Website Report — {root}</title>
<style>
  body{{font-family:system-ui,sans-serif;margin:0;background:#f6f8fb;color:#1f2937}}
  h1{{background:#2563eb;color:#fff;margin:0;padding:1rem 2rem;font-size:1.4rem}}
  .meta{{padding:1rem 2rem;background:#fff;border-bottom:1px solid #e5e7eb}}
  section{{margin:1.5rem 2rem;background:#fff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden}}
  h2{{margin:0;padding:.75rem 1rem;background:#f1f5f9;font-size:1rem;border-bottom:1px solid #e5e7eb}}
  table{{width:100%;border-collapse:collapse;font-size:.875rem}}
  th,td{{padding:.5rem .75rem;text-align:left;border-bottom:1px solid #f3f4f6}}
  th{{background:#f9fafb;font-weight:600}}
  .error{{color:#dc2626}}.warning{{color:#d97706}}.info{{color:#0891b2}}
  .badge{{display:inline-block;border-radius:4px;padding:1px 6px;font-size:.75rem;font-weight:600}}
  .badge.error{{background:#fee2e2}}.badge.warning{{background:#fef3c7}}.badge.info{{background:#e0f2fe}}
  footer{{text-align:center;padding:2rem;color:#6b7280;font-size:.8rem}}
</style>
</head>
<body>
<h1>Website Analysis Report</h1>
<div class="meta">
  <strong>Root:</strong> {root} &nbsp;|&nbsp;
  <strong>Generated:</strong> {generated_at} &nbsp;|&nbsp;
  <strong>HTML files:</strong> {html_count} &nbsp;|&nbsp;
  <strong>Total assets:</strong> {asset_count} ({total_size})
</div>
{sections}
<footer>Generated by Website.py on {generated_at}</footer>
</body>
</html>
"""

_ISSUE_ROW = '<tr><td><span class="badge {sev}">{sev}</span></td><td>{cat}</td><td>{msg}</td><td>{file}</td></tr>'


def generate_html_report(report: SiteReport, output_path: Path) -> None:
    """
    Write a self-contained HTML analysis report to *output_path*.

    Parameters
    ----------
    report:
        Fully populated :class:`SiteReport`.
    output_path:
        Destination file.  Parent directories are created if needed.

    Raises
    ------
    SystemExit
        With EXIT_IO_ERROR on write failure.
    """
    sections: List[str] = []

    # Asset table
    asset_rows = "".join(
        f"<tr><td>{_relative(a.path, report.root)}</td>"
        f"<td>{a.mime_type}</td>"
        f"<td>{_human_bytes(a.size_bytes)}</td>"
        f"<td>{a.last_modified.strftime('%Y-%m-%d')}</td>"
        f"<td><code>{a.checksum[:12]}…</code></td></tr>"
        for a in report.assets
    )
    sections.append(
        f'<section><h2>Assets ({len(report.assets)})</h2>'
        f'<table><tr><th>Path</th><th>MIME</th><th>Size</th><th>Modified</th><th>SHA256</th></tr>'
        f"{asset_rows}</table></section>"
    )

    # Issues table
    all_issues = report.all_issues
    issue_rows = "".join(
        _ISSUE_ROW.format(
            sev=i.severity,
            cat=i.category,
            msg=i.message,
            file=f"{i.file}:{i.line}" if i.line else i.file,
        )
        for i in all_issues
    )
    sections.append(
        f'<section><h2>Issues ({len(all_issues)})</h2>'
        f'<table><tr><th>Severity</th><th>Category</th><th>Message</th><th>Location</th></tr>'
        f"{issue_rows}</table></section>"
    )

    html = _HTML_TEMPLATE.format(
        root=str(report.root),
        generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        html_count=len(report.html_reports),
        asset_count=len(report.assets),
        total_size=_human_bytes(report.total_size_bytes),
        sections="\n".join(sections),
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write HTML report to %s: %s", output_path, exc)
        sys.exit(EXIT_IO_ERROR)

    print(f"HTML report written to: {output_path}")


# ---------------------------------------------------------------------------
# Core analysis orchestrator
# ---------------------------------------------------------------------------


def run_analysis(root: Path, config: Dict[str, Any]) -> SiteReport:
    """
    Run the complete static analysis pipeline over *root*.

    Steps:
    1. Collect all asset files.
    2. Parse every HTML file.
    3. Analyse every CSS file.
    4. Analyse every JS file.
    5. Check local asset references across all HTML files.
    6. Flag oversized images.

    Parameters
    ----------
    root:
        Repository root directory.
    config:
        Merged configuration dictionary.

    Returns
    -------
    SiteReport
        Fully populated analysis report.
    """
    audit_cfg = config.get("audit", {})
    max_img_kb = int(audit_cfg.get("max_image_size_kb", 500))

    site = SiteReport(root=root)
    site.assets = collect_assets(root)

    # Parse HTML
    html_files = _collect_files(root, [".html", ".htm"])
    logger.info("Found %d HTML file(s).", len(html_files))
    for path in html_files:
        site.html_reports.append(parse_html_file(path, root))

    # Analyse CSS
    css_files = _collect_files(root, [".css"])
    logger.info("Found %d CSS file(s).", len(css_files))
    for path in css_files:
        site.css_issues.extend(analyse_css(path, root))

    # Analyse JS
    js_files = _collect_files(root, [".js"])
    logger.info("Found %d JS file(s).", len(js_files))
    for path in js_files:
        site.js_issues.extend(analyse_js(path, root))

    # Local reference check
    if audit_cfg.get("check_links", True):
        site.global_issues.extend(check_local_references(site.html_reports, root))

    # Image size check
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}
    for asset in site.assets:
        if asset.path.suffix.lower() in image_exts:
            kb = asset.size_bytes / 1024
            if kb > max_img_kb:
                site.global_issues.append(
                    Issue(
                        "warning",
                        "performance",
                        f"Image is {kb:.0f} KB (>{max_img_kb} KB threshold): {_relative(asset.path, root)}",
                        file=_relative(asset.path, root),
                    )
                )

    return site


# ---------------------------------------------------------------------------
# CLI command implementations
# ---------------------------------------------------------------------------


def cmd_analyze(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """
    Execute the ``analyze`` subcommand.

    Runs the full analysis pipeline and prints a terminal report.

    Parameters
    ----------
    args:
        Parsed CLI arguments.
    config:
        Loaded configuration.

    Returns
    -------
    int
        Exit code (0 on success, non-zero if errors were found).
    """
    root = Path(args.path).resolve()
    if not root.is_dir():
        logger.error("Not a directory: %s", root)
        return EXIT_IO_ERROR

    logger.info("Analysing %s …", root)
    report = run_analysis(root, config)
    print_site_report(report, verbose=getattr(args, "verbose", False))

    if getattr(args, "output", None):
        output_path = Path(args.output).resolve()
        generate_html_report(report, output_path)

    return EXIT_VALIDATION_FAILED if report.error_count > 0 else EXIT_OK


def cmd_audit(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """
    Execute the ``audit`` subcommand.

    Identical to ``analyze`` but emits a focused summary of issues only.

    Parameters
    ----------
    args:
        Parsed CLI arguments.
    config:
        Loaded configuration.

    Returns
    -------
    int
        Exit code (0 if no errors, EXIT_VALIDATION_FAILED otherwise).
    """
    root = Path(args.path).resolve()
    if not root.is_dir():
        logger.error("Not a directory: %s", root)
        return EXIT_IO_ERROR

    if args.dry_run:
        print(f"[DRY-RUN] Would audit: {root}")
        print("[DRY-RUN] Checks that would run:")
        audit_cfg = config.get("audit", {})
        checks = {
            "check_links": "Broken local asset references",
            "check_seo": "SEO meta-tags, title, headings",
            "check_accessibility": "Alt attributes, lang, ARIA roles",
        }
        for key, label in checks.items():
            status = "✓" if audit_cfg.get(key, True) else "✗ (disabled in config)"
            print(f"  {status}  {label}")
        return EXIT_OK

    logger.info("Auditing %s …", root)
    report = run_analysis(root, config)
    issues = report.all_issues
    if not issues:
        print("No issues found. ✓")
        return EXIT_OK

    print(f"\nAudit findings for {root}:\n")
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    for issue in errors + warnings + (infos if getattr(args, "verbose", False) else []):
        colour = _SEVERITY_COLOUR.get(issue.severity, "")
        loc = f" ({issue.file}:{issue.line})" if issue.file and issue.line else (f" ({issue.file})" if issue.file else "")
        sev_label = f"{issue.severity.upper():<8}"
        print(
            f"  {_colour(sev_label, colour)}  "
            f"{issue.category:20s}  {issue.message}{_colour(loc, _DIM)}"
        )

    print(f"\nTotal: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info.")
    return EXIT_VALIDATION_FAILED if errors else EXIT_OK


def cmd_serve(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """
    Execute the ``serve`` subcommand.

    Starts a local HTTP development server.

    Parameters
    ----------
    args:
        Parsed CLI arguments.
    config:
        Loaded configuration.

    Returns
    -------
    int
        Exit code.
    """
    root = Path(args.path).resolve()
    if not root.is_dir():
        logger.error("Not a directory: %s", root)
        return EXIT_IO_ERROR

    server_cfg = config.get("server", {})
    host: str = getattr(args, "host", None) or server_cfg.get("host", "127.0.0.1")
    port: int = getattr(args, "port", None) or int(server_cfg.get("port", 8000))

    if args.dry_run:
        print(f"[DRY-RUN] Would start HTTP server at http://{host}:{port}")
        print(f"[DRY-RUN] Serving directory: {root}")
        return EXIT_OK

    serve(root, host, port)
    return EXIT_OK


def cmd_build(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """
    Execute the ``build`` subcommand.

    Copies and optionally minifies assets into an output directory.

    Parameters
    ----------
    args:
        Parsed CLI arguments.
    config:
        Loaded configuration.

    Returns
    -------
    int
        Exit code.
    """
    root = Path(args.path).resolve()
    if not root.is_dir():
        logger.error("Not a directory: %s", root)
        return EXIT_IO_ERROR

    build_cfg = config.get("build", {})
    output_rel: str = getattr(args, "output", None) or build_cfg.get("output_dir", "dist")
    output_dir = (root / output_rel).resolve()

    build_site(root, output_dir, config, dry_run=args.dry_run)
    return EXIT_OK


def cmd_report(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """
    Execute the ``report`` subcommand.

    Runs analysis and writes a self-contained HTML report file.

    Parameters
    ----------
    args:
        Parsed CLI arguments.
    config:
        Loaded configuration.

    Returns
    -------
    int
        Exit code.
    """
    root = Path(args.path).resolve()
    if not root.is_dir():
        logger.error("Not a directory: %s", root)
        return EXIT_IO_ERROR

    output_path = Path(getattr(args, "output", None) or "website-report.html").resolve()

    if args.dry_run:
        print(f"[DRY-RUN] Would generate HTML report → {output_path}")
        return EXIT_OK

    logger.info("Generating report for %s …", root)
    site_report = run_analysis(root, config)
    generate_html_report(site_report, output_path)
    print_site_report(site_report, verbose=getattr(args, "verbose", False))
    return EXIT_VALIDATION_FAILED if site_report.error_count > 0 else EXIT_OK


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """
    Build and return the top-level :class:`argparse.ArgumentParser`.

    Subcommands:
    - ``analyze``  — full analysis + terminal report
    - ``audit``    — focused issue listing
    - ``serve``    — local dev server
    - ``build``    — minify + copy assets
    - ``report``   — generate HTML report

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="Website",
        description=(
            "Production-ready static website analysis, auditing, serving, and build tool.\n\n"
            "Examples:\n"
            "  python Website.py analyze ./\n"
            "  python Website.py audit ./ --verbose\n"
            "  python Website.py serve ./ --port 3000\n"
            "  python Website.py build ./ --output dist --dry-run\n"
            "  python Website.py report ./ --output report.html\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="Path to a .yaml, .toml, or .env config file (auto-detected if omitted).",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set log verbosity (default: WARNING).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Website 1.0.0",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ---- analyze -------------------------------------------------------------
    p_analyze = subparsers.add_parser(
        "analyze",
        help="Run full static analysis and print a terminal report.",
        description="Analyse all HTML, CSS, and JS files under PATH and print a detailed report.",
    )
    p_analyze.add_argument("path", metavar="PATH", help="Root directory of the website.")
    p_analyze.add_argument("--dry-run", action="store_true", help="No-op (analysis always prints to stdout).")
    p_analyze.add_argument("--verbose", "-v", action="store_true", help="Include info-level issues.")
    p_analyze.add_argument("--output", "-o", metavar="FILE", help="Also write an HTML report to FILE.")
    p_analyze.set_defaults(func=cmd_analyze)

    # ---- audit ---------------------------------------------------------------
    p_audit = subparsers.add_parser(
        "audit",
        help="Run a focused SEO/accessibility/security audit.",
        description="Audit all HTML, CSS, and JS files under PATH. Exits non-zero if errors found.",
    )
    p_audit.add_argument("path", metavar="PATH", help="Root directory of the website.")
    p_audit.add_argument("--dry-run", action="store_true", help="Preview which checks would run without executing them.")
    p_audit.add_argument("--verbose", "-v", action="store_true", help="Include info-level issues.")
    p_audit.set_defaults(func=cmd_audit)

    # ---- serve ---------------------------------------------------------------
    p_serve = subparsers.add_parser(
        "serve",
        help="Start a local HTTP development server.",
        description="Serve PATH over HTTP for local development.",
    )
    p_serve.add_argument("path", metavar="PATH", help="Directory to serve.")
    p_serve.add_argument("--host", default=None, metavar="HOST", help="Bind address (default: 127.0.0.1).")
    p_serve.add_argument("--port", default=None, type=int, metavar="PORT", help="TCP port (default: 8000).")
    p_serve.add_argument("--dry-run", action="store_true", help="Print what would be started without starting.")
    p_serve.set_defaults(func=cmd_serve)

    # ---- build ---------------------------------------------------------------
    p_build = subparsers.add_parser(
        "build",
        help="Copy and minify website assets into an output directory.",
        description="Minify HTML and CSS, then copy all assets to the output directory.",
    )
    p_build.add_argument("path", metavar="PATH", help="Source directory.")
    p_build.add_argument("--output", "-o", default=None, metavar="DIR", help="Output directory (default: dist).")
    p_build.add_argument("--dry-run", action="store_true", help="Preview actions without writing files.")
    p_build.set_defaults(func=cmd_build)

    # ---- report --------------------------------------------------------------
    p_report = subparsers.add_parser(
        "report",
        help="Generate a self-contained HTML analysis report.",
        description="Analyse PATH and write a single HTML report file.",
    )
    p_report.add_argument("path", metavar="PATH", help="Root directory of the website.")
    p_report.add_argument("--output", "-o", default="website-report.html", metavar="FILE", help="Output HTML file (default: website-report.html).")
    p_report.add_argument("--dry-run", action="store_true", help="Print what would be generated without writing.")
    p_report.add_argument("--verbose", "-v", action="store_true", help="Include info-level issues in terminal output.")
    p_report.set_defaults(func=cmd_report)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Main entry point.

    Parses *argv* (defaults to ``sys.argv[1:]``), loads configuration, and
    dispatches to the appropriate subcommand handler.

    Parameters
    ----------
    argv:
        Optional argument list for programmatic invocation / testing.

    Returns
    -------
    int
        Exit code to pass to :func:`sys.exit`.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    logging.getLogger("website").setLevel(getattr(logging, args.log_level))

    # Load config
    config_path = Path(args.config).resolve() if args.config else None
    if config_path and not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return EXIT_CONFIG_ERROR
    config = load_config(config_path)

    # Dispatch
    try:
        return int(args.func(args, config))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return EXIT_GENERAL_ERROR
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unexpected error: %s", exc)
        return EXIT_GENERAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
