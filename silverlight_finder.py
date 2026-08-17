#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║              S I L V E R L I G H T   S I T E   F I N D E R     ║
║  Entdeckt veraltete Silverlight-Webanwendungen und hilft dabei, ║
║  diese über den IE-Modus von Microsoft Edge zugänglich zu machen ║
╚══════════════════════════════════════════════════════════════════╝

Voraussetzungen:
    pip install requests beautifulsoup4 lxml
"""

import sys
import os
import re
import json
import csv
import webbrowser
import threading
import subprocess
import queue
import xml.etree.ElementTree as ET
from xml.dom import minidom
from urllib.parse import urljoin, urlparse, quote
from datetime import datetime
from typing import List, Dict, Optional, Set, Tuple
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# ─── Abhängigkeiten prüfen ────────────────────────────────────────────────────

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning  # type: ignore
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    from bs4 import BeautifulSoup
    DEPS_OK = True
except ImportError:
    DEPS_OK = False

# ─── Konstanten ───────────────────────────────────────────────────────────────

APP_TITLE   = "Silverlight Site Finder"
APP_VERSION = "1.1.0"

# MIME-Typen die auf Silverlight hinweisen
SL_OBJECT_TYPES: Set[str] = {
    "application/x-silverlight",
    "application/x-silverlight-2",
}

# (Suchbegriff, Beschreibung, Konfidenz)
SL_INDICATORS: List[Tuple[str, str, str]] = [
    ("application/x-silverlight",   "MIME-Typ (object)",         "high"),
    ("application/x-silverlight-2", "MIME-Typ (object)",         "high"),
    (".xap",                        ".xap-Dateireferenz",        "high"),
    ("npctrl.dll",                  "Plugin-DLL (npctrl)",       "high"),
    ("agcore.dll",                  "Silverlight Core DLL",      "high"),
    ("Silverlight.js",              "Silverlight.js eingebunden","high"),
    ("silverlight.js",              "Silverlight.js eingebunden","high"),
    ("silverlightControlHost",      "Host-Container",            "medium"),
    ("SilverlightControlHost",      "Host-Container",            "medium"),
    ("Silverlight.isInstalled",     "Plugin-Erkennung",          "medium"),
    ("createSilverlight",           "createSilverlight()",       "medium"),
    ("Microsoft.Silverlight",       ".NET-Namespace-Referenz",   "medium"),
    ("initializeSilverlight",       "Initialisierung",           "medium"),
    ("SLPlugin",                    "SLPlugin-Referenz",         "medium"),
    ("System.Windows.Browser",      ".NET-Browser-Namespace",    "low"),
    ("MinRuntimeVersion",           "MinRuntimeVersion-Param",   "low"),
]

# Vorgefertigte Suchanfragen
SEARCH_DORKS: List[Tuple[str, str, str]] = [
    ("Bing",         'filetype:xap',
     "https://www.bing.com/search?q=filetype%3Axap"),
    ("Bing",         '"application/x-silverlight-2"',
     "https://www.bing.com/search?q=%22application%2Fx-silverlight-2%22"),
    ("Bing",         '"Silverlight.js" site:de',
     "https://www.bing.com/search?q=%22Silverlight.js%22+site%3Ade"),
    ("Bing",         '"silverlightControlHost"',
     "https://www.bing.com/search?q=%22silverlightControlHost%22"),
    ("Bing",         'Silverlight Unternehmensanwendung login',
     "https://www.bing.com/search?q=Silverlight+Unternehmensanwendung+login"),
    ("Bing",         'Silverlight HR-System intranet',
     "https://www.bing.com/search?q=Silverlight+HR-System+intranet"),
    ("Google",       'filetype:xap',
     "https://www.google.com/search?q=filetype:xap"),
    ("Google",       '"application/x-silverlight-2"',
     "https://www.google.com/search?q=%22application%2Fx-silverlight-2%22"),
    ("Google",       '"Silverlight.js"',
     "https://www.google.com/search?q=%22Silverlight.js%22"),
    ("Google",       '"silverlightControlHost" site:de OR site:at OR site:ch',
     "https://www.google.com/search?q=%22silverlightControlHost%22+site%3Ade+OR+site%3Aat+OR+site%3Ach"),
    ("Shodan",       'Silverlight HTTP-Title',
     "https://www.shodan.io/search?query=http.title%3ASilverlight"),
    ("Wayback Machine", '.xap Archiv-Suche',
     "https://web.archive.org/web/*/*.xap"),
    ("Common Crawl Index", '*.xap CDX-Suche',
     "https://index.commoncrawl.org/CC-MAIN-2020-05-index?url=*.xap&output=json&limit=50"),
]

DISCOVERY_QUERIES: List[str] = [
    '"application/x-silverlight-2"',
    '"silverlightControlHost"',
    '"Silverlight.js"',
    'filetype:xap',
    '"Silverlight.isInstalled"',
    '"createSilverlight"',
]

DISCOVERY_RELEVANCE_TOKENS: List[str] = [
    "silverlight",
    "silverlight.js",
    "xap",
    "silverlightcontrolhost",
    "application/x-silverlight",
    "createSilverlight",
    "silverlight.isinstalled",
]

# ─── Kern-Scanner ─────────────────────────────────────────────────────────────

class SilverlightScanner:
    """Scannt URLs und Domains auf Silverlight-Inhalte."""

    DEFAULT_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: int = 15, verify_ssl: bool = False,
                 max_crawl: int = 50):
        self.timeout    = timeout
        self.verify_ssl = verify_ssl
        self.max_crawl  = max_crawl
        self._session: Optional["requests.Session"] = None
        self._stop      = threading.Event()

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _get_session(self) -> "requests.Session":
        if self._session is None:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = self.DEFAULT_UA
        return self._session

    def stop(self):
        self._stop.set()

    def reset(self):
        self._stop.clear()

    def fetch(self, url: str) -> Tuple[Optional["requests.Response"], Optional[str]]:
        """Lädt eine URL. Gibt (Response, Fehler) zurück."""
        try:
            resp = self._get_session().get(
                url, timeout=self.timeout, verify=self.verify_ssl,
                allow_redirects=True, stream=False,
            )
            return resp, None
        except requests.exceptions.SSLError as e:
            return None, f"SSL-Fehler: {e}"
        except requests.exceptions.ConnectionError as e:
            return None, f"Verbindungsfehler: {e}"
        except requests.exceptions.Timeout:
            return None, "Timeout"
        except requests.exceptions.RequestException as e:
            return None, str(e)
        except Exception as e:
            return None, str(e)

    # ── Analyse ──────────────────────────────────────────────────────────────

    def analyze(self, url: str, response: "requests.Response") -> Dict:
        """Analysiert eine HTTP-Antwort auf Silverlight-Signaturen."""
        result: Dict = {
            "url":          url,
            "final_url":    response.url,
            "status_code":  response.status_code,
            "found":        False,
            "confidence":   "none",   # none | low | medium | high
            "indicators":   [],       # list of (label, confidence)
            "xap_files":    [],
            "title":        "",
            "scanned_at":   datetime.now().isoformat(),
        }

        ct = response.headers.get("content-type", "").lower()

        # Direkte .xap-Datei oder Silverlight-MIME im Header
        if ".xap" in response.url.lower() or "application/x-silverlight" in ct:
            result["found"] = True
            result["confidence"] = "high"
            result["indicators"].append((".xap / MIME-Header", "high"))
            return result

        # Nur HTML weiter analysieren
        if "text/html" not in ct and "application/xhtml" not in ct:
            return result

        try:
            html = response.text
        except Exception:
            return result

        # BeautifulSoup-Analyse
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            try:
                soup = BeautifulSoup(html, "html.parser")
            except Exception:
                soup = None

        if soup:
            # Seitentitel
            title_tag = soup.find("title")
            if title_tag:
                result["title"] = title_tag.get_text(strip=True)[:120]

            # <object type="application/x-silverlight*">
            for obj in soup.find_all("object"):
                obj_type = obj.get("type", "").lower()
                if obj_type in SL_OBJECT_TYPES:
                    result["indicators"].append((f"<object type='{obj_type}'>", "high"))
                    result["found"] = True
                # <param name="source" value="*.xap">
                for param in obj.find_all("param"):
                    pname = param.get("name", "").lower()
                    pval  = param.get("value", "")
                    if pname == "source" and pval.lower().endswith(".xap"):
                        result["indicators"].append((f"<param source='{pval}'>", "high"))
                        if pval not in result["xap_files"]:
                            result["xap_files"].append(pval)
                        result["found"] = True
                    elif pname == "minruntimeversion" and pval:
                        result["indicators"].append((f"MinRuntimeVersion={pval}", "medium"))
                        result["found"] = True

            # <script src="*.js"> auf Silverlight.js prüfen
            for script in soup.find_all("script"):
                src = script.get("src", "")
                if "silverlight.js" in src.lower():
                    result["indicators"].append((f'<script src="{src}">', "high"))
                    result["found"] = True

            # <embed> tags
            for embed in soup.find_all("embed"):
                etype = embed.get("type", "").lower()
                if etype in SL_OBJECT_TYPES:
                    result["indicators"].append((f"<embed type='{etype}'>", "high"))
                    result["found"] = True

        # Roher HTML-Keyword-Scan
        for keyword, label, confidence in SL_INDICATORS:
            if keyword in html:
                entry = (f"{label} [{keyword!r}]", confidence)
                if entry not in result["indicators"]:
                    result["indicators"].append(entry)
                    result["found"] = True

        # Konfidenz-Aggregat
        if result["found"]:
            confs = [c for _, c in result["indicators"]]
            if "high" in confs:
                result["confidence"] = "high"
            elif "medium" in confs:
                result["confidence"] = "medium"
            else:
                result["confidence"] = "low"

        return result

    def _make_empty_error(self, url: str, error: str) -> Dict:
        return {
            "url": url, "final_url": url, "status_code": 0,
            "found": False, "confidence": "none", "indicators": [],
            "xap_files": [], "title": "", "error": error,
            "scanned_at": datetime.now().isoformat(),
        }

    # ── URL-Liste scannen ────────────────────────────────────────────────────

    def scan_urls(self, urls: List[str], progress_cb=None) -> List[Dict]:
        results = []
        total   = len(urls)
        for i, url in enumerate(urls):
            if self._stop.is_set():
                break
            clean_url = (url or "").strip()
            if not clean_url:
                continue
            if "://" in clean_url:
                scheme, rest = clean_url.split("://", 1)
                clean_url = f"{scheme.lower()}://{rest}"
            else:
                clean_url = "https://" + clean_url
            if progress_cb:
                progress_cb(i + 1, total, clean_url)
            resp, err = self.fetch(clean_url)
            results.append(self._make_empty_error(clean_url, err) if err
                           else self.analyze(clean_url, resp))
        return results

    # ── Domain crawlen ───────────────────────────────────────────────────────

    def crawl_domain(self, base_url: str, max_pages: int, progress_cb=None) -> List[Dict]:
        clean_base = (base_url or "").strip()
        if not clean_base:
            return []
        if "://" in clean_base:
            scheme, rest = clean_base.split("://", 1)
            clean_base = f"{scheme.lower()}://{rest}"
        else:
            clean_base = "https://" + clean_base

        base_netloc = urlparse(clean_base).netloc
        visited:  Set[str]  = set()
        to_visit: List[str] = [clean_base]
        to_visit: List[str] = [base_url]
        results:  List[Dict] = []
        count = 0

        while to_visit and count < max_pages and not self._stop.is_set():
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)
            count += 1

            if progress_cb:
                progress_cb(count, max_pages, url)

            resp, err = self.fetch(url)
            if err:
                results.append(self._make_empty_error(url, err))
                continue

            r = self.analyze(url, resp)
            results.append(r)

            # Links auf gleicher Domain extrahieren
            if count < max_pages:
                try:
                    ct = resp.headers.get("content-type", "")
                    if "text/html" in ct:
                        soup = BeautifulSoup(resp.text, "lxml")
                        for a in soup.find_all("a", href=True):
                            abs_url = urljoin(url, a["href"]).split("#")[0]
                            p = urlparse(abs_url)
                            if (p.netloc == base_netloc
                                    and abs_url not in visited
                                    and abs_url not in to_visit
                                    and p.scheme in ("http", "https")):
                                to_visit.append(abs_url)
                except Exception:
                    pass

        return results

    # ── Automatische Kandidaten-Suche ──────────────────────────────────────

    def _normalize_url(self, candidate: str) -> Optional[str]:
        candidate = candidate.strip()
        if not candidate:
            return None
        if candidate.startswith("//"):
            candidate = "https:" + candidate

        if "://" in candidate:
            scheme, rest = candidate.split("://", 1)
            if not scheme:
                return None
            candidate = f"{scheme.lower()}://{rest}"
        else:
            candidate = "https://" + candidate

        p = urlparse(candidate)
        if not p.netloc:
            return None
        cleaned = candidate.split("#")[0].strip()
        if cleaned.endswith("/") and p.path == "/":
            cleaned = cleaned[:-1]
        return cleaned

    def _matches_scope(self, url: str, scope: str) -> bool:
        if not scope:
            return True
        host = (urlparse(url).netloc or "").lower()
        scope = scope.lower().strip()
        if not scope:
            return True
        return host == scope or host.endswith("." + scope)

    def _discover_bing_rss(self, scope: str, max_results: int,
                           progress_cb=None) -> List[str]:
        found: List[str] = []
        seen: Set[str] = set()
        total_queries = len(DISCOVERY_QUERIES)

        for idx, base_query in enumerate(DISCOVERY_QUERIES):
            if self._stop.is_set() or len(found) >= max_results:
                break

            query = base_query
            if scope:
                query += f" site:{scope}"

            if progress_cb:
                progress_cb(idx + 1, total_queries, f"Bing RSS: {query}")

            try:
                resp = self._get_session().get(
                    "https://www.bing.com/search",
                    params={"q": query, "format": "rss", "count": "50"},
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                )
                if resp.status_code != 200:
                    continue

                try:
                    root = ET.fromstring(resp.text)
                except Exception:
                    continue

                for item in root.findall(".//item"):
                    if self._stop.is_set() or len(found) >= max_results:
                        break

                    title = (item.findtext("title") or "").strip()
                    desc = (item.findtext("description") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    haystack = f"{title} {desc} {link}".lower()

                    if not any(token.lower() in haystack for token in DISCOVERY_RELEVANCE_TOKENS):
                        continue

                    candidate = link
                    normalized = self._normalize_url(candidate)
                    if not normalized:
                        continue
                    if not self._matches_scope(normalized, scope):
                        continue
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    found.append(normalized)
            except Exception:
                continue

        return found

    def _discover_wayback(self, scope: str, max_results: int,
                          progress_cb=None) -> List[str]:
        found: List[str] = []
        seen: Set[str] = set()

        patterns = [
            "*.xap",
            "*/Silverlight.js",
            "*/silverlight.js",
        ]
        if scope:
            patterns = [
                f"*.{scope}/*.xap",
                f"*.{scope}/*Silverlight.js*",
            ]

        for idx, pattern in enumerate(patterns):
            if self._stop.is_set() or len(found) >= max_results:
                break

            if progress_cb:
                progress_cb(idx + 1, len(patterns), f"Wayback CDX: {pattern}")

            try:
                resp = self._get_session().get(
                    "https://web.archive.org/cdx/search/cdx",
                    params={
                        "url": pattern,
                        "output": "json",
                        "fl": "original",
                        "filter": "statuscode:200",
                        "limit": str(max_results * 3),
                        "collapse": "urlkey",
                    },
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                )
                if resp.status_code != 200:
                    continue

                try:
                    rows = resp.json()
                except Exception:
                    continue

                if not isinstance(rows, list) or len(rows) <= 1:
                    continue

                for row in rows[1:]:
                    if self._stop.is_set() or len(found) >= max_results:
                        break
                    if not isinstance(row, list) or not row:
                        continue
                    candidate = str(row[0]).strip()
                    normalized = self._normalize_url(candidate)
                    if not normalized:
                        continue
                    if not self._matches_scope(normalized, scope):
                        continue
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    found.append(normalized)
            except Exception:
                continue

        return found

    def discover_candidates(self, scope: str = "", max_results: int = 60,
                            use_bing: bool = True, use_wayback: bool = True,
                            progress_cb=None) -> List[str]:
        """Findet potenzielle Silverlight-URLs ohne manuelle Eingabe."""
        scope = scope.strip()
        max_results = max(1, max_results)

        all_found: List[str] = []
        seen: Set[str] = set()

        if use_bing and not self._stop.is_set():
            bing_urls = self._discover_bing_rss(scope, max_results, progress_cb=progress_cb)
            for u in bing_urls:
                if u not in seen:
                    seen.add(u)
                    all_found.append(u)
                    if len(all_found) >= max_results:
                        return all_found

        if use_wayback and not self._stop.is_set():
            wayback_urls = self._discover_wayback(scope, max_results, progress_cb=progress_cb)
            for u in wayback_urls:
                if u not in seen:
                    seen.add(u)
                    all_found.append(u)
                    if len(all_found) >= max_results:
                        return all_found

        return all_found


# ─── IE-Modus-Helfer ──────────────────────────────────────────────────────────

def generate_ie_site_list(urls: List[str]) -> str:
    """Generiert eine Edge Enterprise Mode Site List (v2) als XML."""
    root = ET.Element("site-list", version="205")
    cb   = ET.SubElement(root, "created-by")
    ET.SubElement(cb, "tool").text         = APP_TITLE
    ET.SubElement(cb, "version").text      = APP_VERSION
    ET.SubElement(cb, "date-created").text = datetime.now().strftime("%Y-%m-%d")

    for url in urls:
        parsed = urlparse(url if "://" in url else "https://" + url)
        domain = parsed.netloc or url
        site   = ET.SubElement(root, "site", url=domain)
        ET.SubElement(site, "compat-mode").text = "IE11"
        ET.SubElement(site, "open-in").text     = "IE11"

    raw = ET.tostring(root, encoding="unicode")
    try:
        return minidom.parseString(raw).toprettyxml(indent="  ")
    except Exception:
        return raw


def open_in_edge(url: str) -> None:
    """Öffnet eine URL in Microsoft Edge."""
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in edge_candidates:
        if os.path.exists(path):
            subprocess.Popen([path, url])
            return
    webbrowser.open(url)


# ─── GUI ──────────────────────────────────────────────────────────────────────

# Catppuccin Mocha Farbpalette
C = {
    "base":    "#1e1e2e",
    "mantle":  "#181825",
    "surface": "#313244",
    "overlay": "#45475a",
    "text":    "#cdd6f4",
    "subtext": "#a6adc8",
    "blue":    "#89b4fa",
    "sky":     "#89dceb",
    "green":   "#a6e3a1",
    "yellow":  "#f9e2af",
    "peach":   "#fab387",
    "red":     "#f38ba8",
    "mauve":   "#cba6f7",
    "teal":    "#94e2d5",
}

CONF_LABELS = {
    "high":   "★★★  Hoch",
    "medium": "★★    Mittel",
    "low":    "★      Niedrig",
    "none":   "—      Keine",
}

IE_MODE_INSTRUCTIONS = """\
════════════════════════════════════════════════════════
  SILVERLIGHT MIT EDGE IE-MODUS NUTZEN – SCHRITT FÜR SCHRITT
