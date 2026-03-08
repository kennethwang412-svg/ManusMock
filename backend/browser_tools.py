"""
浏览器搜索工具 -- 用 Playwright 真实打开浏览器执行搜索并录制视频。

返回值包含两部分：
  - text_result: 提取的搜索结果文本（供 Reasoner 使用）
  - video_filename: 录制的 .webm 视频文件名（供前端 Sandbox 播放）
"""

import re
import time
import urllib.parse
import ctypes
from pathlib import Path
import threading
from concurrent.futures import Future

from playwright.sync_api import sync_playwright

_topmost_stop_event = threading.Event()

_user32 = ctypes.windll.user32
_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def _find_chromium_hwnds() -> list:
    """找到所有 Chromium 浏览器窗口句柄。"""
    hwnds = []
    try:
        def callback(hwnd, _):
            if not _user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value
            if title and ("Chromium" in title or "Chrome" in title):
                hwnds.append(int(hwnd))
            return True
        _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    except Exception:
        pass
    return hwnds


def _set_topmost(hwnd):
    """将窗口设为 TOPMOST 并尝试激活（不模拟任何按键）。"""
    try:
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        SW_SHOW = 5

        _user32.ShowWindow(hwnd, SW_SHOW)
        _user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )

        fg_thread = _user32.GetWindowThreadProcessId(
            _user32.GetForegroundWindow(), None
        )
        my_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        if fg_thread != my_thread:
            _user32.AttachThreadInput(my_thread, fg_thread, True)
            _user32.SetForegroundWindow(hwnd)
            _user32.AttachThreadInput(my_thread, fg_thread, False)
        else:
            _user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _topmost_loop():
    """后台线程：持续将 Chromium 窗口置顶。"""
    while not _topmost_stop_event.is_set():
        for hwnd in _find_chromium_hwnds():
            _set_topmost(hwnd)
        _topmost_stop_event.wait(1.0)


def _start_topmost_watcher():
    """启动置顶守护线程。"""
    _topmost_stop_event.clear()
    t = threading.Thread(target=_topmost_loop, daemon=True)
    t.start()
    return t


def _stop_topmost_watcher():
    """停止置顶守护线程。"""
    _topmost_stop_event.set()

STATIC_DIR = Path(__file__).parent / "static"
VIDEO_DIR = STATIC_DIR / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(text: str, max_len: int = 40) -> str:
    clean = re.sub(r'[\\/:*?"<>|\s]+', "_", text)
    return clean[:max_len].strip("_")


