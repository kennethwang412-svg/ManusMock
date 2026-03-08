# OpenManus (ManusMock)

An open-source multi-agent orchestration platform inspired by [Manus AI](https://manus.im), featuring task planning, automated execution, real-time browser recording, and intelligent Q&A.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135+-green?logo=fastapi)
![Vue](https://img.shields.io/badge/Vue.js-3-brightgreen?logo=vue.js)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

### Multi-Agent Pipeline

```
User Query → Planner → Executor → Reasoner → Verify → Final Answer
```

| Agent | Model | Role |
|-------|-------|------|
| **Planner** | DeepSeek Chat | Decomposes user queries into executable subtasks |
| **Executor** | DeepSeek Chat | Analyzes each subtask, selects tools and parameters |
| **Reasoner** | DeepSeek Reasoner | Synthesizes all execution results into a comprehensive answer with reasoning |
| **Verify** | DeepSeek Chat | Validates and refines the final answer for accuracy and completeness |

### Integrated Search Tools

- **Tavily Search** — AI-optimized search engine
- **Serper** — Google Search API
- **Baidu Qianfan** — Chinese search optimization

### Browser Automation & Live Recording

Powered by Playwright for real browser interactions:
- Automatically opens a browser to perform searches
- Clicks into search result pages to extract content
- Records the entire browsing session as video for frontend playback
- Browser window stays on top for live demonstration (Windows)

### Frontend UI

- Chat interface with full Markdown rendering (headings, lists, tables, code blocks, etc.)
- Left sidebar with real-time task status tracking (Pending → Running → Completed)
- Right panel for viewing and copying extracted code files
- **"OpenManus Computer"** sandbox panel — grouped browser recording playback organized by conversation round
- Light / Dark theme toggle
- Server-Sent Events (SSE) for real-time streaming responses

## Project Structure

```
ManusMock/
├── frontend/
│   ├── index.html          # Main page (Vue 3 via CDN)
│   ├── app.js              # Vue application logic
│   └── style.css           # Styles with CSS theme variables
├── backend/
│   ├── main.py             # FastAPI entry point & agent orchestration
│   ├── tools.py            # Search tool implementations
│   ├── browser_tools.py    # Playwright browser automation & video recording
│   ├── prompts.py          # System prompts for each agent
│   ├── config.yaml         # API key configuration (not in version control)
│   └── requirements.txt    # Python dependencies
├── .gitignore
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10+
- A modern browser (Chrome / Edge / Firefox)

### 1. Clone the Repository

```bash
git clone https://github.com/kennethwang412-svg/ManusMock.git
cd ManusMock
```

### 2. Set Up the Backend

```bash
cd backend

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 3. Configure API Keys

Create a `config.yaml` file in the `backend/` directory:

```yaml
deepseek:
  api_key: "your-deepseek-api-key"
  base_url: "https://api.deepseek.com"
  model: "deepseek-reasoner"

planner:
  model: "deepseek-chat"

executor:
  model: "deepseek-chat"

verify:
  model: "deepseek-chat"

tools:
  tavily:
    api_key: "your-tavily-api-key"
  serper:
    api_key: "your-serper-api-key"
  baidu:
    api_key: "your-baidu-qianfan-api-key"
```

> You need at least a DeepSeek API key and one search tool API key to get started.

### 4. Start the Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

### 5. Start the Frontend

```bash
cd frontend
python -m http.server 8080
```

Open your browser and navigate to http://localhost:8080

## How It Works

1. Type a question in the input box and hit Send
2. **Planning phase** — The Planner decomposes your query into subtasks; the left sidebar updates in real time
3. **Execution phase** — The Executor runs each subtask, calling search tools and the browser
4. Browser actions are recorded and can be replayed in the **"OpenManus Computer"** panel on the right
5. Once execution completes, the Reasoner synthesizes results and the Verify agent refines the answer
6. The final answer appears in the chat area; click the reasoning block to expand the full execution trace

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vue 3 (Composition API, CDN) |
| Backend | FastAPI + Uvicorn |
| AI Models | DeepSeek Reasoner / Chat |
| Search Engines | Tavily, Serper, Baidu Qianfan |
| Browser Automation | Playwright (Chromium) |
| Real-time Communication | Server-Sent Events (SSE) |

## Getting API Keys

| Service | URL |
|---------|-----|
| DeepSeek | https://platform.deepseek.com |
| Tavily | https://tavily.com |
| Serper | https://serper.dev |
| Baidu Qianfan | https://cloud.baidu.com/product/wenxinworkshop |

## License

MIT