════════════════════════════════════════════════════════

SCHRITT 1 – SILVERLIGHT INSTALLIEREN
  Silverlight 5 wird offiziell nicht mehr vertrieben, aber:
  • Archivkopien über web.archive.org (Schaltfläche unten)
  • Interne Software-Verteilung (IT-Abteilung)
  • Hinweis: Silverlight-DLL (npctrl.dll) muss registriert sein

SCHRITT 2 – IE-MODUS IN EDGE AKTIVIEREN
  1. Edge öffnen → Einstellungen (⋯ oben rechts)
  2. → Standardbrowser → Internet Explorer-Kompatibilität
  3. "Websites in Internet Explorer-Modus neu laden zulassen" → AN
  4. Edge neu starten

SCHRITT 3 – SEITE IM IE-MODUS ÖFFNEN
  Methode A – Manuell (einmalig):
    • Zur Silverlight-Seite navigieren
    • ⋯ → „In Internet Explorer-Modus neu laden"
    • Die Seite öffnet sich mit dem IE-Engine (Trident)

  Methode B – Dauerhaft über die Kompatibilitätsliste:
    • edge://settings/defaultBrowser öffnen
    • Unter „Seiten in Internet Explorer-Modus öffnen"
      die URL manuell eintragen  ODER
    • Eine Enterprise Site List XML einbinden (siehe unten)

