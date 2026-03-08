import sys
import io
import json
import asyncio
from pathlib import Path
from datetime import datetime

import yaml
from openai import OpenAI
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.staticfiles import StaticFiles
from tools import get_tool_descriptions, get_tool_by_name, get_last_browser_video
from prompts import PLANNER_SYSTEM_PROMPT, EXECUTOR_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_client(role: str = "default"):
    cfg = load_config()
    ds = cfg["deepseek"]
    client = OpenAI(api_key=ds["api_key"], base_url=ds["base_url"])

    if role == "planner":
        model = cfg.get("planner", {}).get("model", "deepseek-chat")
    elif role == "executor":
        model = cfg.get("executor", {}).get("model", "deepseek-chat")
    elif role == "verify":
        model = cfg.get("verify", {}).get("model", "deepseek-chat")
    else:
        model = ds.get("model", "deepseek-reasoner")

    return client, model


app = FastAPI(title="OpenManus API")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "videos").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def extract_json(raw: str) -> dict:
    json_str = raw
    if "```json" in raw:
        json_str = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        json_str = raw.split("```")[1].split("```")[0]
    return json.loads(json_str.strip())


def call_planner(client: OpenAI, model: str, user_message: str) -> dict:
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]
    response = client.chat.completions.create(model=model, messages=messages)
    raw = response.choices[0].message.content or ""
    return extract_json(raw)


def call_executor(client: OpenAI, model: str, task_description: str) -> dict:
    tool_desc = get_tool_descriptions()
    system_prompt = EXECUTOR_SYSTEM_PROMPT.format(tool_descriptions=tool_desc)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_description},
    ]
    response = client.chat.completions.create(model=model, messages=messages)
    raw = response.choices[0].message.content or ""
    return extract_json(raw)


