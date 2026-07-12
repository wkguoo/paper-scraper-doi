#!/usr/bin/env python
"""
ScienceDirect 论文抓取工具 v2.0
================================
使用 curl_cffi 与用户已授权的浏览器会话访问 ScienceDirect。
支持多种搜索方式，结果保存为 CSV / JSON，无翻译步骤。

支持的搜索模式
--------------
  keyword        — 按关键词搜索
  journal        — 按期刊名浏览
  journal_keyword— 在指定期刊内按关键词搜索
  author         — 按作者搜索
  issn           — 按期刊 ISSN 搜索
  advanced       — 高级搜索（组合多个条件）

快速上手（命令行）
------------------
  python sd_scraper.py -m keyword -q "machine learning" -n 100 --browser-cookies
  python sd_scraper.py -m journal  -j "Energy" -n 50 --browser-cookies
  python sd_scraper.py -m journal_keyword -j "Renewable Energy" -q "solar cell" -n 50 --browser-cookies

交互式向导
----------
  python sd_scraper.py

依赖安装
--------
  pip install curl_cffi browser-cookie3
"""

import json
import csv
import html
import os
import sys
import re
import time
import random
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, unquote, urlparse

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError as exc:
    HAS_CURL_CFFI = False
    CURL_CFFI_IMPORT_ERROR = exc

    class _MissingCurlRequests:
        @staticmethod
        def Session(*_args, **_kwargs):
            raise RuntimeError(_curl_cffi_missing_message())

    curl_requests = _MissingCurlRequests()
from doi_batch_utils import (
    DownloadRunResult,
    PdfDownloadRecord,
    RunEvent,
    RunSummary,
    SupplementDownloadRecord,
    check_cookie_json,
    clean_doi,
    extract_doi_from_text,
    failure_reason_counts,
    filter_records_for_resume,
    load_doi_records,
    load_resume_success_dois,
    safe_write_run_event,
    write_pdf_download_report,
    write_pdf_bytes_atomic,
    write_retry_input_from_reports,
    write_run_summary,
    write_run_summary_json,
    write_supplement_download_report,
)
from sd_supplements import (
    download_supplements_for_article,
    make_article_stem,
    supplement_status_counts,
)
from student_handoff import write_student_handoff
from windows_paths import (
    BROWSER_EXE_ENV,
    browser_bin,
    browser_candidate_paths,
    browser_default_profile,
    browser_display_name,
    chrome_bin,
    chrome_debug_log,
    chrome_debug_profile,
)
from paper_automation.pdf_validation import is_pdf_bytes, is_valid_pdf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

try:
    import browser_cookie3
    HAS_BROWSER_COOKIE3 = True
except ImportError:
    browser_cookie3 = None
    HAS_BROWSER_COOKIE3 = False

try:
    from openpyxl import Workbook, load_workbook
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


# Only cookie files may be copied into the temporary debug profile.
# Never copy Preferences / Secure Preferences / Extensions: Chromium stores
# extension IDs and install paths in Preferences, so cloning them into Edge
# (or vice versa) can load the user's full extension set into the debug browser.
BROWSER_PROFILE_COPY_FILES = (
    "Cookies",
    "Cookies-journal",
)
BROWSER_PROFILE_COPY_DIRS = ()
BROWSER_DEBUG_EXTRA_ARGS = (
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
)


def _curl_cffi_missing_message() -> str:
    return (
        "缺少依赖 curl_cffi，ScienceDirect 网络请求无法执行。"
        "请运行: python -m pip install -r requirements.txt "
        "或 python -m pip install curl_cffi"
    )


class _MissingCurlSession:
    def __getattr__(self, _name: str):
        raise RuntimeError(_curl_cffi_missing_message())

    def get(self, *_args, **_kwargs):
        raise RuntimeError(_curl_cffi_missing_message())

    def post(self, *_args, **_kwargs):
        raise RuntimeError(_curl_cffi_missing_message())


def _new_curl_session(*args, allow_missing: bool = False, **kwargs):
    if HAS_CURL_CFFI:
        return curl_requests.Session(*args, **kwargs)
    if allow_missing:
        return _MissingCurlSession()
    raise RuntimeError(_curl_cffi_missing_message())


# ──────────────────────────────────────────────────────────────────────────────
# DevTools PDF 捕获（纯 websocket-client，无需 Playwright）
# ──────────────────────────────────────────────────────────────────────────────

def _dt_get_header(headers, name: str) -> str:
    target = name.lower()
    if isinstance(headers, dict):
        for k, v in headers.items():
            if str(k).lower() == target:
                return str(v).lower()
    elif isinstance(headers, list):
        for entry in headers:
            if isinstance(entry, dict) and str(entry.get("name", "")).lower() == target:
                return str(entry.get("value", "")).lower()
    return ""


def _dt_is_pdf_url(url: str) -> bool:
    low = (url or "").lower()
    return ".pdf" in low or "pdf.sciencedirectassets.com" in low


def _is_sciencedirect_pdf_asset_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        return False
    return host == "pdf.sciencedirectassets.com"


def _unquote_repeated(value: str, limit: int = 3) -> str:
    for _ in range(limit):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def is_sciencedirect_pdf_access_url(url: str) -> bool:
    """Return True only for real ScienceDirect PDF assets or browser PDF viewers wrapping them."""
    url = (url or "").strip()
    if not url:
        return False
    if _is_sciencedirect_pdf_asset_url(url):
        return True

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if scheme == "chrome-extension":
        if host != "mhjfbmdgcfjbbpaeojofohoefgiehjai" or not path.endswith("/index.html"):
            return False
    elif scheme in {"chrome", "edge"}:
        if host != "pdf-viewer":
            return False
    else:
        return False

    query_values: list[str] = []
    for values in parse_qs(parsed.query, keep_blank_values=True).values():
        query_values.extend(values)
    if parsed.fragment:
        query_values.append(parsed.fragment)

    for value in query_values:
        decoded = _unquote_repeated(value)
        embedded_urls = re.findall(r"https?://[^\s'\"<>)]*", decoded)
        if any(_is_sciencedirect_pdf_asset_url(candidate) for candidate in embedded_urls):
            return True
    return False


def _dt_is_pdf_response(response: dict) -> bool:
    mime = (response.get("mimeType") or "").lower()
    ct = _dt_get_header(response.get("headers") or {}, "content-type")
    return "pdf" in mime or "pdf" in ct or _dt_is_pdf_url(response.get("url", ""))


def _dt_is_pdf_fetch_response(url: str, status, headers) -> bool:
    if status is None or status < 200 or status >= 400:
        return False
    ct = _dt_get_header(headers, "content-type")
    return "pdf" in ct or _dt_is_pdf_url(url)


BLOCK_PAGE_SIGNALS = (
    "there was a problem providing",
    "verify you are human",
    "captcha",
    "are you a robot",
    "robot or human",
    "challenge-platform",
    "cf-browser-verification",
    "access denied",
)

# 需要人工点击验证的 CAPTCHA 类封锁（等待无效，必须人工解决）
CAPTCHA_SIGNALS = (
    "are you a robot",
    "verify you are human",
    "captcha",
    "robot or human",
    "challenge-platform",
    "cf-browser-verification",
)

# 每次页面加载前注入：保持调试浏览器会话与普通浏览器环境兼容
_BROWSER_COMPAT_JS = """
(function() {
    // 1. 隐藏 webdriver 标志（最常见的检测点）
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. 补全 navigator.plugins（受控 Chrome 默认为空数组）
    if (navigator.plugins.length === 0) {
        Object.defineProperty(navigator, 'plugins', {
            get: () => {
                const arr = [
                    { name: 'Chrome PDF Plugin',     filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer',     filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client',         filename: 'internal-nacl-plugin' },
                ];
                arr.item = (i) => arr[i];
                arr.namedItem = (n) => arr.find(p => p.name === n) || null;
                arr.refresh = () => {};
                Object.setPrototypeOf(arr, PluginArray.prototype);
                return arr;
            }
        });
    }

    // 3. 补全 navigator.languages
    if (!navigator.languages || navigator.languages.length === 0) {
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
    }

    // 4. 补全 window.chrome（受控 Chrome 有时缺失）
    if (!window.chrome) {
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {},
        };
    }

    // 5. Notification.permission 不暴露"default"以外的值
    const _origQuery = window.Notification
        ? window.Notification.requestPermission
        : null;
    if (window.Notification) {
        try {
            Object.defineProperty(Notification, 'permission', { get: () => 'default' });
        } catch (_) {}
    }

    // 6. 去掉 CDP 注入的全局变量痕迹
    try { delete window.__nightmare; } catch (_) {}
    try { delete window._phantom;    } catch (_) {}
    try { delete window.callPhantom;  } catch (_) {}
    try { delete document.__defineGetter__; } catch (_) {}
})();
"""


def _dt_capture_pdf(ws_url: str, url: str, timeout: int = 35, fetch_patterns=None):
    """
    在已有 DevTools 标签页中导航到 url，通过 Network/Fetch 拦截捕获 PDF 字节。
    返回 (bytes | None, note_str)。
    note_str 以 "blocked:" 开头表示遇到访问限制页面。
    """
    try:
        import websocket as _ws
    except ImportError:
        return None, "websocket-client 未安装"

    import base64 as _b64

    ws = _ws.create_connection(ws_url, timeout=180, suppress_origin=True)
    ws.settimeout(1)
    msg_id = 200

    def send(method, params=None):
        nonlocal msg_id
        msg_id += 1
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        return msg_id

    pdf_req_ids: set = set()
    body_reqs: dict = {}        # {rpc_id: network_request_id}
    fetch_body_reqs: dict = {}  # {rpc_id: fetch_request_id}
    fetch_meta: dict = {}       # {fetch_request_id: {url}}
    evaluate_reqs: dict = {}    # {rpc_id: "block_check"}
    last_pdf_url = ""
    last_error = ""

    try:
        send("Page.enable")
        # 每次新页面加载前注入浏览器兼容脚本
        send("Page.addScriptToEvaluateOnNewDocument", {"source": _BROWSER_COMPAT_JS})
        send("Fetch.enable", {"patterns": fetch_patterns or [
            {"urlPattern": "*pdf.sciencedirectassets.com/*", "requestStage": "Response"},
            {"urlPattern": "*pdfft*", "requestStage": "Response"},
        ]})
        send("Network.enable", {
            "maxTotalBufferSize": 120 * 1024 * 1024,
            "maxResourceBufferSize": 100 * 1024 * 1024,
        })
        send("Network.setCacheDisabled", {"cacheDisabled": True})
        send("Page.navigate", {"url": url})

        deadline = time.time() + max(5, timeout)
        while time.time() < deadline:
            ws.settimeout(max(0.5, min(2.0, deadline - time.time())))
            try:
                raw = ws.recv()
            except Exception:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            method = msg.get("method")
            if method == "Fetch.requestPaused":
                p = msg.get("params", {})
                req_id = p.get("requestId")
                req_url = (p.get("request") or {}).get("url", "")
                status = p.get("responseStatusCode")
                hdrs = p.get("responseHeaders") or []
                if req_id and _dt_is_pdf_fetch_response(req_url, status, hdrs):
                    fetch_meta[req_id] = {"url": req_url}
                    bid = send("Fetch.getResponseBody", {"requestId": req_id})
                    fetch_body_reqs[bid] = req_id
                elif req_id:
                    send("Fetch.continueRequest", {"requestId": req_id})
            elif method == "Network.responseReceived":
                p = msg.get("params", {})
                resp = p.get("response", {})
                if _dt_is_pdf_response(resp):
                    rid = p.get("requestId")
                    if rid:
                        pdf_req_ids.add(rid)
                        last_pdf_url = resp.get("url", "") or last_pdf_url
            elif method == "Network.loadingFinished":
                rid = msg.get("params", {}).get("requestId")
                if rid in pdf_req_ids and rid not in body_reqs.values():
                    bid = send("Network.getResponseBody", {"requestId": rid})
                    body_reqs[bid] = rid
            elif method == "Network.loadingFailed":
                p = msg.get("params", {})
                rid = p.get("requestId")
                if rid in pdf_req_ids:
                    last_error = p.get("errorText") or "pdf_loading_failed"
                    pdf_req_ids.discard(rid)
            elif method == "Page.loadEventFired":
                bid = send("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.slice(0,2000).toLowerCase() : ''",
                    "returnByValue": True,
                })
                evaluate_reqs[bid] = "block_check"
            elif msg.get("id") in evaluate_reqs:
                evaluate_reqs.pop(msg["id"])
                if "error" not in msg:
                    text = msg.get("result", {}).get("result", {}).get("value", "") or ""
                    if any(sig in text for sig in BLOCK_PAGE_SIGNALS):
                        return None, f"blocked:{text[:120]}"
            elif msg.get("id") in fetch_body_reqs:
                req_id = fetch_body_reqs.pop(msg["id"])
                result = msg.get("result", {})
                if "error" not in msg:
                    body = result.get("body")
                    if body:
                        data = _b64.b64decode(body) if result.get("base64Encoded") else body.encode("latin-1", errors="ignore")
                        if is_pdf_bytes(data):
                            return data, fetch_meta.get(req_id, {}).get("url") or last_pdf_url or url
                try:
                    send("Fetch.continueRequest", {"requestId": req_id})
                except Exception:
                    pass
            elif msg.get("id") in body_reqs:
                body_reqs.pop(msg["id"])
                result = msg.get("result", {})
                if "error" not in msg:
                    body = result.get("body")
                    if body:
                        data = _b64.b64decode(body) if result.get("base64Encoded") else body.encode("latin-1", errors="ignore")
                        if is_pdf_bytes(data):
                            return data, last_pdf_url or url
    finally:
        try:
            ws.close()
        except Exception:
            pass

    return None, last_error or "network_pdf_not_captured"


# ──────────────────────────────────────────────────────────────────────────────
# 核心爬虫类
# ──────────────────────────────────────────────────────────────────────────────

