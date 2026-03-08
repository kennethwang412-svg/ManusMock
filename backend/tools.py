"""
工具注册表 —— 维护所有可供 Executor 调度的工具。

已实现工具：
- tavily_search: Tavily AI 搜索（推荐，返回结构化摘要）
- serper_search: Serper Google 搜索（快速，返回 Google 原始结果）
- baidu_search: 百度千帆智能搜索（中文优化，返回百度搜索结果）
- browser_search: 浏览器可视化搜索（打开真实浏览器搜索并录制视频）
"""

import json
from pathlib import Path

import requests
import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_tool_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("tools", {})


# ============================================================
#  Tavily Search
# ============================================================
def tavily_search(query: str, max_results: int = 5) -> str:
    cfg = _load_tool_config().get("tavily", {})
    api_key = cfg.get("api_key", "")
    if not api_key:
        return "[Tavily] 错误: 未配置 API Key"

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            include_answer=True,
            search_depth="basic",
        )

        results = []
        if response.get("answer"):
            results.append(f"【AI 摘要】{response['answer']}")

        for i, r in enumerate(response.get("results", [])[:max_results], 1):
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("content", "")
            results.append(f"[{i}] {title}\n    链接: {url}\n    内容: {content}")

        return "\n\n".join(results) if results else "[Tavily] 未找到相关结果"
    except Exception as e:
        return f"[Tavily] 搜索失败: {e}"


# ============================================================
#  Serper (Google Search)
# ============================================================
def serper_search(query: str, max_results: int = 5) -> str:
    cfg = _load_tool_config().get("serper", {})
    api_key = cfg.get("api_key", "")
    if not api_key:
        return "[Serper] 错误: 未配置 API Key"

    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results, "gl": "cn", "hl": "zh-cn"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []

        kg = data.get("knowledgeGraph")
        if kg:
            desc = kg.get("description", "")
            if desc:
                results.append(f"【知识图谱】{kg.get('title', '')}: {desc}")

        for i, item in enumerate(data.get("organic", [])[:max_results], 1):
            title = item.get("title", "")
            link = item.get("link", "")
            snippet = item.get("snippet", "")
            results.append(f"[{i}] {title}\n    链接: {link}\n    内容: {snippet}")

        return "\n\n".join(results) if results else "[Serper] 未找到相关结果"
    except Exception as e:
        return f"[Serper] 搜索失败: {e}"


# ============================================================
#  百度千帆智能搜索
# ============================================================
def baidu_search(query: str, max_results: int = 5) -> str:
    cfg = _load_tool_config().get("baidu", {})
    api_key = cfg.get("api_key", "")
    if not api_key:
        return "[百度千帆] 错误: 未配置 API Key"

    try:
        resp = requests.post(
            "https://qianfan.baidubce.com/v2/ai_search/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "messages": [{"role": "user", "content": query}],
                "search_source": "baidu_search_v2",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []

        choices = data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            if content:
                results.append(f"【百度AI摘要】{content}")

        search_results = data.get("search_results", [])
        for i, item in enumerate(search_results[:max_results], 1):
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("content", item.get("snippet", ""))
            results.append(f"[{i}] {title}\n    链接: {url}\n    内容: {snippet}")

        return "\n\n".join(results) if results else "[百度千帆] 未找到相关结果"
    except Exception as e:
        return f"[百度千帆] 搜索失败: {e}"


# ============================================================
#  Browser Search (可视化搜索 + 录屏)
# ============================================================
_last_browser_video = {"filename": ""}


def browser_search_wrapper(query: str, task_id: int = 0) -> str:
    from browser_tools import browser_search as _bs
    result = _bs(query=query, task_id=task_id, engine="baidu")
    _last_browser_video["filename"] = result.get("video_filename", "")
    return result.get("text_result", "[浏览器搜索] 无结果")


def get_last_browser_video() -> str:
    return _last_browser_video["filename"]


# ============================================================
#  工具注册表
# ============================================================
TOOL_REGISTRY = [
    {
        "name": "tavily_search",
        "description": "Tavily AI 搜索引擎。返回结构化的网页搜索结果和 AI 生成的摘要，适合需要高质量、结构化搜索结果的场景。支持全球搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或查询语句",
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回的最大结果数量，默认为 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "function": tavily_search,
    },
    {
        "name": "serper_search",
        "description": "Serper Google 搜索引擎。通过 Google 搜索获取实时结果，包含知识图谱和网页摘要，速度快（1-2秒），适合需要 Google 搜索结果的场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或查询语句",
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回的最大结果数量，默认为 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "function": serper_search,
    },
    {
        "name": "baidu_search",
        "description": "百度千帆智能搜索。基于百度搜索引擎，对中文内容优化最好，返回百度搜索结果和 AI 摘要，适合中文搜索场景。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或查询语句",
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回的最大结果数量，默认为 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "function": baidu_search,
    },
    {
        "name": "browser_search",
        "description": "浏览器深度搜索。打开真实浏览器执行搜索，点击进入前3个搜索结果页面提取详细内容，并录制全过程视频。用户可在 Sandbox 中观看完整的搜索-浏览-阅读过程回放。速度较慢（30-60秒），但能获取更丰富的页面内容并提供可视化体验。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或查询语句",
                },
                "task_id": {
                    "type": "integer",
                    "description": "当前子任务的编号，用于视频文件命名",
                    "default": 0,
                },
            },
            "required": ["query"],
        },
        "function": browser_search_wrapper,
    },
]


def get_tool_descriptions() -> str:
    lines = []
    for i, tool in enumerate(TOOL_REGISTRY, 1):
        params = tool["parameters"]["properties"]
        param_parts = []
        for pname, pinfo in params.items():
            required = pname in tool["parameters"].get("required", [])
            req_tag = "必填" if required else "可选"
            param_parts.append(f"    - {pname} ({pinfo['type']}, {req_tag}): {pinfo['description']}")
        params_text = "\n".join(param_parts)
        lines.append(f"  {i}. {tool['name']}: {tool['description']}\n   参数:\n{params_text}")
    return "\n".join(lines)


def get_tool_by_name(name: str):
    for tool in TOOL_REGISTRY:
        if tool["name"] == name:
            return tool
    return None