SCHRITT 4 – ENTERPRISE SITE LIST (für IT-Admins)
  Die XML-Datei (rechts generierbar) kann über:
  • Group Policy: „InternetExplorerIntegrationSiteList"
  • Registry:
    HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge
    → InternetExplorerIntegrationLevel = 1
    → InternetExplorerIntegrationSiteList = "file:///C:/SiteList.xml"
  eingebunden werden. Edge lädt die Seiten dann automatisch im IE-Modus.

SCHRITT 5 – SILVERLIGHT-PLUG-IN IM IE-MODUS ÜBERPRÜFEN
  Im IE-Modus → Extras (Zahnrad) → Add-On-Verwaltung
  → „Microsoft Silverlight" muss als Aktiviert erscheinen
════════════════════════════════════════════════════════
"""

TIPS_TEXT = """\
TIPPS ZUM AUFFINDEN VON SILVERLIGHT-WEBANWENDUNGEN
═══════════════════════════════════════════════════

Typische Einsatzgebiete (2008–2016):

  • HR- & ERP-Systeme     SAP Enterprise Portal, ADP, Sage, Navision-Frontends
  • Behördenportale       E-Government-Lösungen (vor 2017), Steuerbehörden
  • Medizin / PACS        Radiologische Bildbetrachtungssysteme (Viewer)
  • Lernmanagementsysteme Moodle-Plugins, Blackboard, Meridian LMS
  • GIS-Anwendungen       Kartendienste auf Silverlight-Basis
  • Finanz-Dashboards     Reporting-Tools, Business Intelligence
  • Streaming-Dienste     Ältere Netflix-/IIS Smooth Streaming-Clients