class ScienceDirectScraper:
    BASE_URL = "https://www.sciencedirect.com"
    SEARCH_API = "https://www.sciencedirect.com/search/api"

    def __init__(self, cookies_file=None, use_browser_cookies=False, delay_range=(2, 5), browser_exe=None):
        self.session = _new_curl_session(impersonate="chrome124", allow_missing=True)
        self.delay_range = delay_range
        self._search_token = None
        self._cookie_dict = {}     # 机构 cookie（来自 Chrome/文件，用于 PDF 下载）
        self._session_cookies = {} # 搜索 session cookie（来自服务器，用于搜索 API）

        self.browser_exe = browser_exe
        self.CHROME_BIN = browser_bin(browser_exe)
        self.browser_name = browser_display_name(browser_exe)
        self.last_browser_message = self.browser_status_message()
        self.last_download_next_steps = ""

        if use_browser_cookies:
            self._load_browser_cookies()
        elif cookies_file:
            self._load_cookies(cookies_file)

    def browser_status_message(self) -> str:
        return (
            f"{self.browser_name}: {self.CHROME_BIN}; "
            f"profile: {browser_default_profile(self.CHROME_BIN)}; "
            f"debug_port: {self.CHROME_DBG_PORT}"
        )

    @staticmethod
    def default_download_next_steps() -> str:
        return (
            "Open pdf_download_report.csv and run_summary.json to inspect exact failures.\n"
        "If institutional access failed, sign in through the selected external browser debug window and retry the DOI batch.\n"
            "If ScienceDirect remains inaccessible, try publisher OA pages, author/lab pages, or Unpaywall."
        )

    # ── Cookie 支持 ──────────────────────────────────────────────────────────

    def _apply_cookie_header(self):
        """把 _cookie_dict 拼成 Cookie 请求头发送（比 session.cookies 更可靠）。"""
        if self._cookie_dict:
            self.session.headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in self._cookie_dict.items()
            )

    def _load_browser_cookies(self):
        """直接从本机 Chrome 读取 sciencedirect.com 的 cookie。"""
        if not HAS_BROWSER_COOKIE3:
            print("[错误] 未安装 browser-cookie3，请运行：pip install browser-cookie3")
            return
        loaders = [("Chrome", browser_cookie3.chrome)]

        errors: list[str] = []
        for label, loader in loaders:
            before = len(self._cookie_dict)
            try:
                jar = loader(domain_name='.sciencedirect.com')
                for c in jar:
                    self._cookie_dict[c.name] = c.value
                added = len(self._cookie_dict) - before
                if added:
                    self._apply_cookie_header()
                    print(f"[信息] 已从 {label} 自动读取 {added} 个 cookie（机构账号模式）")
                    return
            except Exception as e:
                errors.append(f"{label}: {e}")

        print("[警告] Chrome 中未找到 sciencedirect.com 的 cookie；下载时可能需要在调试浏览器中登录")
        if errors:
            print(f"[警告] 本机浏览器 cookie 读取失败: {'; '.join(errors[:2])}")
        if sys.platform.startswith("win"):
            print("       提示：Windows 上可通过弹出的调试浏览器完成机构登录并刷新 Cookie")
        elif sys.platform == "darwin":
            print("       提示：macOS 可能弹出钥匙串权限请求，请点允许")

    def _load_cookies(self, cookies_file):
        """从 JSON 文件加载 cookies。"""
        if not os.path.exists(cookies_file):
            print(f"[警告] 找不到 cookies 文件: {cookies_file}，将以游客模式运行")
            return
        data = None
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
            try:
                with open(cookies_file, "r", encoding=encoding) as f:
                    data = json.load(f)
                print(f"[信息] Cookie JSON 编码识别为 {encoding}")
                break
            except UnicodeDecodeError as e:
                last_error = e
        if data is None:
            print(f"[警告] 无法读取 cookies 文件编码: {last_error}，将以游客模式运行")
            return

        cookie_items = data
        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            cookie_items = data["cookies"]

        if isinstance(cookie_items, list):
            for c in cookie_items:
                if not isinstance(c, dict):
                    continue
                name = c.get("name") or c.get("Name", "")
                value = c.get("value") or c.get("Value", "")
                if name and value:
                    self._cookie_dict[name] = value
        elif isinstance(cookie_items, dict):
            self._cookie_dict.update({k: str(v) for k, v in cookie_items.items()})
        self._apply_cookie_header()
        print(f"[信息] 已加载 {len(self._cookie_dict)} 个 cookie（机构账号模式）")

    # ── 内部工具 ─────────────────────────────────────────────────────────────

    def _delay(self):
        time.sleep(random.uniform(*self.delay_range))

    def _fetch_search_token(self, params: dict):
        """
        用干净 session 访问搜索页面，获取：
        1. 服务器下发的 session cookie（EUID、csrf_token 等）
        2. searchToken（嵌入在页面 INITIAL_STATE 中）

        注意：不带浏览器 cookie，避免旧 MIAMISESSION 与新 session 冲突。
        服务器 cookie 单独存入 _session_cookies，搜索时只用这些。
        机构 cookie（_cookie_dict）仅在 PDF 下载时附加。
        """
        url = self.BASE_URL + "/search?" + urlencode(params)
        try:
            # 不带任何 Cookie 头，让服务器建立干净 session
            resp = self.session.get(url, timeout=25,
                                    headers={"Cookie": ""})
            if resp.status_code != 200:
                print(f"  [警告] 获取搜索页面失败 HTTP {resp.status_code}")
                return None

            # 收集服务器下发的 cookie
            self._session_cookies = {}
            for k, v in resp.headers.items():
                if k.lower() == "set-cookie":
                    part = v.split(";")[0]
                    if "=" in part:
                        name, val = part.split("=", 1)
                        self._session_cookies[name.strip()] = val.strip()
            # 更新请求头：只用 session cookie（干净）
            self.session.headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in self._session_cookies.items()
            )

            m = re.search(r'"searchToken":"([^"]+)"', resp.text)
            if m:
                self._search_token = m.group(1)
                return self._search_token
            else:
                print("  [警告] 页面中未找到 searchToken")
                return None
        except Exception as e:
            print(f"  [网络错误] {e}")
            return None

    def _search(self, params: dict, max_count: int = 100):
        """
        两步搜索流程：
        Step 1: 访问搜索页 HTML → 获取 csrf_token cookie + searchToken
        Step 2: 用 token 调 /search/api 获取 JSON 数据，支持分页
        """
        results = []
        offset = 0
        per_page = 25
        total_known = None

        # Step 1: 获取 token（只需首次）
        token_params = {k: v for k, v in params.items()}
        token_params["offset"] = 0
        token_params["show"] = per_page
        token = self._fetch_search_token(token_params)
        if not token:
            print("  [错误] 无法获取搜索凭证，请检查网络或 cookie")
            return results

        self._delay()

        # Step 2: 分页调用 API
        _token_retries = 0
        while len(results) < max_count:
            api_params = {k: v for k, v in params.items()}
            api_params["offset"] = offset
            api_params["show"] = per_page
            api_params["t"] = token
            api_params["hostname"] = "www.sciencedirect.com"

            api_url = self.SEARCH_API + "?" + urlencode(api_params)

            try:
                resp = self.session.get(
                    api_url,
                    timeout=20,
                    headers={
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Referer": self.BASE_URL + "/search?" + urlencode(params),
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                if resp.status_code == 401:
                    if _token_retries >= 2:
                        print("  [错误] Token 多次刷新后仍无效，停止")
                        break
                    _token_retries += 1
                    wait = 5 * _token_retries
                    print(f"  [信息] Token 失效，等待 {wait}s 后重新获取...")
                    time.sleep(wait)
                    token_params["offset"] = offset
                    token = self._fetch_search_token(token_params)
                    if not token:
                        print("  [错误] 无法刷新 Token")
                        break
                    continue
                if resp.status_code == 429:
                    print("  [限速] 请求过于频繁，等待 30s...")
                    time.sleep(30)
                    continue
                if resp.status_code != 200:
                    print(f"  [HTTP {resp.status_code}] API 请求失败")
                    break
                _token_retries = 0  # 成功后重置
                data = resp.json()
            except json.JSONDecodeError:
                print("  [错误] 返回内容不是 JSON，可能遇到访问限制")
                break
            except Exception as e:
                print(f"  [网络错误] {e}")
                break

            items = data.get("searchResults", [])
            if total_known is None:
                total_known = int(data.get("resultsFound", data.get("totalResults", 0)))
                actual_max = min(max_count, total_known) if total_known else max_count
                if total_known:
                    print(f"  共找到 {total_known} 篇，计划抓取 {actual_max} 篇")
                else:
                    print(f"  本页返回 {len(items)} 篇")

            if not items:
                if total_known == 0:
                    print("  没有匹配的结果")
                else:
                    print("  没有更多结果了")
                break

            for item in items:
                if len(results) >= max_count:
                    break
                article = self._parse_article(item)
                results.append(article)
                idx = len(results)
                actual_max = min(max_count, total_known or max_count)
                title_preview = (article["title"] or "（无标题）")[:60]
                print(f"  [{idx}/{actual_max}] {title_preview}")

            offset += per_page
            if total_known and offset >= total_known:
                break
            if len(results) >= max_count:
                break

            self._delay()

        return results

    def _parse_article(self, item: dict) -> dict:
        """解析单条搜索结果。"""
        authors_raw = item.get("authors", [])
        if isinstance(authors_raw, list):
            names = []
            for a in authors_raw:
                if isinstance(a, dict):
                    name = a.get("name", "")
                    if not name:
                        name = f"{a.get('givenName', '')} {a.get('surname', '')}".strip()
                    if name:
                        names.append(name)
                elif isinstance(a, str):
                    names.append(a)
            authors_str = "; ".join(names)
        elif isinstance(authors_raw, dict):
            author_list = authors_raw.get("authorList", [])
            authors_str = "; ".join(
                f"{a.get('givenName', '')} {a.get('surname', '')}".strip()
                for a in author_list
            )
        else:
            authors_str = ""

        doi = item.get("doi") or item.get("prism:doi", "")
        link = item.get("link", "")
        if not link:
            link = f"https://doi.org/{doi}" if doi else ""
        elif not link.startswith("http"):
            link = self.BASE_URL + link

        # 日期：API 返回 sortDate（ISO 格式）或 publicationDateDisplay
        sort_date = item.get("sortDate", "")
        date_str = sort_date[:10] if sort_date else ""   # 取 YYYY-MM-DD
        year = date_str[:4] if date_str else ""

        # 卷号：volumeIssue 如 "Volume 414"
        volume_issue = item.get("volumeIssue", "")
        volume = volume_issue.replace("Volume ", "").strip() if volume_issue else ""

        # PDF 下载链接（需机构权限）
        pdf_info = item.get("pdf", {}) or {}
        pdf_link = pdf_info.get("downloadLink", "")
        if pdf_link and not pdf_link.startswith("http"):
            pdf_link = self.BASE_URL + pdf_link
        pii = item.get("pii", "")

        # 期刊名去掉 HTML 标签
        journal_raw = item.get("sourceTitle", "") or item.get("publicationName", "")
        journal_name = re.sub(r"<[^>]+>", "", journal_raw)

        return {
            "title":        item.get("title", ""),
            "authors":      authors_str,
            "journal":      journal_name,
            "volume":       volume,
            "issue":        item.get("issue", ""),
            "year":         year,
            "date":         date_str,
            "doi":          doi,
            "abstract":     item.get("abstract", ""),
            "article_type": item.get("articleType", ""),
            "open_access":  bool(item.get("openAccess") or item.get("openArchive")),
            "url":          link,
            "pdf_url":      pdf_link,
            "pii":          pii,
        }

    # ── 搜索模式 ─────────────────────────────────────────────────────────────

    def search_by_keyword(self, query, count=100, sort_by="relevance",
                          date_range=None, article_type=None):
        """按关键词搜索（支持布尔运算符 AND / OR / NOT）。"""
        print(f"\n[关键词搜索]  关键词: {query}")
        params = {"qs": query, "sortBy": sort_by}
        if date_range:
            params["date"] = date_range
        if article_type:
            params["articleTypes"] = article_type
        return self._search(params, max_count=count)

    def search_by_journal(self, journal_name, count=100, sort_by="date",
                          date_range=None):
        """按期刊名称浏览。"""
        print(f"\n[期刊浏览]  期刊: {journal_name}")
        params = {"pub": journal_name, "sortBy": sort_by}
        if date_range:
            params["date"] = date_range
        return self._search(params, max_count=count)

    def search_by_journal_keyword(self, journal_name, query, count=100,
                                  sort_by="relevance", date_range=None):
        """在指定期刊内按关键词搜索。"""
        print(f"\n[期刊+关键词]  期刊: {journal_name}  关键词: {query}")
        params = {"pub": journal_name, "qs": query, "sortBy": sort_by}
        if date_range:
            params["date"] = date_range
        return self._search(params, max_count=count)

    def search_by_author(self, author_name, count=100, sort_by="date"):
        """按作者姓名搜索。"""
        print(f"\n[作者搜索]  作者: {author_name}")
        params = {"au": author_name, "sortBy": sort_by}
        return self._search(params, max_count=count)

    def search_by_issn(self, issn, count=100, sort_by="date", date_range=None):
        """按期刊 ISSN 搜索。"""
        print(f"\n[ISSN 搜索]  ISSN: {issn}")
        params = {"issn": issn, "sortBy": sort_by}
        if date_range:
            params["date"] = date_range
        return self._search(params, max_count=count)

    def search_advanced(self, query=None, journal=None, author=None,
                        issn=None, date_range=None, article_type=None,
                        open_access_only=False, count=100, sort_by="relevance"):
        """高级搜索：组合多个条件。"""
        print("\n[高级搜索]")
        params = {"sortBy": sort_by}
        if query:
            params["qs"] = query;       print(f"  关键词:   {query}")
        if journal:
            params["pub"] = journal;    print(f"  期刊:     {journal}")
        if author:
            params["au"] = author;      print(f"  作者:     {author}")
        if issn:
            params["issn"] = issn;      print(f"  ISSN:     {issn}")
        if date_range:
            params["date"] = date_range; print(f"  时间范围: {date_range}")
        if article_type:
            params["articleTypes"] = article_type; print(f"  文章类型: {article_type}")
        if open_access_only:
            params["openAccess"] = "true"; print("  仅开放获取: 是")
        return self._search(params, max_count=count)

    # ── 保存结果 ─────────────────────────────────────────────────────────────

    # DOI batch mode.

    DOI_COLUMN_CANDIDATES = ("doi", "DOI", "Doi", "DOI号", "doi号")
    COLUMN_ALIASES = {
        "title": ("title", "article title", "paper title", "标题", "题名", "文献标题"),
        "authors": ("authors", "author", "作者", "作者列表"),
        "journal": ("journal", "source", "publication", "期刊", "期刊名称"),
        "year": ("year", "publication year", "年份", "发表年份"),
        "date": ("date", "publication date", "日期", "发表日期"),
        "doi": DOI_COLUMN_CANDIDATES,
    }

    @staticmethod
    def _normalize_column_name(name):
        return re.sub(r"[\s_\-]+", "", str(name or "")).lower()

    @classmethod
    def _find_column(cls, headers, candidates):
        normalized = {cls._normalize_column_name(h): h for h in headers}
        for candidate in candidates:
            key = cls._normalize_column_name(candidate)
            if key in normalized:
                return normalized[key]
        return None

    @classmethod
    def _row_value(cls, row, field):
        col = cls._find_column(row.keys(), cls.COLUMN_ALIASES[field])
        if not col:
            return ""
        value = row.get(col, "")
        return "" if value is None else str(value).strip()

    @staticmethod
    def _clean_doi(doi):
        return clean_doi(doi)

    @classmethod
    def _extract_doi_from_text(cls, text):
        return extract_doi_from_text(text)

    @staticmethod
    def _extract_pii_from_text(text):
        if not text:
            return ""
        patterns = (
            r"/science/article/pii/([A-Z0-9]+)",
            r"/retrieve/pii/([A-Z0-9]+)",
            r'"pii"\s*:\s*"([^"]+)"',
            r"'pii'\s*:\s*'([^']+)'",
            r"PII:\s*([A-Z0-9]+)",
        )
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.I)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_citation_metadata(html_text):
        if not html_text:
            return {}
        meta: dict[str, list[str]] = {}
        attr_re = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*(".*?"|\'.*?\'|[^\s>]+)', flags=re.S)
        for tag_match in re.finditer(r"<meta\b[^>]*>", html_text, flags=re.I | re.S):
            attrs = {}
            for key, raw_value in attr_re.findall(tag_match.group(0)):
                value = raw_value.strip().strip('"\'')
                attrs[key.lower()] = html.unescape(value).strip()
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            content = attrs.get("content") or ""
            if name.startswith("citation_") and content:
                meta.setdefault(name, []).append(content)

        title = (meta.get("citation_title") or [""])[0]
        authors = "; ".join(meta.get("citation_author") or [])
        journal = (meta.get("citation_journal_title") or meta.get("citation_publication") or [""])[0]
        date = (
            meta.get("citation_publication_date")
            or meta.get("citation_online_date")
            or meta.get("citation_date")
            or [""]
        )[0]
        year_match = re.search(r"\b(19|20)\d{2}\b", date)
        return {
            "title": title,
            "authors": authors,
            "journal": journal,
            "date": date,
            "year": year_match.group(0) if year_match else "",
        }

    def _read_doi_rows_from_csv(self, input_path):
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
            rows = []
            try:
                with open(input_path, "r", newline="", encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader, start=2):
                        rows.append((idx, row))
                print(f"[信息] CSV 编码识别为 {encoding}")
                return rows
            except UnicodeDecodeError as e:
                last_error = e
        raise UnicodeDecodeError(
            "csv", b"", 0, 1,
            f"无法识别 CSV 编码，请另存为 UTF-8 CSV；最后一次错误: {last_error}"
        )

    def _read_doi_rows_from_text(self, input_path):
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
            rows = []
            try:
                with open(input_path, "r", encoding=encoding) as f:
                    for idx, line in enumerate(f, start=1):
                        doi = self._extract_doi_from_text(line)
                        if doi:
                            rows.append((idx, {"doi": doi, "title": ""}))
                print(f"[信息] 文本编码识别为 {encoding}")
                return rows
            except UnicodeDecodeError as e:
                last_error = e
        raise UnicodeDecodeError(
            "text", b"", 0, 1,
            f"无法识别文本编码，请另存为 UTF-8；最后一次错误: {last_error}"
        )

    def _read_doi_rows_from_xlsx(self, input_path, sheet_name=None):
        if not HAS_OPENPYXL:
            raise RuntimeError("读取 xlsx 需要安装 openpyxl")
        wb = load_workbook(input_path, read_only=True, data_only=True)
        if sheet_name and sheet_name not in wb.sheetnames:
            raise ValueError(f"找不到工作表：{sheet_name}。可用工作表：{', '.join(wb.sheetnames)}")
        ws = wb[sheet_name] if sheet_name else wb[wb.sheetnames[0]]
        rows_iter = ws.iter_rows(values_only=True)
        headers = next(rows_iter, None)
        if not headers:
            return []
        headers = [str(h).strip() if h is not None else "" for h in headers]
        rows = []
        for idx, values in enumerate(rows_iter, start=2):
            row = {headers[i]: values[i] if i < len(values) else "" for i in range(len(headers))}
            rows.append((idx, row))
        return rows

    def _read_doi_rows(self, input_path, doi_column=None, sheet_name=None):
        records = load_doi_records(input_path, doi_column=doi_column, sheet_name=sheet_name)
        if not records:
            return [], "输入文件没有可读取的数据行"

        rows = []
        for record in records:
            rows.append({
                "row_number": record.row_number,
                "doi": record.doi,
                "title": record.title,
                "authors": record.authors,
                "journal": record.journal,
                "year": record.year,
                "date": record.date,
            })
        return rows, ""

    def _resolve_doi_to_article(self, item):
        doi = item["doi"]
        if not doi:
            return None, "DOI 为空"

        doi_url = f"https://doi.org/{doi}"
        try:
            print(f"    访问 DOI 跳转: {doi_url}", flush=True)
            resp = self.session.get(
                doi_url,
                allow_redirects=True,
                timeout=20,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://doi.org/",
                },
            )
        except Exception as e:
            return None, f"DOI 访问失败: {e}"

        final_url = unquote(str(getattr(resp, "url", "") or ""))
        try:
            body = resp.text or ""
        except Exception:
            body = ""

        target_text = (final_url + "\n" + body).lower()
        if "sciencedirect.com" not in target_text and "linkinghub.elsevier.com" not in target_text:
            return None, f"非 ScienceDirect 链接: {final_url or doi_url}"

        pii = self._extract_pii_from_text(final_url) or self._extract_pii_from_text(body)
        if not pii:
            return None, f"无法从 ScienceDirect 页面提取 PII: {final_url or doi_url}"

        article_url = f"{self.BASE_URL}/science/article/pii/{pii}"
        page_meta = self._extract_citation_metadata(body)
        return {
            "title": item.get("title", "") or page_meta.get("title", ""),
            "authors": item.get("authors", "") or page_meta.get("authors", ""),
            "journal": item.get("journal", "") or page_meta.get("journal", ""),
            "volume": "",
            "issue": "",
            "year": item.get("year", "") or page_meta.get("year", ""),
            "date": item.get("date", "") or page_meta.get("date", ""),
            "doi": doi,
            "abstract": "",
            "article_type": "",
            "open_access": "",
            "url": final_url or article_url,
            "pdf_url": f"{article_url}/pdfft",
            "pii": pii,
        }, ""

    def resolve_doi_batch(
        self,
        input_path,
        doi_column=None,
        sheet_name=None,
        resume_success_dois=None,
        event_path=None,
    ):
        try:
            rows, error = self._read_doi_rows(input_path, doi_column, sheet_name)
        except Exception as e:
            error = f"读取输入文件失败: {e}"
            rows = []
        if error:
            print(f"[错误] {error}")
            safe_write_run_event(event_path, RunEvent(stage="resolve", status="failed", reason=error))
            return [], [{"row_number": "", "doi": "", "reason": error}]

        self.last_doi_batch_total_rows = len(rows)
        self.last_doi_batch_total_doi = sum(1 for item in rows if item.get("doi"))
        resume_skipped = []
        if resume_success_dois:
            rows, resume_skipped = filter_records_for_resume(rows, resume_success_dois)
            self.last_doi_batch_resume_skipped = len(resume_skipped)
        print(f"\n[DOI 批量解析] 从 {input_path} 读取 {len(rows)} 条记录")
        resolved = []
        failed = []
        seen = set()
        safe_write_run_event(
            event_path,
            RunEvent(
                stage="resolve",
                status="start",
                counts={
                    "total_rows": self.last_doi_batch_total_rows,
                    "total_doi": self.last_doi_batch_total_doi,
                    "resume_skipped": len(resume_skipped),
                },
            ),
        )
        for item in resume_skipped:
            print(f"  [断点恢复] 跳过已成功下载: {item.get('doi', '')}", flush=True)
            safe_write_run_event(
                event_path,
                RunEvent(
                    stage="resolve",
                    status="skipped",
                    row_number=item.get("row_number", ""),
                    doi=item.get("doi", ""),
                    title=item.get("title", ""),
                    reason=item.get("reason", ""),
                    counts={
                        "resolved": len(resolved),
                        "failed": len(failed),
                        "resume_skipped": len(resume_skipped),
                    },
                ),
            )
        for idx, item in enumerate(rows, start=1):
            doi = item["doi"]
            print(f"  [{idx}/{len(rows)}] 开始解析: {doi or '(空 DOI)'}", flush=True)
            safe_write_run_event(
                event_path,
                RunEvent(
                    stage="resolve",
                    status="running",
                    row_number=item.get("row_number", ""),
                    doi=doi,
                    title=item.get("title", ""),
                    counts={"current": idx, "total": len(rows), "resolved": len(resolved), "failed": len(failed)},
                ),
            )
            if not doi:
                failed.append({"row_number": item["row_number"], "doi": "", "reason": "DOI 为空"})
                print(f"  [{idx}/{len(rows)}] 跳过：第 {item['row_number']} 行 DOI 为空", flush=True)
                safe_write_run_event(
                    event_path,
                    RunEvent(
                        stage="resolve",
                        status="skipped",
                        row_number=item.get("row_number", ""),
                        doi="",
                        title=item.get("title", ""),
                        reason="DOI 为空",
                        counts={"current": idx, "total": len(rows), "resolved": len(resolved), "failed": len(failed)},
                    ),
                )
                continue
            doi_key = doi.lower()
            if doi_key in seen:
                failed.append({"row_number": item["row_number"], "doi": doi, "reason": "重复 DOI，已跳过"})
                print(f"  [{idx}/{len(rows)}] 跳过重复 DOI: {doi}", flush=True)
                safe_write_run_event(
                    event_path,
                    RunEvent(
                        stage="resolve",
                        status="skipped",
                        row_number=item.get("row_number", ""),
                        doi=doi,
                        title=item.get("title", ""),
                        reason="重复 DOI，已跳过",
                        counts={"current": idx, "total": len(rows), "resolved": len(resolved), "failed": len(failed)},
                    ),
                )
                continue
            seen.add(doi_key)

            article, reason = self._resolve_doi_to_article(item)
            if article:
                resolved.append(article)
                print(f"  [{idx}/{len(rows)}] 已解析: {doi} -> {article['pii']}", flush=True)
                safe_write_run_event(
                    event_path,
                    RunEvent(
                        stage="resolve",
                        status="success",
                        row_number=item.get("row_number", ""),
                        doi=doi,
                        title=article.get("title", ""),
                        pii=article.get("pii", ""),
                        counts={"current": idx, "total": len(rows), "resolved": len(resolved), "failed": len(failed)},
                    ),
                )
            else:
                failed.append({"row_number": item["row_number"], "doi": doi, "reason": reason})
                print(f"  [{idx}/{len(rows)}] 解析失败: {doi} ({reason})", flush=True)
                safe_write_run_event(
                    event_path,
                    RunEvent(
                        stage="resolve",
                        status="failed",
                        row_number=item.get("row_number", ""),
                        doi=doi,
                        title=item.get("title", ""),
                        reason=reason,
                        counts={"current": idx, "total": len(rows), "resolved": len(resolved), "failed": len(failed)},
                    ),
                )
            self._delay()
        safe_write_run_event(
            event_path,
            RunEvent(
                stage="resolve",
                status="complete",
                counts={"resolved": len(resolved), "failed": len(failed), "resume_skipped": len(resume_skipped)},
            ),
        )
        return resolved, failed

    def save_failed_doi_report(self, failures, filename, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["row_number", "doi", "reason"])
            writer.writeheader()
            writer.writerows(failures)
        print(f"[CSV] DOI 失败报告已保存 -> {path}  （共 {len(failures)} 条）")
        return path

    FIELDS = ["title", "authors", "journal", "volume", "issue",
              "year", "date", "doi", "abstract", "article_type",
              "open_access", "url", "pdf_url", "pii"]

    def save_to_csv(self, results, filename, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        print(f"\n[CSV] 已保存 → {path}  （共 {len(results)} 篇）")
        return path

    def save_to_json(self, results, filename, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[JSON] 已保存 → {path}  （共 {len(results)} 篇）")
        return path

    def save_to_xlsx(self, results, filename, output_dir):
        if not HAS_OPENPYXL:
            print("[警告] 未安装 openpyxl，回退保存为 CSV")
            csv_name = os.path.splitext(filename)[0] + ".csv"
            return self.save_to_csv(results, csv_name, output_dir)

        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        wb = Workbook()
        ws = wb.active
        ws.title = "papers"
        ws.append(self.FIELDS)
        for item in results:
            ws.append([item.get(field, "") for field in self.FIELDS])
        wb.save(path)
        print(f"[XLSX] 已保存 → {path}  （共 {len(results)} 篇）")
        return path

    @staticmethod
    def _make_pdf_filename(idx, article):
        """生成 PDF 文件名：年份_第一作者_短题名_doihash.pdf。"""
        return f"{make_article_stem(idx, article)}.pdf"

    # ── PDF 下载（直连，无 CDP）────────────────────────────────────────────────

    def _get_cookies_via_cdp(self, ctx):
        """从 CDP Chrome 上下文提取所有相关 Cookie（含 session cookies）。"""
        try:
            all_c = ctx.cookies([
                "https://www.sciencedirect.com",
                "https://www.sciencedirectassets.com",
                "https://pdf.sciencedirectassets.com",
                "https://www.elsevier.com",
            ])
            d = {c["name"]: c["value"] for c in all_c}
            h = "; ".join(f"{k}={v}" for k, v in d.items())
            return d, h
        except Exception:
            return {}, ""

    def _get_cookies_via_browser_cookie3(self):
        """从磁盘 Chrome Cookies 文件读取持久化 Cookie（备用，缺少 session cookies）。"""
        if not HAS_BROWSER_COOKIE3:
            return {}, ""
        try:
            all_cookies = {}
            for domain in (".sciencedirect.com", ".elsevier.com", ".sciencedirectassets.com"):
                jar = browser_cookie3.chrome(domain_name=domain)
                for c in jar:
                    all_cookies[c.name] = c.value
            h = "; ".join(f"{k}={v}" for k, v in all_cookies.items())
            return all_cookies, h
        except Exception as e:
            print(f"  [警告] 读取 Chrome Cookie 失败：{e}")
            return {}, ""

    def _fetch_pdf_link_from_article(self, pii, cookie_header, session):
        """
        用 curl_cffi 访问文章页 HTML，提取 View PDF 按钮的 href（含 md5/pid）。
        返回完整 URL 或 None。
        """
        url = f"{self.BASE_URL}/science/article/pii/{pii}"
        try:
            resp = session.get(
                url,
                headers={
                    "Cookie": cookie_header,
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/146.0.0.0 Safari/537.36"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/avif,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "none",
                    "sec-fetch-user": "?1",
                    "upgrade-insecure-requests": "1",
                },
                allow_redirects=True,
                timeout=25,
            )
            if resp.status_code != 200 or "pdfft" not in resp.text:
                return None
            m = re.search(
                r'href="(/science/article/pii/[^"]*pdfft[^"]*md5[^"]+)"',
                resp.text
            )
            if m:
                return self.BASE_URL + m.group(1).replace("&amp;", "&")
            return None
        except Exception:
            return None

    def _ensure_cookies_with_cdp(self):
        """
        用 CDP Chrome 访问 ScienceDirect 主页，获取包含 session cookies 的完整 Cookie。
        返回 (cookie_header_str, needs_login)。
        若 CDP 不可用，退回到 browser_cookie3。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            _, h = self._get_cookies_via_browser_cookie3()
            return h, False

        if not self._is_chrome_debug_ready():
            print(f"  调试端口未就绪，尝试启动 {self.browser_name}...")
            self._launch_chrome_with_debug()

        if not self._is_chrome_debug_ready():
            print("  [警告] 无法启动调试浏览器，使用磁盘 Cookie（可能缺少 session 信息）")
            _, h = self._get_cookies_via_browser_cookie3()
            return h, False

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.CHROME_DBG_PORT}"
            )
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()

            # 访问 ScienceDirect 主页，初始化用户已授权的浏览器会话
            setup_page = ctx.new_page()
            setup_page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
            try:
                setup_page.goto(self.BASE_URL, timeout=20000, wait_until="domcontentloaded")
                time.sleep(3)
            except Exception:
                pass

            # 检查是否有机构访问（防止 session 过期）
            needs_login = False
            if self._cookie_dict or HAS_BROWSER_COOKIE3:
                test_pii = None
                if not self._check_sd_access(ctx):
                    needs_login = True
            setup_page.close()

            _, cookie_header = self._get_cookies_via_cdp(ctx)
            return cookie_header, needs_login

    def download_pdfs(self, results, output_dir):
        """
        【主要下载方法】通过用户已授权的浏览器会话下载 PDF。

        工作原理（已验证可行）
        ---------------------
        ScienceDirect PDF 访问通常依赖已登录的真实浏览器会话：

        ① /pdfft 端点：无论 curl_cffi 还是 CDP 直接 GET，均会触发 JS 验证
          → 绕不过去，不能直接用 HTTP 请求这个 URL

        ② pdf.sciencedirectassets.com：真正的 PDF 文件服务器，无 JS 验证
          → curl_cffi 可以直接下载 ✓

        所以正确姿势：
          步骤 1  CDP 控制浏览器加载文章页面
                  使用用户本机登录状态和机构权限
          步骤 2  CDP 模拟点击 "View PDF" 按钮
                  Chrome 内部打开弹窗并导航到 sciencedirectassets.com
                  — 浏览器内部导航会沿用当前授权会话
          步骤 3  捕获弹窗的 sciencedirectassets.com URL，立即关闭弹窗
          步骤 4  curl_cffi 直接 GET 这个 URL → 下载 PDF ✓

        PDF 数据通过用户已授权的会话请求获取，浏览器用于建立访问上下文。

        前提
        ----
        Chrome 已通过机构账号（CARSI/深技大）登录 ScienceDirect。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[错误] 需要 playwright：pip install playwright && playwright install chromium")
            return

        pdf_dir = os.path.join(output_dir, "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)
        total = len(results)
        success = skip = fail = 0

        print(f"\n[PDF 下载]  共 {total} 篇，保存至 {pdf_dir}")

        # ── 启动 / 连接调试 Chrome ────────────────────────────────────────
        if not self._is_chrome_debug_ready():
            print(f"  自动启动调试 {self.browser_name}...")
            self._launch_chrome_with_debug()
            if not self._is_chrome_debug_ready():
                print("[错误] 浏览器调试端口无法启动，查看调试日志")
                return

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.CHROME_DBG_PORT}"
            )
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            print(f"  已连接 {self.browser_name} ✓")

            # 访问主页，初始化真实浏览器上下文
            setup_page = ctx.new_page()
            setup_page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
            try:
                setup_page.goto(self.BASE_URL, timeout=20000, wait_until="domcontentloaded")
                time.sleep(2)
            except Exception:
                pass
            setup_page.close()

            # 检查机构访问权限
            test_pii = next((a["pii"] for a in results if a.get("pii")), None)
            if not self._check_sd_access(ctx, test_pii):
                self._wait_for_login(ctx, test_pii)
                if not self._check_sd_access(ctx, test_pii):
                    print("[警告] 仍未检测到机构权限，将尝试继续（部分可能失败）")
                else:
                    print("  机构访问权限确认 ✓")
            else:
                print("  机构访问权限确认 ✓")

            # 提取 cookies，用于 curl_cffi 最终下载
            _, cookie_header = self._get_cookies_via_cdp(ctx)
            dl_session = curl_requests.Session(impersonate="chrome124")
            _DL_HEADERS = {
                "Cookie": cookie_header,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "cross-site",
            }

            print(f"\n  开始下载 {total} 篇 PDF…\n")

            for idx, article in enumerate(results, 1):
                pii = article.get("pii", "")
                title_short = article.get("title", "")[:55]

                if not pii:
                    print(f"  [{idx}/{total}] 跳过（无 PII）: {title_short}")
                    skip += 1
                    continue

                filename = self._make_pdf_filename(idx, article)
                filepath = os.path.join(pdf_dir, filename)

                if os.path.exists(filepath):
                    if is_valid_pdf(filepath):
                        print(f"  [{idx}/{total}] 已存在，跳过: {filename}")
                        skip += 1
                        continue
                    try:
                        os.remove(filepath)
                    except OSError:
                        print(f"  [{idx}/{total}] 无效已存在文件无法清理: {filename}")
                        fail += 1
                        continue

                article_url = f"{self.BASE_URL}/science/article/pii/{pii}"

                # 步骤 1+2+3：CDP 加载文章页 → 点击 View PDF → 捕获弹窗 URL
                page = ctx.new_page()
                pdf_assets_url = None
                try:
                    page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
                    page.goto(article_url, timeout=30000, wait_until="networkidle")
                    time.sleep(1)

                    # 等待 View PDF 按钮出现
                    try:
                        page.wait_for_selector('a[href*="pdfft"]', timeout=10000)
                    except Exception:
                        body = page.inner_text("body")[:300]
                        if "problem providing" in body:
                            print(
                                f"  [{idx}/{total}] ✗ 文章页当前显示 CAPTCHA 或访问限制"
                            )
                            page.close()
                            fail += 1
                            continue
                        print(f"  [{idx}/{total}] ✗ 无 PDF 按钮（无权限？）: {title_short[:35]}")
                        fail += 1
                        page.close()
                        continue

                    # 点击按钮 → 浏览器内部弹出新窗口
                    try:
                        with page.expect_popup(timeout=15000) as popup_info:
                            page.click('a[href*="pdfft"]')
                        popup = popup_info.value
                        pdf_assets_url = popup.url
                        popup.close()   # 立即关闭，不让 Chrome 打开 PDF 阅读器
                    except Exception:
                        # 没有弹窗：有些浏览器配置直接在当前页跳转
                        try:
                            pdf_assets_url = page.eval_on_selector(
                                'a[href*="pdfft"]', 'el => el.href'
                            )
                        except Exception:
                            pass
                    page.close()

                except Exception as e:
                    print(f"  [{idx}/{total}] ✗ 页面加载失败: {title_short[:35]}  ({e})")
                    fail += 1
                    try:
                        page.close()
                    except Exception:
                        pass
                    if idx < total:
                        time.sleep(random.uniform(5, 10))
                    continue

                if not pdf_assets_url:
                    print(f"  [{idx}/{total}] ✗ 未能获取 PDF 链接: {title_short[:40]}")
                    fail += 1
                    if idx < total:
                        time.sleep(random.uniform(5, 10))
                    continue

                # 步骤 4：curl_cffi 直接下载（sciencedirectassets.com 无 JS 验证）
                try:
                    headers = dict(_DL_HEADERS)
                    headers["Referer"] = article_url
                    resp = dl_session.get(
                        pdf_assets_url, headers=headers,
                        allow_redirects=True, timeout=90,
                    )
                    ct = resp.headers.get("content-type", "")
                    if is_pdf_bytes(resp.content):
                        size_kb = write_pdf_bytes_atomic(filepath, resp.content) // 1024
                        print(f"  [{idx}/{total}] ✓ {filename}  ({size_kb} KB)")
                        success += 1
                    else:
                        print(f"  [{idx}/{total}] ✗ 非 PDF 响应（{ct[:40]}）: {title_short[:35]}")
                        fail += 1
                except Exception as e:
                    print(f"  [{idx}/{total}] ✗ 下载异常: {title_short[:35]}  ({e})")
                    fail += 1

                if idx < total:
                    time.sleep(random.uniform(5, 10))

        print(f"\n[完成] 成功: {success}  失败: {fail}  跳过: {skip}")

    # ── DevTools PDF 下载（主要方法，无需 Playwright）────────────────────────

    def download_pdfs_devtools(
        self,
        results,
        output_dir,
        debug_port=9222,
        login_wait_seconds=600,
        interactive_login=True,
        event_path=None,
        download_supplements=True,
    ):
        """
        通过 Chrome DevTools Protocol 下载 PDF（纯 websocket-client，无需 Playwright）。

        工作原理：
        1. 连接已运行的 Chrome 调试实例（端口 9222）
        2. 逐篇在新标签页打开 pdfft URL
        3. 通过 Network/Fetch DevTools 事件拦截 PDF 响应字节
        4. 直接写盘，无 Save 对话框、无 Playwright 依赖

        前提：Chrome 已通过机构账号（CARSI/深技大）登录 ScienceDirect。
        """
        total = len(results)
        pdf_records = []
        supplement_records = []
        success = skip = fail = 0
        supplement_success = supplement_failed = supplement_skipped = supplement_not_found = 0

        def _record(article, status, file="", reason=""):
            pdf_records.append(PdfDownloadRecord(
                doi=article.get("doi", ""),
                pii=article.get("pii", ""),
                title=article.get("title", ""),
                status=status,
                file=file,
                reason=reason,
            ))
            safe_write_run_event(
                event_path,
                RunEvent(
                    stage="pdf",
                    status=status,
                    doi=article.get("doi", ""),
                    title=article.get("title", ""),
                    pii=article.get("pii", ""),
                    file=file,
                    reason=reason,
                    counts={
                        "pdf_success": success,
                        "pdf_failed": fail,
                        "pdf_skipped": skip,
                        "pdf_total": total,
                    },
                ),
            )

        def _add_supplement_records(records):
            nonlocal supplement_success, supplement_failed, supplement_skipped, supplement_not_found
            for record in records:
                supplement_records.append(record)
                if record.status == "success":
                    supplement_success += 1
                elif record.status == "failed":
                    supplement_failed += 1
                elif record.status == "skipped":
                    supplement_skipped += 1
                elif record.status == "not_found":
                    supplement_not_found += 1
                safe_write_run_event(
                    event_path,
                    RunEvent(
                        stage="supplement",
                        status=record.status,
                        doi=record.doi,
                        title=record.article_title,
                        pii=record.pii,
                        file=record.file,
                        reason=record.reason,
                        counts={
                            "supplement_success": supplement_success,
                            "supplement_failed": supplement_failed,
                            "supplement_skipped": supplement_skipped,
                            "supplement_not_found": supplement_not_found,
                        },
                    ),
                )

        def _skip_supplements_for_pdf_failure(article, idx, article_file=""):
            if not download_supplements:
                return
            filename = article_file or self._make_pdf_filename(idx, article)
            _add_supplement_records([
                SupplementDownloadRecord(
                    doi=article.get("doi", ""),
                    pii=article.get("pii", ""),
                    article_title=article.get("title", ""),
                    article_file=filename,
                    supplement_index=0,
                    status="skipped",
                    reason="PDF download failed; supplement download not attempted",
                )
            ])

        try:
            import websocket
        except ImportError:
            print("[错误] 需要 websocket-client：pip install websocket-client")
            for idx, article in enumerate(results, 1):
                fail += 1
                filename = self._make_pdf_filename(idx, article)
                _record(article, "failed", file=filename, reason="缺少 websocket-client 依赖")
                _skip_supplements_for_pdf_failure(article, idx, filename)
            return DownloadRunResult(
                pdf_success=0,
                pdf_failed=total,
                pdf_skipped=0,
                pdf_records=pdf_records,
                supplement_success=supplement_success,
                supplement_failed=supplement_failed,
                supplement_skipped=supplement_skipped,
                supplement_not_found=supplement_not_found,
                supplement_records=supplement_records,
            )

        from urllib.request import Request as _Req, urlopen as _urlopen
        from urllib.parse import quote as _quote

        pdf_dir = os.path.join(output_dir, "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)

        print(f"\n[DevTools PDF 下载]  共 {total} 篇，保存至 {pdf_dir}")
        safe_write_run_event(event_path, RunEvent(stage="pdf", status="start", counts={"pdf_total": total}))

        # 启动 / 连接 Chrome
        chrome_was_fresh = not self._is_chrome_debug_ready()
        if chrome_was_fresh:
            print(f"  Debug port is not ready; starting {self.browser_name}...")
            self._launch_chrome_with_debug()
            if not self._is_chrome_debug_ready():
                print("[error] Browser debug port is unavailable; PDF download aborted")
                for idx, article in enumerate(results, 1):
                    fail += 1
                    filename = self._make_pdf_filename(idx, article)
                    _record(article, "failed", file=filename, reason="browser_debug_port_unavailable")
                    _skip_supplements_for_pdf_failure(article, idx, filename)
                self.last_download_next_steps = self.default_download_next_steps()
                return DownloadRunResult(
                    pdf_success=success,
                    pdf_failed=fail,
                    pdf_skipped=skip,
                    pdf_records=pdf_records,
                    supplement_success=supplement_success,
                    supplement_failed=supplement_failed,
                    supplement_skipped=supplement_skipped,
                    supplement_not_found=supplement_not_found,
                    supplement_records=supplement_records,
                )
        else:
            print("  Browser debug port detected")

        base_url = f"http://127.0.0.1:{debug_port}"

        def open_tab(url):
            req = _Req(f"{base_url}/json/new?{_quote(url, safe=':/?&=%')}", method="PUT")
            with _urlopen(req, timeout=20) as r:
                return json.loads(r.read())

        def close_tab(page_id):
            try:
                _urlopen(_Req(f"{base_url}/json/close/{page_id}"), timeout=10)
            except Exception:
                pass

        def _prompt_login(pii=None):
            target = (
                f"{self.BASE_URL}/science/article/pii/{pii}/pdfft"
                if pii else self.BASE_URL
            )
            try:
                open_tab(target)
            except Exception:
                pass
            print("\n" + "=" * 60)
            print(f"  Please finish institutional sign-in in the opened {self.browser_name} window:")
            print("  1. 如果显示学校/机构登录页，请输入你的机构账号")
            print("  2. 如果停留在 ScienceDirect，请点击 Sign in → Access through your institution")
            print("  3. 确认 PDF 能正常显示（看到 PDF 内容，不是登录页）")
            if interactive_login:
                print("  4. 完成后回到此终端，按 Enter 继续")
            else:
                print(f"  4. 本程序会自动轮询权限，最长等待 {login_wait_seconds} 秒")
            print("=" * 60)
            if interactive_login:
                try:
                    input("  >>> 登录完成后按 Enter：")
                except EOFError:
                    print("  [info] Non-interactive mode; polling for access automatically")

        def _wait_for_institutional_access(pii: str) -> bool:
            if interactive_login:
                return _check_institutional_access(pii)
            deadline = time.time() + max(0, login_wait_seconds)
            while time.time() <= deadline:
                if _check_institutional_access(pii):
                    return True
                remaining = int(max(0, deadline - time.time()))
                if remaining <= 0:
                    break
                wait = min(15, remaining)
                print(f"  尚未检测到机构权限，{wait}s 后自动重试...（剩余约 {remaining}s）")
                time.sleep(wait)
            return False

        # ── 权限检查：导航到真实 pdfft URL，判断落地域名 ──────────────────────
        # 文章页面未登录也显示 sciencedirect.com，所以不能用文章页面判断。
        # pdfft URL 在有权限时重定向到 pdf.sciencedirectassets.com（S3 PDF），
        # 没有权限时重定向到登录页或停留在 sciencedirect.com 文章页。
        def _check_institutional_access(pii: str) -> bool:
            """返回 True 表示有机构下载权限。"""
            test_pdf_url = f"{self.BASE_URL}/science/article/pii/{pii}/pdfft"
            tab = None
            try:
                tab = open_tab(test_pdf_url)
                time.sleep(10)  # 等待所有重定向完成
                ws = websocket.create_connection(
                    tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                    "params": {"expression": "location.href", "returnByValue": True}}))
                final_url = ""
                for _ in range(15):
                    msg = json.loads(ws.recv())
                    if msg.get("id") == 1:
                        final_url = msg.get("result", {}).get("result", {}).get("value", "")
                        break
                ws.close()
                # 有权限 → 落到 PDF 资产服务器或 reader 页面
                return is_sciencedirect_pdf_access_url(final_url)
            except Exception as e:
                print(f"  [警告] 权限检查异常: {e}")
                return False
            finally:
                if tab:
                    close_tab(tab["id"])

        test_pii = next((a["pii"] for a in results if a.get("pii")), None)

        if chrome_was_fresh:
            # Fresh debug browser may not have institutional login state.
            _prompt_login(test_pii)

        has_institutional_pdf_access = True
        if test_pii:
            print("  检查机构访问权限（导航至 PDF URL）...")
            has_institutional_pdf_access = _check_institutional_access(test_pii)
            if has_institutional_pdf_access:
                print("  机构访问权限确认 ✓")
            else:
                print("  Institutional PDF access was not detected.")
                _prompt_login(test_pii)
                # 登录后再检查一次
                print("  重新检查权限...")
                if _wait_for_institutional_access(test_pii):
                    has_institutional_pdf_access = True
                    print("  机构访问权限确认 ✓")
                else:
                    has_institutional_pdf_access = False
                    print("  [warning] Still no institutional PDF access; attempting downloads may fail.")
                    self.last_download_next_steps = self.default_download_next_steps()

        print()

        INTER_MIN         = 12   # 常规篇间间隔（秒）
        INTER_MAX         = 22
        SESSION_BREAK_N   = 8    # 每 N 篇主动歇一次（预防封锁）
        SESSION_BREAK_T   = 150  # 歇息时长（秒）
        BLOCK_WAIT_1      = 270  # 第一次被封：等 4.5 分钟
        BLOCK_WAIT_2      = 420  # 仍被封：再等 7 分钟

        # ── 持久标签页（整个下载会话共用一个 tab，减少 tab 开关频率）──────────
        try:
            p_tab = open_tab("about:blank")
        except Exception as e:
            fail += total
            print(f"  [error] Cannot create browser debug tab; PDF download aborted: {e}")
            print(f"\n[完成] 成功: {success}  失败: {fail}  跳过: {skip}")
            for idx, article in enumerate(results, 1):
                filename = self._make_pdf_filename(idx, article)
                _record(article, "failed", file=filename, reason=f"browser_debug_tab_unavailable: {e}")
                _skip_supplements_for_pdf_failure(article, idx, filename)
            self.last_download_next_steps = self.default_download_next_steps()
            return DownloadRunResult(
                pdf_success=success,
                pdf_failed=fail,
                pdf_skipped=skip,
                pdf_records=pdf_records,
                supplement_success=supplement_success,
                supplement_failed=supplement_failed,
                supplement_skipped=supplement_skipped,
                supplement_not_found=supplement_not_found,
                supplement_records=supplement_records,
            )

        def _tab_navigate(url, wait=5.0):
            """在持久标签页内导航到 url，等待页面加载，不抛异常。"""
            try:
                ws2 = websocket.create_connection(
                    p_tab["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
                ws2.settimeout(2)
                mid = [0]

                def _s(method, params=None):
                    mid[0] += 1
                    ws2.send(json.dumps({"id": mid[0], "method": method,
                                        "params": params or {}}))

                _s("Page.enable")
                _s("Page.addScriptToEvaluateOnNewDocument", {"source": _BROWSER_COMPAT_JS})
                _s("Page.navigate", {"url": url})
                deadline2 = time.time() + wait + 10
                while time.time() < deadline2:
                    try:
                        msg = json.loads(ws2.recv())
                        if msg.get("method") == "Page.loadEventFired":
                            break
                    except Exception:
                        pass
                ws2.close()
            except Exception:
                pass
            time.sleep(wait)

        def _tab_eval(expression, timeout=10):
            try:
                ws2 = websocket.create_connection(
                    p_tab["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True)
                ws2.settimeout(2)
                ws2.send(json.dumps({
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": expression, "returnByValue": True},
                }))
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        msg = json.loads(ws2.recv())
                    except Exception:
                        continue
                    if msg.get("id") == 1:
                        ws2.close()
                        return msg.get("result", {}).get("result", {}).get("value", "")
                ws2.close()
            except Exception:
                pass
            return ""

        def _tab_outer_html():
            return _tab_eval("document.documentElement ? document.documentElement.outerHTML : ''", timeout=12)

        def _debug_cookie_header():
            try:
                ws2 = websocket.create_connection(
                    p_tab["webSocketDebuggerUrl"], timeout=10, suppress_origin=True)
                ws2.settimeout(2)
                ws2.send(json.dumps({
                    "id": 1,
                    "method": "Network.getCookies",
                    "params": {
                        "urls": [
                            self.BASE_URL,
                            "https://ars.els-cdn.com",
                            "https://www.sciencedirect.com",
                            "https://www.elsevier.com",
                        ]
                    },
                }))
                deadline = time.time() + 10
                while time.time() < deadline:
                    try:
                        msg = json.loads(ws2.recv())
                    except Exception:
                        continue
                    if msg.get("id") == 1:
                        cookies = msg.get("result", {}).get("cookies", []) or []
                        ws2.close()
                        return "; ".join(
                            f"{cookie.get('name')}={cookie.get('value')}"
                            for cookie in cookies
                            if cookie.get("name") and cookie.get("value")
                        )
                ws2.close()
            except Exception:
                pass
            return ""

        def _ensure_tab():
            """若持久 tab 的 DevTools 连接已失效，重建它。"""
            nonlocal p_tab
            try:
                ws_test = websocket.create_connection(
                    p_tab["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
                ws_test.close()
            except Exception:
                try:
                    close_tab(p_tab["id"])
                except Exception:
                    pass
                try:
                    p_tab = open_tab("about:blank")
                    time.sleep(1)
                except Exception as exc:
                    raise RuntimeError(f"browser_debug_tab_rebuild_failed: {exc}") from exc

        def _fetch_one(pii, pdf_url):
            """
            在持久 tab 里先导航文章页（建立 Cookie 上下文），
            再拦截 pdfft PDF 字节。返回 (bytes|None, note, article_html)。
            """
            try:
                _ensure_tab()
                article_url = f"{self.BASE_URL}/science/article/pii/{pii}"
                _tab_navigate(article_url, wait=random.uniform(4, 6))
                article_html = _tab_outer_html()
                pdf_bytes, note = _dt_capture_pdf(p_tab["webSocketDebuggerUrl"], pdf_url, timeout=45)
                return pdf_bytes, note, article_html
            except Exception as exc:
                return None, str(exc), ""

        def _download_supplements(article, idx, article_file, article_html=""):
            if not download_supplements:
                return
            pii = article.get("pii", "")
            if not pii:
                return
            article_url = f"{self.BASE_URL}/science/article/pii/{pii}"
            if not article_html:
                try:
                    _ensure_tab()
                    _tab_navigate(article_url, wait=random.uniform(3, 5))
                    article_html = _tab_outer_html()
                except Exception:
                    article_html = ""
            cookie_header = _debug_cookie_header()
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": article_url,
            }
            if cookie_header:
                headers["Cookie"] = cookie_header
            supp_session = curl_requests.Session(impersonate="chrome124")
            records = download_supplements_for_article(
                article=article,
                article_index=idx,
                article_file=article_file,
                article_html=article_html,
                article_url=article_url,
                output_dir=output_dir,
                session=supp_session,
                headers=headers,
            )
            _add_supplement_records(records)
            article_success, article_failed, article_skipped, article_not_found = supplement_status_counts(records)
            print(
                f"    [补充材料] 成功/失败/跳过/未发现: "
                f"{article_success}/{article_failed}/{article_skipped}/{article_not_found}"
            )

        downloads_since_break = 0

        try:
            for idx, article in enumerate(results, 1):
                pii = article.get("pii", "")
                title_short = (article.get("title") or "")[:55]

                if not pii:
                    print(f"  [{idx}/{total}] 跳过（无 PII）: {title_short}")
                    skip += 1
                    _record(article, "skipped", reason="无 PII")
                    continue

                filename = self._make_pdf_filename(idx, article)
                filepath = os.path.join(pdf_dir, filename)

                if os.path.exists(filepath):
                    if is_valid_pdf(filepath):
                        print(f"  [{idx}/{total}] 已存在，跳过: {filename}")
                        skip += 1
                        _record(article, "skipped", file=filename, reason="文件已存在")
                        _download_supplements(article, idx, filename)
                        continue
                    try:
                        os.remove(filepath)
                    except OSError:
                        print(f"  [{idx}/{total}] 无效已存在文件无法清理: {filename}")
                        fail += 1
                        _record(article, "failed", file=filename, reason="invalid_existing_pdf")
                        _skip_supplements_for_pdf_failure(article, idx, filename)
                        continue

                pdf_url = article.get("pdf_url") or ""
                if not pdf_url or "pdfft" not in pdf_url:
                    pdf_url = f"{self.BASE_URL}/science/article/pii/{pii}/pdfft"

                pdf_bytes, note, article_html = _fetch_one(pii, pdf_url)

                # 封锁处理：区分「速率限制」和「CAPTCHA」
                if pdf_bytes is None and str(note).startswith("blocked:"):
                    note_low = str(note).lower()
                    is_captcha = any(s in note_low for s in CAPTCHA_SIGNALS)

                    if is_captcha:
                        # CAPTCHA requires one manual browser verification.
                        # 点完后整个会话恢复，后续篇目无需再次干预
                        print(f"\n  🔒 [{idx}/{total}] Elsevier 要求人机验证（CAPTCHA）")
                        safe_write_run_event(
                            event_path,
                            RunEvent(
                                stage="pdf",
                                status="blocked",
                                doi=article.get("doi", ""),
                                title=article.get("title", ""),
                                pii=pii,
                                reason="CAPTCHA",
                                counts={"current": idx, "pdf_total": total},
                            ),
                        )
                        print("  ─────────────────────────────────────────────")
                        print(f"  Switch to the {self.browser_name} window and complete verification:")
                        print("  · 勾选「I'm not a robot」或完成图片验证")
                        if interactive_login:
                            print("  · 验证通过后，回到此终端按 Enter 继续")
                        else:
                            print("  · 验证通过后，本程序会等待片刻后自动重试")
                        print("  ─────────────────────────────────────────────")
                        if interactive_login:
                            try:
                                input("  >>> 验证完成后按 Enter：")
                            except EOFError:
                                time.sleep(30)
                        else:
                            time.sleep(min(max(login_wait_seconds, 30), 180))
                        pdf_bytes, note, article_html = _fetch_one(pii, pdf_url)
                    else:
                        # 速率限制：自动等待后重试（无需人工）
                        print(f"  [{idx}/{total}] ⏳ 速率限制，等 {BLOCK_WAIT_1}s（约 {BLOCK_WAIT_1//60} 分钟）后自动重试...")
                        safe_write_run_event(
                            event_path,
                            RunEvent(
                                stage="pdf",
                                status="blocked",
                                doi=article.get("doi", ""),
                                title=article.get("title", ""),
                                pii=pii,
                                reason="rate_limit",
                                counts={"current": idx, "pdf_total": total},
                            ),
                        )
                        _tab_navigate("about:blank", wait=2)
                        time.sleep(BLOCK_WAIT_1)
                        pdf_bytes, note, article_html = _fetch_one(pii, pdf_url)

                        if pdf_bytes is None and str(note).startswith("blocked:"):
                            print(f"  [{idx}/{total}] ⏳ 仍被限速，再等 {BLOCK_WAIT_2}s（约 {BLOCK_WAIT_2//60} 分钟）...")
                            _tab_navigate("about:blank", wait=2)
                            time.sleep(BLOCK_WAIT_2)
                            pdf_bytes, note, article_html = _fetch_one(pii, pdf_url)

                if pdf_bytes and is_pdf_bytes(pdf_bytes):
                    size_kb = write_pdf_bytes_atomic(filepath, pdf_bytes) // 1024
                    print(f"  [{idx}/{total}] ✓ {filename}  ({size_kb} KB)")
                    success += 1
                    downloads_since_break += 1
                    _record(article, "success", file=filename)
                    _download_supplements(article, idx, filename, article_html)
                else:
                    is_blocked = str(note).startswith("blocked:")
                    tag = "被封锁" if is_blocked else "未捕获PDF"
                    reason = f"{tag}: {str(note)[:160]}"
                    if not has_institutional_pdf_access:
                        reason = f"no_institutional_pdf_access: {str(note)[:160]}"
                    print(f"  [{idx}/{total}] ✗ {tag}: {title_short[:40]}  ({str(note)[:80]})")
                    fail += 1
                    _record(article, "failed", file=filename, reason=reason)
                    _skip_supplements_for_pdf_failure(article, idx, filename)

                if idx < total:
                    # 每 SESSION_BREAK_N 篇成功后主动歇息，避免触发封锁
                    if downloads_since_break >= SESSION_BREAK_N:
                        print(f"  [节流] 已连续下载 {downloads_since_break} 篇，主动歇息 {SESSION_BREAK_T}s ...")
                        _tab_navigate("about:blank", wait=2)
                        time.sleep(SESSION_BREAK_T)
                        downloads_since_break = 0
                    else:
                        time.sleep(random.uniform(INTER_MIN, INTER_MAX))
        finally:
            close_tab(p_tab["id"])

        print(f"\n[完成] 成功: {success}  失败: {fail}  跳过: {skip}")
        if download_supplements:
            print(
                f"[补充材料完成] 成功: {supplement_success}  失败: {supplement_failed}  "
                f"跳过: {supplement_skipped}  未发现: {supplement_not_found}"
            )
        safe_write_run_event(
            event_path,
            RunEvent(
                stage="pdf",
                status="complete",
                counts={
                    "pdf_success": success,
                    "pdf_failed": fail,
                    "pdf_skipped": skip,
                    "pdf_total": total,
                    "supplement_success": supplement_success,
                    "supplement_failed": supplement_failed,
                    "supplement_skipped": supplement_skipped,
                    "supplement_not_found": supplement_not_found,
                },
            ),
        )
        if fail and not self.last_download_next_steps:
            self.last_download_next_steps = self.default_download_next_steps()
        return DownloadRunResult(
            pdf_success=success,
            pdf_failed=fail,
            pdf_skipped=skip,
            pdf_records=pdf_records,
            supplement_success=supplement_success,
            supplement_failed=supplement_failed,
            supplement_skipped=supplement_skipped,
            supplement_not_found=supplement_not_found,
            supplement_records=supplement_records,
        )

    # ── Chrome CDP（保留为备用，调试用）──────────────────────────────────────

    CHROME_BIN = chrome_bin()
    CHROME_DBG_PROFILE = chrome_debug_profile("chrome_dbg_profile")
    CHROME_DBG_PORT = 9222

    def _is_chrome_debug_ready(self):
        """检查 Chrome 调试端口是否已就绪。"""
        import urllib.request
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.CHROME_DBG_PORT}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def _launch_chrome_with_debug(self):
        """
        自动以调试模式启动 Chrome：
        1. 把默认 Profile 的关键浏览器状态复制到临时目录
        2. 用 --user-data-dir + --remote-debugging-port 启动 Chrome
        3. 最多等待 40s，直到调试端口就绪
        返回 Popen 对象，失败返回 None
        """
        import subprocess, shutil

        default_profile = browser_default_profile(self.CHROME_BIN)
        tmp_default = os.path.join(self.CHROME_DBG_PROFILE, "Default")
        os.makedirs(tmp_default, exist_ok=True)

        # 只复制最小浏览器状态。不要默认复制 History、Login Data、Web Data
        # 或 Local Storage 等更敏感状态；登录不足时让用户在调试浏览器中完成认证。
        files_to_copy = BROWSER_PROFILE_COPY_FILES
        dirs_to_copy = BROWSER_PROFILE_COPY_DIRS

        for fname in files_to_copy:
            src = os.path.join(default_profile, fname)
            dst = os.path.join(tmp_default, fname)
            if os.path.exists(src):
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    print(f"  [警告] 复制 {fname} 失败：{e}（将继续，可能需要手动登录）")

        for dname in dirs_to_copy:
            src = os.path.join(default_profile, dname)
            dst = os.path.join(tmp_default, dname)
            if os.path.exists(src):
                try:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                except Exception as e:
                    print(f"  [警告] 同步目录 {dname} 失败：{e}（将继续）")

        # 仅清理调试 profile 的残留锁文件，不影响用户正在使用的 Chrome。
        for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lf = os.path.join(self.CHROME_DBG_PROFILE, lock)
            try:
                os.remove(lf)
            except FileNotFoundError:
                pass

        cmd = [
            self.CHROME_BIN,
            f"--remote-debugging-port={self.CHROME_DBG_PORT}",
            f"--remote-allow-origins=http://127.0.0.1:{self.CHROME_DBG_PORT}",
            f"--user-data-dir={self.CHROME_DBG_PROFILE}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            *BROWSER_DEBUG_EXTRA_ARGS,
        ]

        log_path = chrome_debug_log("chrome_debug.log")
        proc = None
        try:
            with open(log_path, "w") as log_f:
                proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
            print(f"  {self.browser_name} debug browser started (PID {proc.pid}); waiting for port...")
        except FileNotFoundError:
            print(f"  [error] Browser executable not found: {self.CHROME_BIN}")
            print(f"  Tip: install Edge/Chrome, pass --browser-exe, or set {BROWSER_EXE_ENV}.")
            candidates = browser_candidate_paths()
            if candidates:
                print("  已检查候选路径：")
                for candidate in candidates[:10]:
                    print(f"    - {candidate}")
            return None

        # 最多等待 40 秒
        for i in range(40):
            time.sleep(1)
            if self._is_chrome_debug_ready():
                print(f"  Browser debug port is ready ({i+1}s)")
                return proc
            if (i + 1) % 5 == 0:
                print(f"  Waiting for browser startup... ({i+1}s)")

        print(f"  [warning] Browser did not become ready within 40s; log: {log_path}")
        return None

    def open_chrome_for_login(self, target_url=None, keep_page_open=True):
        """
        从终端打开一个带远程调试端口的真实 Chrome，供用户手动完成机构登录。
        """
        target_url = target_url or self.BASE_URL
        if not self._is_chrome_debug_ready():
            print(f"  Starting debug {self.browser_name}...")
            self._launch_chrome_with_debug()

        if not self._is_chrome_debug_ready():
            print("\n[error] Browser debug port is unavailable; check the debug log.")
            return False

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[错误] 需要 playwright：pip install playwright")
            return False

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.CHROME_DBG_PORT}"
            )
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
            try:
                page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
            except Exception:
                pass

            print("\n" + "=" * 60)
            print(f"  {self.browser_name} is open. Finish these steps in the browser:")
            print("  1. 登录 ScienceDirect / 学校机构账号")
            print("  2. 确认能正常打开一篇有权限的文章")
            print("  3. 回到终端按 Enter，继续执行后续抓取")
            print("=" * 60)
            input()

            if not keep_page_open:
                try:
                    page.close()
                except Exception:
                    pass
        return True

    # ── PDF 下载（Chrome CDP）────────────────────────────────────────────────

    # 调试浏览器兼容脚本
    _BROWSER_COMPAT_SCRIPT = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        delete navigator.__proto__.webdriver;
        window.chrome = window.chrome || { runtime: {} };
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
    """

    def _check_sd_access(self, ctx, test_pii=None):
        """
        检查当前 Chrome 是否有机构全文访问权限。
        返回 True 表示有权限，False 表示需要登录（含 CARSI 重定向情形）。
        """
        check_page = ctx.new_page()
        try:
            check_page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
            if test_pii:
                url = f"{self.BASE_URL}/science/article/pii/{test_pii}"
            else:
                url = self.BASE_URL
            check_page.goto(url, timeout=25000, wait_until="domcontentloaded")
            time.sleep(2)
            current_url = check_page.url
            # 被重定向到 ScienceDirect 以外（如 CARSI/Shibboleth 登录页）
            if "sciencedirect.com" not in current_url:
                return False
            # 跳转到 /abs/ 说明只有摘要访问权
            if test_pii and "/abs/" in current_url:
                return False
            # 页面有 Sign in 且无 Remote access 提示 → 未登录
            body_text = check_page.inner_text("body")
            if "Sign in" in body_text and "Remote access" not in body_text:
                return False
            return True
        except Exception:
            return False
        finally:
            check_page.close()

    def _wait_for_login(self, ctx, test_pii=None):
        """
        打开 ScienceDirect 文章页（触发 CARSI 自动重定向），提示用户完成机构登录，
        等待用户在终端按 Enter 确认。
        """
        login_page = ctx.new_page()
        try:
            login_page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
            # 直接访问文章页会触发 CARSI 重定向，比主页更直接
            target = (
                f"{self.BASE_URL}/science/article/pii/{test_pii}"
                if test_pii else self.BASE_URL
            )
            login_page.goto(target, timeout=20000, wait_until="domcontentloaded")
        except Exception:
            pass

        print("\n" + "="*60)
        print(f"  {self.browser_name} may have redirected to the institutional login page.")
        print(f"  Please finish sign-in in {self.browser_name}:")
        print("  · 若显示 SZTU 登录页：直接输入工号/密码登录")
        print("  · 若显示 ScienceDirect：点右上角 Sign in → Access through")
        print("    your institution → 搜索选择你的学校 → 完成登录")
        print("  登录完成后，回到终端按 Enter 继续…")
        print("="*60)
        input()

        try:
            login_page.close()
        except Exception:
            pass

    def download_pdfs_via_chrome(self, results, output_dir):
        """
        通过 Chrome DevTools Protocol 驱动 Chrome 下载 PDF。
        脚本会自动：
          ① 复制默认 Chrome Profile 的持久化 Cookie（可能保留部分登录状态）
          ② 启动带调试端口的 Chrome（不影响你正常使用的 Chrome 数据）
          ③ 检查机构访问权限，若未登录则提示你在 Chrome 中登录（一次性）
          ④ 逐篇访问 PDF 页面并下载到 pdfs/ 子目录
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[错误] 需要 playwright：pip install playwright && playwright install chromium")
            return

        pdf_dir = os.path.join(output_dir, "pdfs")
        os.makedirs(pdf_dir, exist_ok=True)
        total = len(results)
        success = skip = fail = 0

        print(f"\n[浏览器 PDF 下载]  共 {total} 篇，保存至 {pdf_dir}")

        # 如果调试端口未就绪，自动启动 Chrome
        chrome_proc = None
        if not self._is_chrome_debug_ready():
            print(f"  调试端口未就绪，自动启动 {self.browser_name}...")
            chrome_proc = self._launch_chrome_with_debug()
            if not self._is_chrome_debug_ready():
                print("\n[错误] 浏览器调试端口仍不可用，PDF 下载中止")
                print("  请查看日志：cat /tmp/chrome_debug.log")
                return
        else:
            print("  已检测到浏览器调试端口 ✓")

        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{self.CHROME_DBG_PORT}"
                )
            except Exception as e:
                print(f"\n[错误] 连接浏览器失败：{e}")
                return

            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            print(f"  已连接 {self.browser_name} ✓")

            # 检查机构访问权限，取第一篇有 pii 的文章测试
            test_pii = next((a["pii"] for a in results if a.get("pii")), None)
            print("  检查机构访问权限...")
            if not self._check_sd_access(ctx, test_pii):
                # 需要登录
                self._wait_for_login(ctx)
                # 再次检查
                if not self._check_sd_access(ctx, test_pii):
                    print("\n[警告] 仍未检测到机构全文权限，将尝试继续下载（部分论文可能失败）")
                else:
                    print("  机构访问权限确认 ✓")
            else:
                print("  机构访问权限确认 ✓")

            print()

            # 提取浏览器 cookies 供后续 HTTP 下载使用
            browser_cookies = ctx.cookies([
                "https://www.sciencedirect.com",
                "https://www.sciencedirectassets.com",
                "https://pdf.sciencedirectassets.com",
                "https://www.elsevier.com",
            ])
            cookie_header = "; ".join(
                f"{c['name']}={c['value']}" for c in browser_cookies
            )
            dl_session = curl_requests.Session(impersonate="chrome124")
            _DL_HEADERS = {
                "Cookie": cookie_header,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/146.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                          "image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
            }

            for idx, article in enumerate(results, 1):
                pii = article.get("pii", "")
                title_short = article.get("title", "")[:55]
                if not pii:
                    print(f"  [{idx}/{total}] 跳过（无 PII）: {title_short}")
                    skip += 1
                    continue

                filename = self._make_pdf_filename(idx, article)
                filepath = os.path.join(pdf_dir, filename)

                if os.path.exists(filepath):
                    if is_valid_pdf(filepath):
                        print(f"  [{idx}/{total}] 已存在，跳过: {filename}")
                        skip += 1
                        continue
                    try:
                        os.remove(filepath)
                    except OSError:
                        print(f"  [{idx}/{total}] 无效已存在文件无法清理: {filename}")
                        fail += 1
                        continue

                article_url = f"{self.BASE_URL}/science/article/pii/{pii}"

                # ── 策略 A：用搜索结果里的 pdf_url 直接 HTTP 下载 ──────────
                # pdf_url 是带 md5/pid 参数的 pdfft 链接，可直接重定向到
                # pdf.sciencedirectassets.com，并沿用当前授权会话
                pdf_url_from_search = article.get("pdf_url", "")
                downloaded = False

                if pdf_url_from_search and "pdfft" in pdf_url_from_search:
                    try:
                        headers_a = dict(_DL_HEADERS)
                        headers_a["Referer"] = article_url
                        headers_a["sec-fetch-site"] = "same-origin"
                        resp = dl_session.get(
                            pdf_url_from_search,
                            headers=headers_a,
                            allow_redirects=True,
                            timeout=60,
                        )
                        ct = resp.headers.get("content-type", "")
                        if is_pdf_bytes(resp.content):
                            size_kb = write_pdf_bytes_atomic(filepath, resp.content) // 1024
                            print(f"  [{idx}/{total}] ✓ {filename}  ({size_kb} KB)  [直连]")
                            success += 1
                            downloaded = True
                    except Exception:
                        pass  # 静默失败，回退到策略 B

                if downloaded:
                    if idx < total:
                        time.sleep(random.uniform(3, 6))
                    continue

                # ── 策略 B：CDP 加载文章页 → 点击 View PDF → curl_cffi 下载 ─
                page = ctx.new_page()
                try:
                    page.add_init_script(self._BROWSER_COMPAT_SCRIPT)
                    page.goto(article_url, timeout=30000, wait_until="networkidle")
                    time.sleep(1)

                    # 检查是否有下载按钮（有权限才有）
                    try:
                        page.wait_for_selector('a[href*="pdfft"]', timeout=8000)
                    except Exception:
                        page_text = ""
                        try:
                            page_text = page.inner_text("body")[:300]
                        except Exception:
                            pass
                        if "problem providing" in page_text or "crasolve" in page.url:
                            print(
                                f"  [{idx}/{total}] ✗ 文章页当前显示 CAPTCHA 或访问限制"
                            )
                            page.close()
                            fail += 1
                            continue
                        print(f"  [{idx}/{total}] ✗ 无下载按钮（可能无权限）: {title_short[:40]}")
                        fail += 1
                        page.close()
                        continue

                    # 点击按钮，捕获弹出的 PDF 窗口 URL
                    pdf_assets_url = None
                    try:
                        with page.expect_popup(timeout=15000) as popup_info:
                            page.click('a[href*="pdfft"]')
                        popup = popup_info.value
                        pdf_assets_url = popup.url
                        popup.close()
                    except Exception:
                        # 没有弹窗，获取当前 href 作为备用
                        try:
                            pdf_assets_url = page.eval_on_selector(
                                'a[href*="pdfft"]', 'el => el.href'
                            )
                        except Exception:
                            pass
                    page.close()

                    if not pdf_assets_url:
                        raise RuntimeError("无法获取 PDF 链接")

                    # 若是 sciencedirectassets.com 直接下载，否则也尝试
                    headers_b = dict(_DL_HEADERS)
                    headers_b["Referer"] = article_url
                    headers_b["sec-fetch-site"] = "cross-site"
                    resp = dl_session.get(
                        pdf_assets_url,
                        headers=headers_b,
                        allow_redirects=True,
                        timeout=60,
                    )
                    ct = resp.headers.get("content-type", "")
                    if is_pdf_bytes(resp.content):
                        size_kb = write_pdf_bytes_atomic(filepath, resp.content) // 1024
                        print(f"  [{idx}/{total}] ✓ {filename}  ({size_kb} KB)  [CDP+直连]")
                        success += 1
                    else:
                        print(f"  [{idx}/{total}] ✗ 响应非 PDF（{ct[:30]}）: {title_short[:35]}")
                        fail += 1

                except Exception as e:
                    print(f"  [{idx}/{total}] ✗ 失败: {title_short[:40]}  ({e})")
                    fail += 1
                    try:
                        page.close()
                    except Exception:
                        pass

                if idx < total:
                    time.sleep(random.uniform(3, 6))

        print(f"\n[完成] 成功: {success}  失败: {fail}  跳过: {skip}")
        if chrome_proc is not None:
            print(f"\n  提示：调试用的 Chrome 仍在运行 (PID {chrome_proc.pid})")
            print("  如需关闭：pkill -f 'Google Chrome'")


# ──────────────────────────────────────────────────────────────────────────────
# 交互式向导
# ──────────────────────────────────────────────────────────────────────────────

def _input_int(prompt, default):
    raw = input(f"{prompt} [默认 {default}]: ").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default

def _input_optional(prompt):
    raw = input(f"{prompt} [留空跳过]: ").strip()
    return raw if raw else None

def interactive_mode():
    print("=" * 60)
    print("  ScienceDirect 论文抓取工具 v2.0")
    print("=" * 60)

    # ── 机构 Cookie ───────────────────────────────────────────────
    print("\n【机构账号 Cookie】")
    print("  1. 自动从 Chrome 读取（推荐）")
    print("  2. 手动指定 cookie 文件")
    print("  3. 跳过，以游客身份运行")
    cookie_choice = input("  请选择 [1/2/3，默认 1]: ").strip() or "1"

    cookies_file = None
    use_browser_cookies = False
    if cookie_choice == "1":
        use_browser_cookies = True
    elif cookie_choice == "2":
        cookies_file = _input_optional("  Cookie 文件路径（如 cookies.json）")

    scraper = ScienceDirectScraper(cookies_file=cookies_file, use_browser_cookies=use_browser_cookies)

    # ── 搜索模式 ──────────────────────────────────────────────────
    print("\n【搜索模式】")
    modes = {
        "1": ("keyword",         "按关键词搜索"),
        "2": ("journal",         "按期刊名称浏览"),
        "3": ("journal_keyword", "在指定期刊内按关键词搜索"),
        "4": ("author",          "按作者搜索"),
        "5": ("issn",            "按期刊 ISSN 搜索"),
        "6": ("advanced",        "高级搜索（组合多个条件）"),
    }
    for k, (_, desc) in modes.items():
        print(f"  {k}. {desc}")
    choice = input("  请选择 [1-6]: ").strip()
    mode = modes.get(choice, ("keyword", ""))[0]

    # ── 采集参数 ──────────────────────────────────────────────────
    print("\n【搜索参数】")
    query      = _input_optional("  关键词（如 machine learning）")
    journal    = _input_optional("  期刊名称（如 Energy）")
    author     = _input_optional("  作者（如 Zhang Wei）")
    issn       = _input_optional("  期刊 ISSN（如 0360-5442）")
    date_range = _input_optional("  年份范围（如 2020-2024）")
    print("  文章类型: FLA=完整文章  REV=综述  SCO=短通讯  留空=全部")
    article_type = _input_optional("  文章类型")
    count      = _input_int("  最大抓取数量", 50)
    sort_raw   = input("  排序方式 relevance/date [默认 relevance]: ").strip()
    sort_by    = sort_raw if sort_raw in ("relevance", "date") else "relevance"

    # ── 执行搜索 ──────────────────────────────────────────────────
    results = []
    if mode == "keyword":
        results = scraper.search_by_keyword(query or "", count, sort_by, date_range, article_type)
    elif mode == "journal":
        results = scraper.search_by_journal(journal or "", count, sort_by, date_range)
    elif mode == "journal_keyword":
        results = scraper.search_by_journal_keyword(journal or "", query or "", count, sort_by, date_range)
    elif mode == "author":
        results = scraper.search_by_author(author or "", count, sort_by)
    elif mode == "issn":
        results = scraper.search_by_issn(issn or "", count, sort_by, date_range)
    elif mode == "advanced":
        results = scraper.search_advanced(query, journal, author, issn,
                                          date_range, article_type,
                                          count=count, sort_by=sort_by)

    if not results:
        print("\n未获取到任何结果，请检查参数或 cookie。")
        return

    # ── 保存格式 ──────────────────────────────────────────────────
    print("\n【保存格式】")
    fmt_raw = input("  格式 xlsx/csv/json/all [默认 xlsx]: ").strip().lower()
    fmt = fmt_raw if fmt_raw in ("xlsx", "csv", "json", "all") else "xlsx"

    print("\n【PDF 下载】")
    print("  1. 下载 PDF（推荐）")
    print("     读取你 Chrome 浏览器的 Cookie，并通过已授权会话下载")
    print("     前提：Chrome 已通过机构账号（CARSI/深技大）登录 ScienceDirect")
    print("  2. 跳过，只保存文献列表")
    dl_choice = input("  请选择 [1/2，默认 2]: ").strip() or "2"
    download_pdfs = (dl_choice == "1")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [mode]
    if query:   parts.append(query.replace(" ", "_")[:20])
    if journal: parts.append(journal.replace(" ", "_")[:20])
    base = "_".join(parts) + f"_{timestamp}"
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", base)

    if fmt in ("xlsx", "all"):
        scraper.save_to_xlsx(results, base + ".xlsx", output_dir)
    if fmt in ("csv", "all"):
        scraper.save_to_csv(results, base + ".csv", output_dir)
    if fmt in ("json", "all"):
        scraper.save_to_json(results, base + ".json", output_dir)
    if download_pdfs:
        download_result = scraper.download_pdfs_devtools(results, output_dir)
        if isinstance(download_result, DownloadRunResult):
            report_path = write_supplement_download_report(download_result.supplement_records, output_dir)
            print(f"[报告] 补充材料下载明细已保存 -> {report_path}")


# ──────────────────────────────────────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "ScienceDirect 论文抓取工具 v2.0（兼容入口）。"
            "新文献任务请优先使用 paper_batch.py 或 UI「统一批次（推荐）」。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
推荐入口（默认产品路径）:
  python paper_batch.py start --input papers.xlsx --out results --email you@example.com

本脚本为兼容 / 高级 ScienceDirect 专用 CLI。使用示例:
  python sd_scraper.py --interactive
  python sd_scraper.py --open-browser-login
  python sd_scraper.py -m keyword -q "machine learning" -n 100 --browser-cookies --format xlsx --download-pdfs
  python sd_scraper.py -m journal -j "Energy" -n 50 --browser-cookies --sort date --format xlsx
  python sd_scraper.py -m journal_keyword -j "Renewable Energy" -q "solar cell" -n 50 --browser-cookies --download-pdfs
  python sd_scraper.py -m author -a "Zhang Wei" -n 30 --browser-cookies --format all
  python sd_scraper.py -m advanced -q "deep learning" --date 2021-2024 --type REV -n 50 --browser-cookies --download-pdfs
  python sd_scraper.py -m doi_batch --input papers.xlsx --browser-cookies --download-pdfs
        """,
    )
    parser.add_argument("--interactive", action="store_true", help="启动交互式向导")
    parser.add_argument("--open-browser-login", action="store_true",
                        help="先从终端打开真实浏览器，手动完成机构登录后再继续")
    parser.add_argument("--login-only", action="store_true",
                        help="只打开浏览器并等待你登录，不执行搜索")
    parser.add_argument("-m", "--mode",
                        choices=["keyword", "journal", "journal_keyword",
                                 "author", "issn", "advanced", "doi_batch"],
                        help="搜索模式")
    parser.add_argument("-q", "--query",   help="搜索关键词（支持 AND/OR/NOT）")
    parser.add_argument("-j", "--journal", help="期刊名称")
    parser.add_argument("-a", "--author",  help="作者姓名")
    parser.add_argument("--issn",          help="期刊 ISSN")
    parser.add_argument("-n", "--count",   type=int, default=50, help="最大抓取数量（默认 50）")
    parser.add_argument("--date",          help="年份范围，如 2020-2024")
    parser.add_argument("--sort",          choices=["relevance", "date"], default="relevance")
    parser.add_argument("--type",  dest="article_type",
                        choices=["FLA", "REV", "SCO", "EDB", "ERR", "COR"],
                        help="文章类型: FLA 完整文章 / REV 综述 / SCO 短通讯")
    parser.add_argument("--open-access",   action="store_true", help="仅抓取开放获取文章")
    parser.add_argument("--browser-cookies", dest="browser_cookies", action="store_true",
                        help="自动从本机 Chrome 读取 cookie")
    parser.add_argument("--cookies",       help="Cookie JSON 文件路径")
    parser.add_argument("--browser-exe",
                        help="Browser executable path for institutional login/download (defaults to Chrome, then Edge)")
    parser.add_argument("--format",        choices=["xlsx", "csv", "json", "all"], default="xlsx")
    parser.add_argument("--download-pdfs", action="store_true",
                        help="在保存文献列表后，继续下载对应 PDF")
    parser.add_argument("--no-download-supplements", action="store_true",
                        help="下载 PDF 时不自动下载 ScienceDirect 补充材料")
    parser.add_argument("--output",        help="输出目录（默认 ./results/）")
    parser.add_argument("--filename",      help="自定义输出文件名（不含扩展名）")
    parser.add_argument("--input", dest="input_file",
                        help="DOI 批量下载输入文件（.xlsx/.xlsm/.csv/.tsv/.txt/.md/.markdown）")
    parser.add_argument("--doi-column",
                        help="DOI 列名；不填时自动识别 doi/DOI/DOI号")
    parser.add_argument("--sheet",
                        help="Excel 工作表名；不填时读取第一个工作表")
    parser.add_argument("--resume-from",
                        help="DOI 批量断点恢复目录；仅对 doi_batch 模式生效")
    parser.add_argument("--auto-retry-input", action="store_true",
                        help="DOI 批量任务结束后自动生成可重试 DOI CSV；仅对 doi_batch 模式生效")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.interactive or len(sys.argv) == 1:
        interactive_mode()
        return

    if args.login_only and args.mode:
        print("提示: --login-only 会忽略搜索参数，只负责打开浏览器供你登录。")
    if args.login_only and not args.open_browser_login:
        args.open_browser_login = True

    if not args.mode and not args.login_only:
        parser.print_help()
        return
    if args.resume_from and args.mode != "doi_batch":
        print("提示: --resume-from 仅支持 doi_batch 模式，当前模式将忽略该参数。")
    if args.auto_retry_input and args.mode != "doi_batch":
        print("提示: --auto-retry-input 仅支持 doi_batch 模式，当前模式将忽略该参数。")

    scraper = ScienceDirectScraper(
        cookies_file=args.cookies,
        use_browser_cookies=args.browser_cookies,
        browser_exe=args.browser_exe,
    )

    if args.open_browser_login:
        ok = scraper.open_chrome_for_login(keep_page_open=True)
        if not ok:
            return
        if args.login_only:
            print(f"\n{scraper.browser_name} will stay open and keep the current login state.")
            print("接下来请直接运行真正的抓取命令，例如：")
            print('python sd_scraper.py -m keyword -q "machine learning" -n 20 --browser-cookies --format xlsx --download-pdfs')
            return

    if args.mode == "doi_batch":
        if not args.input_file:
            print("错误: doi_batch 模式需要 --input 参数")
            return

        cookie_message = ""
        if args.cookies:
            cookie_check = check_cookie_json(args.cookies)
            cookie_message = cookie_check.message
            print(f"[Cookie 检查] {cookie_message}")
            if not cookie_check.is_usable:
                print("[警告] Cookie 文件可能无法用于 ScienceDirect PDF 下载，将继续尝试。")
        elif args.download_pdfs and args.browser_cookies:
            cookie_message = "未选择 Cookie JSON 文件；将尝试从本机浏览器/调试会话获取 Cookie"
        elif args.download_pdfs:
            cookie_message = "未选择 Cookie JSON 文件；PDF 下载可能需要在调试浏览器中手动登录"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = args.filename or f"doi_batch_{timestamp}"
        output_root = args.output or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "results")
        output_dir = os.path.join(output_root, base)
        os.makedirs(output_dir, exist_ok=True)
        event_path = os.path.join(output_dir, "run_events.jsonl")
        print(f"[报告] 结构化事件 -> {event_path}")

        resume_success_dois = set()
        if args.resume_from:
            resume_success_dois = load_resume_success_dois(args.resume_from)
            print(f"[断点恢复] 从 {args.resume_from} 读取到 {len(resume_success_dois)} 条已成功 PDF DOI，将跳过这些 DOI。")
            safe_write_run_event(
                event_path,
                RunEvent(
                    stage="resume",
                    status="loaded",
                    reason=str(args.resume_from),
                    counts={"success_dois": len(resume_success_dois)},
                ),
            )

        results, failures = scraper.resolve_doi_batch(
            args.input_file,
            doi_column=args.doi_column,
            sheet_name=args.sheet,
            resume_success_dois=resume_success_dois,
            event_path=event_path,
        )

        resolved_path = ""
        if results:
            resolved_path = scraper.save_to_xlsx(results, "doi_batch_resolved.xlsx", output_dir)
        else:
            print("\n未解析到任何 ScienceDirect DOI。")

        failed_path = scraper.save_failed_doi_report(failures, "doi_batch_failed.csv", output_dir)

        pdf_success = pdf_failed = pdf_skipped = 0
        pdf_records = []
        supplement_success = supplement_failed = supplement_skipped = supplement_not_found = 0
        supplement_records = []
        supplement_report_path = ""
        download_supplements = args.download_pdfs and not args.no_download_supplements
        if args.download_pdfs and results:
            download_result = scraper.download_pdfs_devtools(
                results,
                output_dir,
                event_path=event_path,
                download_supplements=download_supplements,
            )
            if download_result:
                pdf_success, pdf_failed, pdf_skipped, pdf_records = download_result
                if isinstance(download_result, DownloadRunResult):
                    supplement_success = download_result.supplement_success
                    supplement_failed = download_result.supplement_failed
                    supplement_skipped = download_result.supplement_skipped
                    supplement_not_found = download_result.supplement_not_found
                    supplement_records = download_result.supplement_records
            else:
                pdf_failed = len(results)
                pdf_records = [
                    PdfDownloadRecord(
                        doi=item.get("doi", ""),
                        pii=item.get("pii", ""),
                        title=item.get("title", ""),
                        status="failed",
                        reason="PDF 下载流程未返回状态",
                    )
                    for item in results
                ]
        elif args.download_pdfs:
            print("没有可下载的解析结果，跳过 PDF 下载。")
        else:
            pdf_records = [
                PdfDownloadRecord(
                    doi=item.get("doi", ""),
                    pii=item.get("pii", ""),
                    title=item.get("title", ""),
                    status="not_requested",
                    reason="未勾选 PDF 下载",
                )
                for item in results
            ]

        pdf_report_path = write_pdf_download_report(pdf_records, output_dir)
        if download_supplements and results:
            supplement_report_path = str(write_supplement_download_report(supplement_records, output_dir))
        retry_input_path = ""
        retry_input_count = 0
        retry_input_excluded_count = 0
        if args.auto_retry_input:
            retry_result = write_retry_input_from_reports(
                pdf_report_path,
                failed_path,
                output_dir,
            )
            retry_input_path = retry_result.path
            retry_input_count = retry_result.row_count
            retry_input_excluded_count = retry_result.excluded_count
            if retry_result.path:
                print(
                    f"[报告] 重试输入已保存 -> {retry_result.path}  "
                    f"（可重试 {retry_result.row_count} 条；排除 {retry_result.excluded_count} 条）"
                )
            else:
                print(f"[报告] 未发现可重试失败 DOI，未生成重试输入。排除 {retry_result.excluded_count} 条。")
        handoff_paths = write_student_handoff(
            output_dir,
            resolved_records=results,
            failed_records=failures,
            pdf_records=pdf_records,
            supplement_records=supplement_records,
            merged_input_path=args.input_file,
            resolved_path=resolved_path,
            failed_path=failed_path,
            pdf_report_path=pdf_report_path,
            supplement_report_path=supplement_report_path,
        )
        total_doi = getattr(
            scraper,
            "last_doi_batch_total_doi",
            len(results) + sum(1 for item in failures if item.get("doi")),
        )
        summary = RunSummary(
            input_path=args.input_file,
            output_dir=output_dir,
            total_doi=total_doi,
            resolved_count=len(results),
            failure_reasons=failure_reason_counts(failures),
            pdf_success=pdf_success,
            pdf_failed=pdf_failed,
            pdf_skipped=pdf_skipped,
            resolved_path=resolved_path,
            failed_path=failed_path,
            pdf_report_path=str(pdf_report_path),
            cookie_message=cookie_message,
            retry_input_path=retry_input_path,
            retry_input_count=retry_input_count,
            retry_input_excluded_count=retry_input_excluded_count,
            supplement_requested=download_supplements and bool(results),
            supplement_success=supplement_success,
            supplement_failed=supplement_failed,
            supplement_skipped=supplement_skipped,
            supplement_not_found=supplement_not_found,
            supplement_report_path=supplement_report_path,
            browser_message=scraper.last_browser_message,
            download_next_steps=scraper.last_download_next_steps,
            student_readme_path=str(handoff_paths.readme_path),
            paper_index_path=str(handoff_paths.paper_index_path),
            paper_index_xlsx_path=str(handoff_paths.paper_index_xlsx_path),
            failure_next_steps_path=str(handoff_paths.failure_next_steps_path),
            library_index_path=str(handoff_paths.library_index_path),
        )
        summary_path = write_run_summary(summary)
        summary_json_path = write_run_summary_json(summary, event_path=event_path)
        print(f"[报告] PDF 下载明细已保存 -> {pdf_report_path}")
        if supplement_report_path:
            print(f"[报告] 补充材料下载明细已保存 -> {supplement_report_path}")
        print(f"[报告] 研究生查看入口 -> {handoff_paths.student_dir}")
        print(f"[报告] 任务摘要已保存 -> {summary_path}")
        print(f"[报告] JSON 摘要已保存 -> {summary_json_path}")
        return

    results = []
    if args.mode == "keyword":
        if not args.query:
            print("错误: keyword 模式需要 -q 参数"); return
        results = scraper.search_by_keyword(
            args.query, args.count, args.sort, args.date, args.article_type)
    elif args.mode == "journal":
        if not args.journal:
            print("错误: journal 模式需要 -j 参数"); return
        results = scraper.search_by_journal(
            args.journal, args.count, args.sort, args.date)
    elif args.mode == "journal_keyword":
        if not args.journal or not args.query:
            print("错误: journal_keyword 模式需要 -j 和 -q 参数"); return
        results = scraper.search_by_journal_keyword(
            args.journal, args.query, args.count, args.sort, args.date)
    elif args.mode == "author":
        if not args.author:
            print("错误: author 模式需要 -a 参数"); return
        results = scraper.search_by_author(args.author, args.count, args.sort)
    elif args.mode == "issn":
        if not args.issn:
            print("错误: issn 模式需要 --issn 参数"); return
        results = scraper.search_by_issn(
            args.issn, args.count, args.sort, args.date)
    elif args.mode == "advanced":
        results = scraper.search_advanced(
            query=args.query, journal=args.journal, author=args.author,
            issn=args.issn, date_range=args.date, article_type=args.article_type,
            open_access_only=args.open_access,
            count=args.count, sort_by=args.sort)

    if not results:
        print("\n未获取到任何结果。")
        return

    if args.filename:
        base = args.filename
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        parts = [args.mode]
        if args.query:   parts.append(args.query.replace(" ", "_")[:20])
        if args.journal: parts.append(args.journal.replace(" ", "_")[:20])
        base = "_".join(parts) + f"_{timestamp}"

    output_dir = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "results")

    if args.format in ("xlsx", "all"):
        scraper.save_to_xlsx(results, base + ".xlsx", output_dir)
    if args.format in ("csv", "all"):
        scraper.save_to_csv(results, base + ".csv", output_dir)
    if args.format in ("json", "all"):
        scraper.save_to_json(results, base + ".json", output_dir)
    if args.download_pdfs:
        download_result = scraper.download_pdfs_devtools(
            results,
            output_dir,
            download_supplements=not args.no_download_supplements,
        )
        if download_result:
            pdf_success, pdf_failed, pdf_skipped, pdf_records = download_result
            pdf_report_path = write_pdf_download_report(pdf_records, output_dir)
            print(f"[报告] PDF 下载明细已保存 -> {pdf_report_path}")
        if not args.no_download_supplements and isinstance(download_result, DownloadRunResult):
            report_path = write_supplement_download_report(download_result.supplement_records, output_dir)
            print(f"[报告] 补充材料下载明细已保存 -> {report_path}")


if __name__ == "__main__":
    main()