async def chat_stream(user_message: str):
    now = datetime.now().strftime("%H:%M")

    print(f"\n{'='*60}")
    print(f"[{now}] 收到前端消息: {user_message}")
    print(f"{'='*60}")

    # ---- 阶段 1: 规划中 ----
    yield sse_event("status", {"phase": "planning"})

    planner_client, planner_model = get_client("planner")
    print(f"\n[Planner] 使用模型: {planner_model}")

    try:
        plan = call_planner(planner_client, planner_model, user_message)
    except Exception as e:
        print(f"[Planner] 规划失败: {e}")
        plan = {
            "goal": user_message,
            "tasks": [{"id": 1, "description": "直接回答用户问题", "depends_on": []}],
            "final_answer": "直接回复用户",
        }

    print(f"\n[Planner] 目标: {plan.get('goal', '')}")
    print(f"[Planner] 子任务数: {len(plan.get('tasks', []))}")
    for t in plan.get("tasks", []):
        deps = f" (依赖: {t['depends_on']})" if t.get("depends_on") else ""
        print(f"  [{t['id']}] {t['description']}{deps}")

    # ---- 阶段 2: 发送 TODO 清单 ----
    todo_list = [
        {"id": t["id"], "description": t["description"], "status": "pending"}
        for t in plan.get("tasks", [])
    ]
    yield sse_event("plan", {
        "goal": plan.get("goal", ""),
        "tasks": todo_list,
        "final_answer": plan.get("final_answer", ""),
    })

    await asyncio.sleep(1.2)

    yield sse_event("status", {"phase": "executing"})

    # ---- 阶段 3: Executor 逐个执行子任务 ----
    executor_client, executor_model = get_client("executor")
    print(f"\n{'─'*60}")
    print(f"[Executor] 使用模型: {executor_model}")
    print(f"[Executor] 开始逐个执行 {len(plan.get('tasks', []))} 个子任务")
    print(f"{'─'*60}")

    task_results = {}

    for task in plan.get("tasks", []):
        task_id = task["id"]

        yield sse_event("task_start", {"id": task_id})
        print(f"\n┌─ 子任务 [{task_id}]: {task['description']}")

        try:
            decision = call_executor(executor_client, executor_model, task["description"])
        except Exception as e:
            print(f"│  [Executor] 决策失败: {e}")
            decision = {"tool": "none", "args": {}, "thought": "决策失败，跳过工具调用"}

        tool_name = decision.get("tool", "none")
        tool_args = decision.get("args", {})
        thought = decision.get("thought", "")

        print(f"│  [Executor 输出] 选择工具: {tool_name}")
        print(f"│  [Executor 输出] 调用参数: {json.dumps(tool_args, ensure_ascii=False)}")
        print(f"│  [Executor 输出] 决策理由: {thought}")

        result = ""
        video_url = ""
        if tool_name != "none":
            tool_def = get_tool_by_name(tool_name)
            if tool_def:
                print(f"│  [工具调用] 正在执行 {tool_name}...")
                if tool_name == "browser_search":
                    tool_args["task_id"] = task_id
                result = tool_def["function"](**tool_args)
                print(f"│  [工具结果] {tool_name} 返回内容 ({len(result)} 字符):")
                for line in result[:500].split("\n"):
                    print(f"│    {line}")
                if len(result) > 500:
                    print(f"│    ... (已截断，共 {len(result)} 字符)")
                if tool_name == "browser_search":
                    vf = get_last_browser_video()
                    if vf:
                        video_url = f"/static/videos/{vf}"
                        print(f"│  [视频录制] {video_url}")
            else:
                print(f"│  [工具调用] 未找到工具: {tool_name}")
        else:
            print(f"│  [工具调用] 无需工具，由大模型直接处理")

        task_results[task_id] = {
            "description": task["description"],
            "tool": tool_name,
            "args": tool_args,
            "tool_result": result,
            "thought": thought,
            "video_url": video_url,
        }

        yield sse_event("task_done", {"id": task_id, "video_url": video_url})
        print(f"└─ 子任务 [{task_id}] 完成 ✓")

    # ---- 阶段 4: Reasoner 根据工具结果生成回复草稿 ----
    yield sse_event("status", {"phase": "answering"})

    reasoner_client, reasoner_model = get_client("default")

    context_parts = [f"用户问题: {user_message}\n"]
    for tid, tr in task_results.items():
        context_parts.append(f"## 子任务{tid}: {tr['description']}")
        if tr["tool"] != "none" and tr["tool_result"]:
            context_parts.append(f"以下是通过搜索工具 {tr['tool']} 获取到的实时信息:\n{tr['tool_result']}")
        else:
            context_parts.append("（此任务无需搜索，由你直接完成）")
        context_parts.append("")
    context_parts.append(
        f"请根据以上搜索结果和信息，针对用户的原始问题进行回答。"
        f"要求：{plan.get('final_answer', '回复用户')}。"
        f"回答要有条理、信息准确，优先使用搜索结果中的事实内容。"
    )

    reasoner_input = "\n".join(context_parts)

    # ===== 关键日志：Reasoner 的完整输入（含 Executor 工具结果） =====
    print(f"\n{'='*60}")
    print(f"[Reasoner 输入] 以下是传给最终答案生成模型的完整内容:")
    print(f"{'='*60}")
    print(reasoner_input)
    print(f"{'='*60}\n")

    messages = [{"role": "user", "content": reasoner_input}]
    response = reasoner_client.chat.completions.create(model=reasoner_model, messages=messages)

    reasoning = response.choices[0].message.reasoning_content or ""
    draft_content = response.choices[0].message.content or ""

    # ---- 阶段 5: Verify 校验并优化回复 ----
    yield sse_event("status", {"phase": "verifying"})

    verify_client, verify_model = get_client("verify")

    verify_input_parts = [
        f"## 用户原始问题\n{user_message}\n",
        f"## 搜索工具获取的原始资料\n",
    ]
    for tid, tr in task_results.items():
        if tr["tool"] != "none" and tr["tool_result"]:
            verify_input_parts.append(f"### 子任务{tid} ({tr['tool']}): {tr['description']}\n{tr['tool_result']}\n")
    verify_input_parts.append(f"## 大模型生成的回复草稿\n{draft_content}")

    verify_input = "\n".join(verify_input_parts)

    verify_messages = [
        {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
        {"role": "user", "content": verify_input},
    ]
    verify_response = verify_client.chat.completions.create(model=verify_model, messages=verify_messages)
    final_content = verify_response.choices[0].message.content or draft_content

    # ===== 关键日志：Verify 输出 =====
    print(f"\n{'='*60}")
    print(f"[Verify 输出] 校验优化后的最终回复:")
    print(f"{'='*60}")
    print(final_content)
    print(f"{'='*60}\n")

    execution_log = []
    all_video_urls = []
    for tid, tr in task_results.items():
        log_entry = {
            "id": tid,
            "description": tr["description"],
            "tool": tr["tool"],
            "args": tr["args"],
            "has_result": bool(tr["tool_result"]),
            "result_preview": tr["tool_result"][:200] if tr["tool_result"] else "",
            "thought": tr["thought"],
            "video_url": tr.get("video_url", ""),
        }
        execution_log.append(log_entry)
        if tr.get("video_url"):
            all_video_urls.append({
                "task_id": tid,
                "description": tr["description"],
                "url": tr["video_url"],
            })

    yield sse_event("answer", {
        "reply": final_content,
        "reasoning": reasoning,
        "execution_log": execution_log,
        "sandbox_videos": all_video_urls,
        "time": now,
    })

    yield sse_event("done", {})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        chat_stream(req.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health():
    cfg = load_config()
    return {
        "status": "ok",
        "reasoner_model": cfg["deepseek"].get("model", "deepseek-reasoner"),
        "planner_model": cfg.get("planner", {}).get("model", "deepseek-chat"),
        "executor_model": cfg.get("executor", {}).get("model", "deepseek-chat"),
        "verify_model": cfg.get("verify", {}).get("model", "deepseek-chat"),
    }