Manuelle Erkundung:
  • robots.txt und sitemap.xml auf .xap-Pfade prüfen
  • Browser-Dev-Tools → Network → nach .xap filtern
  • Wayback Machine: web.archive.org/web/*/*.xap
  • Shodan-Suche: http.title:Silverlight oder http.html:silverlightControlHost

Search-Dork-Beispiele:
  • Google:  "application/x-silverlight-2" site:example.com
  • Google:  intitle:"Silverlight" filetype:xap
  • Bing:    url:*.xap
  • GitHub:  extension:xap filename:.xap (archivierte Projekte)
"""


class App(tk.Tk):
    """Hauptfenster der Anwendung."""

    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry("1150x780")
        self.minsize(900, 620)
        self.configure(bg=C["base"])

        self.scanner    = SilverlightScanner()
        self.results:   List[Dict]              = []
        self.scan_thread: Optional[threading.Thread] = None
        self._dork_map: Dict[str, str]          = {}   # treeview iid → URL

        self._build_style()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        if not DEPS_OK:
            self.after(500, self._warn_deps)

    # ── Stil ─────────────────────────────────────────────────────────────────

    def _build_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TNotebook",        background=C["base"],    borderwidth=0)
        s.configure("TNotebook.Tab",    background=C["surface"], foreground=C["text"],
                    padding=[14, 7],    font=("Segoe UI", 10))
        s.map("TNotebook.Tab",
              background=[("selected", C["blue"])],
              foreground=[("selected", C["base"])])
        s.configure("TFrame",           background=C["base"])
        s.configure("TLabel",           background=C["base"],    foreground=C["text"],
                    font=("Segoe UI", 10))
        s.configure("TButton",          background=C["blue"],    foreground=C["base"],
                    font=("Segoe UI", 10, "bold"), padding=[10, 5])
        s.map("TButton",                background=[("active",   C["sky"]),
                                                    ("disabled", C["overlay"])])
        s.configure("danger.TButton",   background=C["red"],     foreground=C["base"],
                    font=("Segoe UI", 10, "bold"), padding=[10, 5])
        s.map("danger.TButton",         background=[("active", "#ff6e85")])
        s.configure("success.TButton",  background=C["green"],   foreground=C["base"],
                    font=("Segoe UI", 10, "bold"), padding=[10, 5])
        s.map("success.TButton",        background=[("active", "#b5f0aa")])
        s.configure("small.TButton",    background=C["surface"], foreground=C["text"],
                    font=("Segoe UI", 9), padding=[6, 3])
        s.configure("TCheckbutton",     background=C["base"],    foreground=C["text"],
                    font=("Segoe UI", 10))
        s.configure("TEntry",           fieldbackground=C["surface"], foreground=C["text"],
                    insertcolor=C["text"], borderwidth=0)
        s.configure("TSeparator",       background=C["overlay"])
        s.configure("Treeview",         background=C["surface"], foreground=C["text"],
                    fieldbackground=C["surface"], rowheight=22, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", background=C["overlay"], foreground=C["text"],
                    font=("Segoe UI", 9, "bold"))
        s.map("Treeview",
              background=[("selected", C["blue"])],
              foreground=[("selected", C["base"])])
        s.configure("Horizontal.TProgressbar", troughcolor=C["surface"],
                    background=C["blue"], borderwidth=0)
        s.configure("TScrollbar",       background=C["overlay"], troughcolor=C["surface"],
                    borderwidth=0, arrowcolor=C["text"])

    # ── Header ───────────────────────────────────────────────────────────────

    def _build_header(self):
        bar = tk.Frame(self, bg=C["blue"], height=52)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)
        tk.Label(bar, text=f"  ◈  {APP_TITLE}",
                 bg=C["blue"], fg=C["base"], font=("Segoe UI", 15, "bold")).pack(side=tk.LEFT, padx=14)
        tk.Label(bar, text="Entdecke und öffne veraltete Silverlight-Webanwendungen",
                 bg=C["blue"], fg=C["mantle"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=2)

    # ── Notebook ─────────────────────────────────────────────────────────────

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._tab_scanner()
        self._tab_results()
        self._tab_search()
        self._tab_ie_mode()

    # ── Statusleiste ─────────────────────────────────────────────────────────

    def _build_statusbar(self):
        self._status_var = tk.StringVar(value="Bereit.")
        bar = tk.Frame(self, bg=C["mantle"], height=26)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        tk.Label(bar, textvariable=self._status_var,
                 bg=C["mantle"], fg=C["subtext"], font=("Segoe UI", 9),
                 anchor=tk.W).pack(fill=tk.X, padx=10)

    def _warn_deps(self):
        messagebox.showwarning(
            "Pakete fehlen",
            "Die folgenden Python-Pakete werden benötigt:\n\n"
            "    pip install requests beautifulsoup4 lxml\n\n"
            "Bitte installieren und das Programm neu starten.\n"
            "(Die Oberfläche ist trotzdem nutzbar, der Scanner funktioniert jedoch nicht.)"
        )

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 1 – Scanner
    # ═════════════════════════════════════════════════════════════════════════

    def _tab_scanner(self):
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text="  Scanner  ")

        # ── Obere Hälfte: Input + Log ────────────────────────────────────────
        top = ttk.Frame(frame)
        top.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Links: URL-Eingabe
        left = ttk.Frame(top)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        ttk.Label(left, text="URLs scannen  (eine pro Zeile):").pack(anchor=tk.W)
        self._url_input = scrolledtext.ScrolledText(
            left, height=10, bg=C["surface"], fg=C["text"],
            insertbackground=C["text"], font=("Consolas", 10),
            relief=tk.FLAT, borderwidth=4,
        )
        self._url_input.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

        # Domain-Crawl-Zeile
        cframe = ttk.Frame(left)
        cframe.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(cframe, text="Domain crawlen:").pack(side=tk.LEFT)
        self._crawl_var = tk.StringVar()
        ttk.Entry(cframe, textvariable=self._crawl_var, width=34).pack(side=tk.LEFT, padx=6)
        ttk.Label(cframe, text="Max. Seiten:").pack(side=tk.LEFT)
        self._maxpages_var = tk.StringVar(value="30")
        ttk.Entry(cframe, textvariable=self._maxpages_var, width=5).pack(side=tk.LEFT, padx=4)

        # Optionen
        oframe = ttk.Frame(left)
        oframe.pack(fill=tk.X, pady=(0, 8))
        self._ssl_var     = tk.BooleanVar(value=False)
        self._timeout_var = tk.StringVar(value="15")
        ttk.Checkbutton(oframe, text="SSL verifizieren", variable=self._ssl_var).pack(side=tk.LEFT)
        ttk.Label(oframe, text="   Timeout (s):").pack(side=tk.LEFT)
        ttk.Entry(oframe, textvariable=self._timeout_var, width=4).pack(side=tk.LEFT, padx=4)

        # Auto-Discovery
        adf = ttk.Frame(left)
        adf.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(adf, text="Auto-Suche Scope (optional):").pack(side=tk.LEFT)
        self._disc_scope_var = tk.StringVar(value="")
        ttk.Entry(adf, textvariable=self._disc_scope_var, width=24).pack(side=tk.LEFT, padx=6)
        ttk.Label(adf, text="Max. Kandidaten:").pack(side=tk.LEFT)
        self._disc_max_var = tk.StringVar(value="40")
        ttk.Entry(adf, textvariable=self._disc_max_var, width=5).pack(side=tk.LEFT, padx=4)

        adf2 = ttk.Frame(left)
        adf2.pack(fill=tk.X, pady=(0, 8))
        self._disc_bing_var = tk.BooleanVar(value=True)
        self._disc_wayback_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(adf2, text="Bing RSS", variable=self._disc_bing_var).pack(side=tk.LEFT)
        ttk.Checkbutton(adf2, text="Wayback CDX", variable=self._disc_wayback_var).pack(side=tk.LEFT, padx=8)

        # Schaltflächen
        bframe = ttk.Frame(left)
        bframe.pack(fill=tk.X)
        self._btn_scan = ttk.Button(bframe, text="▶  URLs scannen",   command=self._start_url_scan)
        self._btn_crawl = ttk.Button(bframe, text="🕷  Domain crawlen", command=self._start_crawl)
        self._btn_auto_fill = ttk.Button(
            bframe, text="✨  Adressen finden", command=self._start_auto_discovery_only
        )
        self._btn_auto_scan = ttk.Button(
            bframe, text="🚀  Finden + Scannen", command=self._start_auto_discovery_scan,
            style="success.TButton"
        )
        self._btn_stop  = ttk.Button(bframe, text="■  Stopp",          command=self._stop_scan,
                                     style="danger.TButton", state=tk.DISABLED)
        self._btn_scan.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_crawl.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_auto_fill.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_auto_scan.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_stop.pack(side=tk.LEFT)

        # Rechts: Log
        right = ttk.Frame(top)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        ttk.Label(right, text="Scan-Log:").pack(anchor=tk.W)
        self._log = scrolledtext.ScrolledText(
            right, height=18, bg=C["mantle"], fg=C["green"],
            font=("Consolas", 9), relief=tk.FLAT, borderwidth=4,
            state=tk.DISABLED,
        )
        self._log.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # ── Fortschrittsbalken ───────────────────────────────────────────────
        self._progress_var = tk.DoubleVar()
        ttk.Progressbar(frame, variable=self._progress_var, maximum=100,
                        style="Horizontal.TProgressbar").pack(fill=tk.X, padx=10, pady=(0, 4))

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 2 – Ergebnisse
    # ═════════════════════════════════════════════════════════════════════════

    def _tab_results(self):
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text="  Ergebnisse  ")

        # Toolbar
        tb = ttk.Frame(frame)
        tb.pack(fill=tk.X, padx=8, pady=6)
        self._show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(tb, text="Alle URLs anzeigen (auch ohne Silverlight)",
                        variable=self._show_all, command=self._refresh).pack(side=tk.LEFT)
        ttk.Button(tb, text="🔄  Aktualisieren", command=self._refresh,
                   style="small.TButton").pack(side=tk.LEFT, padx=6)
        ttk.Button(tb, text="💾  JSON",         command=self._export_json,
                   style="small.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="💾  CSV",          command=self._export_csv,
                   style="small.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="🗑  Löschen",      command=self._clear_results,
                   style="danger.TButton").pack(side=tk.RIGHT, padx=4)
        self._count_var = tk.StringVar(value="Keine Ergebnisse")
        ttk.Label(tb, textvariable=self._count_var,
                  foreground=C["blue"]).pack(side=tk.RIGHT, padx=8)

        # Treeview
        cols = ("conf", "url", "title", "code", "indicators")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self._tree.heading("conf",       text="Konfidenz",   anchor=tk.CENTER)
        self._tree.heading("url",        text="URL")
        self._tree.heading("title",      text="Seitentitel")
        self._tree.heading("code",       text="HTTP",        anchor=tk.CENTER)
        self._tree.heading("indicators", text="Erkannte Indikatoren")
        self._tree.column("conf",       width=110, anchor=tk.CENTER, stretch=False)
        self._tree.column("url",        width=330)
        self._tree.column("title",      width=190)
        self._tree.column("code",       width=55,  anchor=tk.CENTER, stretch=False)
        self._tree.column("indicators", width=380)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL,   command=self._tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.pack(side=tk.TOP,    fill=tk.BOTH, expand=True, padx=8)
        vsb.pack(side=tk.RIGHT,         fill=tk.Y)
        hsb.pack(side=tk.BOTTOM,        fill=tk.X,    padx=8)

        # Farb-Tags
        self._tree.tag_configure("high",   foreground=C["red"])
        self._tree.tag_configure("medium", foreground=C["peach"])
        self._tree.tag_configure("low",    foreground=C["yellow"])
        self._tree.tag_configure("none",   foreground=C["overlay"])

        # Aktionsleiste
        af = ttk.Frame(frame)
        af.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(af, text="🌐  In Edge öffnen",        command=self._open_in_edge).pack(side=tk.LEFT, padx=2)
        ttk.Button(af, text="📋  URL kopieren",          command=self._copy_url).pack(side=tk.LEFT, padx=2)
        ttk.Button(af, text="🔍  Details",               command=self._show_details).pack(side=tk.LEFT, padx=2)
        ttk.Button(af, text="🛡  Für IE-Modus vormerken",
                   command=self._mark_ie, style="success.TButton").pack(side=tk.LEFT, padx=6)

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 3 – Web-Suche
    # ═════════════════════════════════════════════════════════════════════════

    def _tab_search(self):
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text="  Web-Suche  ")

        ttk.Label(frame,
                  text="Vorgefertigte Suchanfragen (Doppelklick oder Schaltfläche zum Öffnen):",
                  font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 4))

        # Dorks-Tabelle
        dcols = ("engine", "dork")
        dtree = ttk.Treeview(frame, columns=dcols, show="headings",
                             height=min(len(SEARCH_DORKS), 14))
        dtree.heading("engine", text="Engine",       anchor=tk.CENTER)
        dtree.heading("dork",   text="Suchanfrage / Dork")
        dtree.column("engine",  width=130, anchor=tk.CENTER, stretch=False)
        dtree.column("dork",    width=600)

        for engine, dork, url in SEARCH_DORKS:
            iid = dtree.insert("", tk.END, values=(engine, dork))
            self._dork_map[iid] = url

        vsb2 = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=dtree.yview)
        dtree.configure(yscrollcommand=vsb2.set)
        dtree.pack(fill=tk.X, padx=12, pady=2)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        dtree.bind("<Double-1>", lambda _: self._open_dork(dtree))

        btn_f = ttk.Frame(frame)
        btn_f.pack(fill=tk.X, padx=12, pady=4)
        ttk.Button(btn_f, text="Ausgewählte Suche im Browser öffnen →",
                   command=lambda: self._open_dork(dtree)).pack(side=tk.LEFT)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=12, pady=10)

        # Eigene Suche
        ttk.Label(frame, text="Eigene Suche:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=12)
        cf = ttk.Frame(frame)
        cf.pack(fill=tk.X, padx=12, pady=4)
        self._custom_search = tk.StringVar()
        ttk.Entry(cf, textvariable=self._custom_search, width=55).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(cf, text="Bing",   command=lambda: webbrowser.open(
            "https://www.bing.com/search?q=" + quote(self._custom_search.get())
        )).pack(side=tk.LEFT, padx=2)
        ttk.Button(cf, text="Google", command=lambda: webbrowser.open(
            "https://www.google.com/search?q=" + quote(self._custom_search.get())
        )).pack(side=tk.LEFT, padx=2)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=12, pady=10)

        # Tipps
        tips = scrolledtext.ScrolledText(
            frame, height=14, bg=C["mantle"], fg=C["text"],
            font=("Consolas", 9), relief=tk.FLAT, borderwidth=4,
        )
        tips.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        tips.insert(tk.END, TIPS_TEXT)
        tips.config(state=tk.DISABLED)

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 4 – IE-Modus
    # ═════════════════════════════════════════════════════════════════════════

    def _tab_ie_mode(self):
        frame = ttk.Frame(self.nb)
        self.nb.add(frame, text="  IE-Modus  ")

        # Anleitung
        instr = scrolledtext.ScrolledText(
            frame, height=16, bg=C["mantle"], fg=C["text"],
            font=("Consolas", 9), relief=tk.FLAT, borderwidth=4,
        )
        instr.pack(fill=tk.X, padx=12, pady=(10, 4))
        instr.insert(tk.END, IE_MODE_INSTRUCTIONS)
        instr.config(state=tk.DISABLED)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=12, pady=6)

        # IE-Modus-URLs
        ttk.Label(frame, text="Für IE-Modus vorgemerkte URLs:",
                  font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=12)
        self._ie_urls = scrolledtext.ScrolledText(
            frame, height=5, bg=C["surface"], fg=C["text"],
            insertbackground=C["text"], font=("Consolas", 10),
            relief=tk.FLAT, borderwidth=4,
        )
        self._ie_urls.pack(fill=tk.X, padx=12, pady=4)

        # Schaltflächen
        bf = ttk.Frame(frame)
        bf.pack(fill=tk.X, padx=12, pady=4)
        ttk.Button(bf, text="📄  Site List XML generieren",
                   command=self._gen_xml).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bf, text="⚙  Edge-Einstellungen öffnen",
                   command=lambda: open_in_edge("edge://settings/defaultBrowser"),
                   style="small.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="📥  Silverlight-Archiv (Wayback)",
                   command=lambda: webbrowser.open(
                       "https://web.archive.org/web/2019*/https://www.microsoft.com/silverlight/"
                   ), style="small.TButton").pack(side=tk.LEFT, padx=2)

        # XML-Ausgabe
        ttk.Label(frame, text="Generierte Enterprise Mode Site List XML:").pack(anchor=tk.W, padx=12, pady=(8, 2))
        self._xml_out = scrolledtext.ScrolledText(
            frame, height=8, bg=C["mantle"], fg=C["green"],
            font=("Consolas", 9), relief=tk.FLAT, borderwidth=4,
            state=tk.DISABLED,
        )
        self._xml_out.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

        xbf = ttk.Frame(frame)
        xbf.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Button(xbf, text="💾  XML speichern", command=self._save_xml).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(xbf, text="📋  Kopieren",      command=self._copy_xml,
                   style="small.TButton").pack(side=tk.LEFT)

    # ═════════════════════════════════════════════════════════════════════════
    # Scanner-Logik
    # ═════════════════════════════════════════════════════════════════════════

    def _log_msg(self, msg: str):
        def _do():
            self._log.config(state=tk.NORMAL)
            ts = datetime.now().strftime("%H:%M:%S")
            self._log.insert(tk.END, f"[{ts}]  {msg}\n")
            self._log.see(tk.END)
            self._log.config(state=tk.DISABLED)
        self.after(0, _do)

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status_var.set(msg))

    def _set_progress(self, pct: float):
        self.after(0, lambda: self._progress_var.set(pct))

    def _set_scanning(self, active: bool):
        s_off = tk.DISABLED if active else tk.NORMAL
        s_on  = tk.NORMAL   if active else tk.DISABLED
        def _do():
            self._btn_scan.config(state=s_off)
            self._btn_crawl.config(state=s_off)
            self._btn_auto_fill.config(state=s_off)
            self._btn_auto_scan.config(state=s_off)
            self._btn_stop.config(state=s_on)
        self.after(0, _do)

    def _get_timeout(self) -> int:
        try:
            return max(1, int(self._timeout_var.get()))
        except ValueError:
            return 15

    def _start_url_scan(self):
        if not DEPS_OK:
            messagebox.showerror("Fehler", "Pakete nicht installiert:\npip install requests beautifulsoup4 lxml")
            return
        urls = [u.strip() for u in self._url_input.get("1.0", tk.END).splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("Hinweis", "Bitte mindestens eine URL eingeben.")
            return
        self.scanner.reset()
        self.scanner.verify_ssl = self._ssl_var.get()
        self.scanner.timeout    = self._get_timeout()
        self._set_scanning(True)
        self._log_msg(f"Starte URL-Scan: {len(urls)} Einträge")
        self.scan_thread = threading.Thread(target=self._run_url_scan, args=(urls,), daemon=True)
        self.scan_thread.start()

    def _get_discovery_limit(self) -> int:
        try:
            return max(1, int(self._disc_max_var.get()))
        except ValueError:
            return 40

    def _start_auto_discovery_only(self):
        if not DEPS_OK:
            messagebox.showerror("Fehler", "Pakete nicht installiert:\npip install requests beautifulsoup4 lxml")
            return
        if not self._disc_bing_var.get() and not self._disc_wayback_var.get():
            messagebox.showwarning("Hinweis", "Bitte mindestens eine Quelle aktivieren (Bing RSS oder Wayback CDX).")
            return

        self.scanner.reset()
        self.scanner.verify_ssl = self._ssl_var.get()
        self.scanner.timeout    = self._get_timeout()
        self._set_scanning(True)
        self._set_progress(0)

        scope = self._disc_scope_var.get().strip()
        limit = self._get_discovery_limit()
        self._log_msg(f"Starte Auto-Suche: scope='{scope or 'global'}', limit={limit}")

        self.scan_thread = threading.Thread(
            target=self._run_auto_discovery,
            args=(scope, limit, False),
            daemon=True,
        )
        self.scan_thread.start()

    def _start_auto_discovery_scan(self):
        if not DEPS_OK:
            messagebox.showerror("Fehler", "Pakete nicht installiert:\npip install requests beautifulsoup4 lxml")
            return
        if not self._disc_bing_var.get() and not self._disc_wayback_var.get():
            messagebox.showwarning("Hinweis", "Bitte mindestens eine Quelle aktivieren (Bing RSS oder Wayback CDX).")
            return

        self.scanner.reset()
        self.scanner.verify_ssl = self._ssl_var.get()
        self.scanner.timeout    = self._get_timeout()
        self._set_scanning(True)
        self._set_progress(0)

        scope = self._disc_scope_var.get().strip()
        limit = self._get_discovery_limit()
        self._log_msg(f"Starte Auto-Suche + Scan: scope='{scope or 'global'}', limit={limit}")

        self.scan_thread = threading.Thread(
            target=self._run_auto_discovery,
            args=(scope, limit, True),
            daemon=True,
        )
        self.scan_thread.start()

    def _set_url_input(self, urls: List[str], append: bool = True):
        def _do():
            if not append:
                self._url_input.delete("1.0", tk.END)
            existing = {u.strip() for u in self._url_input.get("1.0", tk.END).splitlines() if u.strip()}
            for u in urls:
                if u not in existing:
                    self._url_input.insert(tk.END, u + "\n")
                    existing.add(u)
        self.after(0, _do)

    def _run_auto_discovery(self, scope: str, limit: int, scan_after: bool):
        def _dcb(i, total, msg):
            self._set_status(f"Suche {i}/{total}: {msg[:80]}")
            if total > 0:
                self._set_progress(i / total * 30)

        discovered = self.scanner.discover_candidates(
            scope=scope,
            max_results=limit,
            use_bing=self._disc_bing_var.get(),
            use_wayback=self._disc_wayback_var.get(),
            progress_cb=_dcb,
        )

        if self.scanner._stop.is_set():
            self._log_msg("⏹  Auto-Suche gestoppt.")
            self._set_scanning(False)
            self._set_status("Gestoppt.")
            return

        self._set_url_input(discovered, append=True)
        self._log_msg(f"Auto-Suche abgeschlossen: {len(discovered)} Kandidaten gefunden.")

        if not scan_after:
            self._set_progress(100)
            self._set_scanning(False)
            self._set_status(f"Auto-Suche fertig: {len(discovered)} Kandidaten gefunden.")
            return

        if not discovered:
            self._set_progress(100)
            self._set_scanning(False)
            self._set_status("Keine Kandidaten für Scan gefunden.")
            return

        known = {
            (r.get("url") or "").strip() for r in self.results
        } | {
            (r.get("final_url") or "").strip() for r in self.results
        }
        to_scan = [u for u in discovered if u not in known]

        if not to_scan:
            self._set_progress(100)
            self._set_scanning(False)
            self._set_status("Alle gefundenen Kandidaten wurden bereits gescannt.")
            self._log_msg("Keine neuen URLs für Scan übrig (bereits vorhanden).")
            return

        self._log_msg(f"Starte Scan der gefundenen Kandidaten: {len(to_scan)} URLs")

        def _scb(i, total, url):
            self._set_progress(30 + (i / total * 70))
            self._set_status(f"Scanne {i}/{total}: {url[:90]}")
            self._log_msg(f"→ {url}")

        new = self.scanner.scan_urls(to_scan, progress_cb=_scb)
        self._finish_scan(new)

    def _run_url_scan(self, urls: List[str]):
        def _cb(i, total, url):
            self._set_progress(i / total * 100)
            self._set_status(f"Scanne {i}/{total}: {url[:90]}")
            self._log_msg(f"→ {url}")
        new = self.scanner.scan_urls(urls, progress_cb=_cb)
        self._finish_scan(new)

    def _start_crawl(self):
        if not DEPS_OK:
            messagebox.showerror("Fehler", "Pakete nicht installiert:\npip install requests beautifulsoup4 lxml")
            return
        domain = self._crawl_var.get().strip()
        if not domain:
            messagebox.showwarning("Hinweis", "Bitte eine Domain zum Crawlen eingeben.")
            return
        try:
            max_p = max(1, int(self._maxpages_var.get()))
        except ValueError:
            max_p = 30
        self.scanner.reset()
        self.scanner.verify_ssl = self._ssl_var.get()
        self.scanner.timeout    = self._get_timeout()
        self.scanner.max_crawl  = max_p
        self._set_scanning(True)
        self._log_msg(f"Starte Crawl: {domain}  (max. {max_p} Seiten)")
        self.scan_thread = threading.Thread(target=self._run_crawl, args=(domain, max_p), daemon=True)
        self.scan_thread.start()

    def _run_crawl(self, domain: str, max_p: int):
        def _cb(i, total, url):
            self._set_progress(i / total * 100)
            self._set_status(f"Crawle {i}/{total}: {url[:90]}")
            self._log_msg(f"→ {url}")
        new = self.scanner.crawl_domain(domain, max_p, progress_cb=_cb)
        self._finish_scan(new)

    def _finish_scan(self, new_results: List[Dict]):
        self.results.extend(new_results)
        found = sum(1 for r in new_results if r.get("found"))
        total = len(new_results)
        self._log_msg(f"✔  Fertig – {total} URLs geprüft, {found} mit Silverlight erkannt.")
        self._set_status(f"Abgeschlossen: {found}/{total} Silverlight-Seiten gefunden.")
        self._set_progress(100)
        self._set_scanning(False)
        self.after(0, self._refresh)
        if found:
            self.after(0, lambda: self.nb.select(1))

    def _stop_scan(self):
        self.scanner.stop()
        self._log_msg("⏹  Stopp angefordert …")

    # ═════════════════════════════════════════════════════════════════════════
    # Ergebnisse-Logik
    # ═════════════════════════════════════════════════════════════════════════

    def _refresh(self):
        for item in self._tree.get_children():
            self._tree.delete(item)

        show_all = self._show_all.get()
        display  = self.results if show_all else [r for r in self.results if r.get("found")]

        for r in display:
            conf   = r.get("confidence", "none")
            inds   = r.get("indicators", [])
            ind_str = ", ".join(
                (i[0] if isinstance(i, tuple) else str(i)) for i in inds[:3]
            )
            if len(inds) > 3:
                ind_str += f"  (+{len(inds)-3} weitere)"
            self._tree.insert("", tk.END, tags=(conf,), values=(
                CONF_LABELS.get(conf, "—"),
                r.get("url", ""),
                r.get("title", "")[:65],
                r.get("status_code", ""),
                ind_str,
            ))

        found = sum(1 for r in display if r.get("found"))
        self._count_var.set(f"{found} Silverlight-Seiten  |  {len(display)} gesamt")

    def _selected(self) -> Optional[Dict]:
        sel = self._tree.selection()
        if not sel:
            return None
        url = self._tree.item(sel[0])["values"][1]
        for r in self.results:
            if r.get("url") == url or r.get("final_url") == url:
                return r
        return None

    def _open_in_edge(self):
        r = self._selected()
        if r:
            open_in_edge(r.get("final_url") or r.get("url", ""))
        else:
            messagebox.showinfo("Hinweis", "Bitte eine URL in der Liste auswählen.")

    def _copy_url(self):
        r = self._selected()
        if r:
            url = r.get("final_url") or r.get("url", "")
            self.clipboard_clear()
            self.clipboard_append(url)

    def _show_details(self):
        r = self._selected()
        if not r:
            messagebox.showinfo("Hinweis", "Bitte eine URL auswählen.")
            return

        win = tk.Toplevel(self)
        win.title(f"Details: {r.get('url','')[:70]}")
        win.geometry("720x520")
        win.configure(bg=C["base"])

        txt = scrolledtext.ScrolledText(
            win, bg=C["mantle"], fg=C["text"], font=("Consolas", 10),
            relief=tk.FLAT, borderwidth=8,
        )
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        lines = [
            f"URL            {r.get('url','')}",
            f"Final URL      {r.get('final_url','')}",
            f"HTTP-Status    {r.get('status_code','')}",
            f"Silverlight    {'✔  JA' if r.get('found') else '✘  NEIN'}",
            f"Konfidenz      {r.get('confidence','none').upper()}",
            f"Seitentitel    {r.get('title','')}",
            f"Gescannt am    {r.get('scanned_at','')}",
            "",
            "─── Erkannte Indikatoren " + "─" * 44,
        ]
        for ind in r.get("indicators", []):
            label, conf = ind if isinstance(ind, tuple) else (str(ind), "?")
            lines.append(f"  [{conf.upper():6}]  {label}")

        if r.get("xap_files"):
            lines += ["", "─── .xap-Dateien " + "─" * 52]
            lines += [f"  {x}" for x in r["xap_files"]]

        if r.get("error"):
            lines += ["", "─── Fehler " + "─" * 58, f"  {r['error']}"]

        txt.insert(tk.END, "\n".join(lines))
        txt.config(state=tk.DISABLED)

    def _mark_ie(self):
        r = self._selected()
        if not r:
            messagebox.showinfo("Hinweis", "Bitte eine URL auswählen.")
            return
        url = r.get("final_url") or r.get("url", "")
        if url and url not in self._ie_urls.get("1.0", tk.END):
            self._ie_urls.insert(tk.END, url + "\n")
        self.nb.select(3)

    def _clear_results(self):
        if messagebox.askyesno("Bestätigen", "Alle Scanergebnisse löschen?"):
            self.results.clear()
            self._refresh()

    def _export_json(self):
        if not self.results:
            messagebox.showinfo("Hinweis", "Keine Ergebnisse vorhanden.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile=f"silverlight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        if not path:
            return
        data = [{k: v for k, v in r.items() if k != "indicators"}
                for r in self.results]
        # Indicators als Strings
        for orig, d in zip(self.results, data):
            d["indicators"] = [
                f"[{c.upper()}] {l}" if isinstance(i, tuple) else str(i)
                for i in orig.get("indicators", [])
                for (l, c) in [i if isinstance(i, tuple) else (i, "?")]
            ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("Gespeichert", f"JSON gespeichert:\n{path}")

    def _export_csv(self):
        if not self.results:
            messagebox.showinfo("Hinweis", "Keine Ergebnisse vorhanden.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"silverlight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not path:
            return
        fields = ["url", "final_url", "status_code", "found", "confidence", "title", "scanned_at"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.results)
        messagebox.showinfo("Gespeichert", f"CSV gespeichert:\n{path}")

    # ═════════════════════════════════════════════════════════════════════════
    # IE-Modus-Logik
    # ═════════════════════════════════════════════════════════════════════════

    def _gen_xml(self):
        raw  = self._ie_urls.get("1.0", tk.END).strip()
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning("Hinweis", "Keine URLs in der IE-Modus-Liste vorhanden.")
            return
        xml = generate_ie_site_list(urls)
        self._xml_out.config(state=tk.NORMAL)
        self._xml_out.delete("1.0", tk.END)
        self._xml_out.insert(tk.END, xml)
        self._xml_out.config(state=tk.DISABLED)

    def _save_xml(self):
        xml = self._xml_out.get("1.0", tk.END).strip()
        if not xml:
            messagebox.showwarning("Hinweis", "Bitte erst eine Site List generieren.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xml", filetypes=[("XML", "*.xml")],
            initialfile="SilverlightSiteList.xml",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml)
            messagebox.showinfo("Gespeichert", f"XML gespeichert:\n{path}")

    def _copy_xml(self):
        xml = self._xml_out.get("1.0", tk.END).strip()
        if xml:
            self.clipboard_clear()
            self.clipboard_append(xml)

    # ─── Such-Logik ──────────────────────────────────────────────────────────

    def _open_dork(self, tree: ttk.Treeview):
        sel = tree.selection()
        if not sel:
            return
        url = self._dork_map.get(sel[0])
        if url:
            webbrowser.open(url)


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