def browser_search(query: str, task_id: int = 0, engine: str = "baidu") -> dict:
    """
    用真实浏览器执行搜索并录制全过程视频。
    在独立线程中运行以兼容 asyncio 事件循环。
    """
    result_future = Future()

    def _run():
        try:
            res = _browser_search_sync(query, task_id, engine)
            result_future.set_result(res)
        except Exception as e:
            result_future.set_exception(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return result_future.result(timeout=180)


def _extract_page_content(page, max_chars: int = 800) -> str:
    """从详情页提取正文内容。"""
    for selector in ["article", "main", ".post-content", ".article-content", ".content", "#content"]:
        el = page.locator(selector).first
        if el.count():
            try:
                text = el.inner_text(timeout=5000)
                if len(text.strip()) > 50:
                    return text.strip()[:max_chars]
            except Exception:
                continue
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
        return body_text.strip()[:max_chars]
    except Exception:
        return ""


def _collect_result_links(page, engine: str, max_links: int = 3) -> list:
    """从搜索结果页收集前 N 个可点击的链接 URL。"""
    links = []
    if engine == "baidu":
        items = page.locator("#content_left .result h3 a, #content_left .c-container h3 a").all()
    else:
        items = page.locator("#search .g a h3").locator("..").all()

    for item in items:
        if len(links) >= max_links:
            break
        try:
            href = item.get_attribute("href") or ""
            if href and href.startswith("http"):
                links.append(href)
            elif href:
                links.append(href)
        except Exception:
            continue
    return links


def _browser_search_sync(query: str, task_id: int, engine: str) -> dict:
    tag = _sanitize_filename(query)
    video_prefix = f"task{task_id}_{tag}"

    if engine == "google":
        search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    else:
        search_url = f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}"

    text_result = ""
    video_filename = ""
    detail_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--window-position=200,80",
            ],
        )
        context = browser.new_context(
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720},
            locale="zh-CN",
        )
        page = context.new_page()
        _start_topmost_watcher()

        try:
            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(1)

            if engine == "google":
                text_result = _extract_google_results(page)
            else:
                text_result = _extract_baidu_results(page)

            page.evaluate("window.scrollBy(0, 300)")
            time.sleep(0.6)
            page.evaluate("window.scrollBy(0, 300)")
            time.sleep(0.6)

            result_links = _collect_result_links(page, engine, max_links=3)

            for idx, link in enumerate(result_links):
                try:
                    page.goto(link, timeout=12000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    time.sleep(0.8)

                    page_title = page.title() or f"页面 {idx + 1}"

                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, 250)")
                        time.sleep(0.5)

                    content = _extract_page_content(page)

                    if content:
                        detail_results.append(
                            f"\n--- 详情页 [{idx + 1}] {page_title} ---\n"
                            f"链接: {link}\n"
                            f"内容:\n{content}"
                        )

                    page.go_back(timeout=8000)
                    time.sleep(0.5)

                except Exception as e:
                    detail_results.append(f"\n--- 详情页 [{idx + 1}] 访问失败: {e} ---")
                    try:
                        page.goto(search_url, timeout=10000, wait_until="domcontentloaded")
                        time.sleep(0.5)
                    except Exception:
                        pass

        except Exception as e:
            text_result = f"[浏览器搜索] 执行出错: {e}"

        tmp_video_path = page.video.path()
        _stop_topmost_watcher()
        context.close()
        browser.close()

    if detail_results:
        text_result += "\n\n" + "\n".join(detail_results)

    if tmp_video_path and Path(tmp_video_path).exists():
        final_name = f"{video_prefix}_{Path(tmp_video_path).stem}.webm"
        final_path = VIDEO_DIR / final_name
        Path(tmp_video_path).rename(final_path)
        video_filename = final_name

    return {
        "text_result": text_result or "[浏览器搜索] 未提取到搜索结果",
        "video_filename": video_filename,
    }


def _extract_baidu_results(page, max_results: int = 5) -> str:
    results = []
    items = page.locator("#content_left .result, #content_left .c-container").all()

    for i, item in enumerate(items[:max_results]):
        try:
            title_el = item.locator("h3").first
            title = title_el.inner_text(timeout=3000) if title_el.count() else ""

            link = ""
            a_el = item.locator("h3 a").first
            if a_el.count():
                link = a_el.get_attribute("href") or ""

            snippet = ""
            for sel in [".c-abstract", ".content-right_8Zs40", "span.content-right_8Zs40", ".c-span-last"]:
                snippet_el = item.locator(sel).first
                if snippet_el.count():
                    snippet = snippet_el.inner_text(timeout=3000)
                    break

            if not snippet:
                snippet = item.inner_text(timeout=3000)[:200]

            if title:
                results.append(f"[{i+1}] {title}\n    链接: {link}\n    内容: {snippet}")
        except Exception:
            continue

    return "\n\n".join(results) if results else "[百度] 未提取到搜索结果"


def _extract_google_results(page, max_results: int = 5) -> str:
    results = []
    items = page.locator("#search .g").all()

    for i, item in enumerate(items[:max_results]):
        try:
            title_el = item.locator("h3").first
            title = title_el.inner_text(timeout=3000) if title_el.count() else ""

            link = ""
            a_el = item.locator("a").first
            if a_el.count():
                link = a_el.get_attribute("href") or ""

            snippet = ""
            snippet_el = item.locator("[data-sncf], .VwiC3b, .IsZvec").first
            if snippet_el.count():
                snippet = snippet_el.inner_text(timeout=3000)

            if title:
                results.append(f"[{i+1}] {title}\n    链接: {link}\n    内容: {snippet}")
        except Exception:
            continue

    return "\n\n".join(results) if results else "[Google] 未提取到搜索结果"
