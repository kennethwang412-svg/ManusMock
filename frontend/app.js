const { createApp, ref, computed, nextTick, onMounted } = Vue;

const CODE_FILE_EXTENSIONS = {
  python: '.py', py: '.py',
  javascript: '.js', js: '.js',
  typescript: '.ts', ts: '.ts',
  jsx: '.jsx', tsx: '.tsx',
  json: '.json',
  html: '.html', css: '.css',
  java: '.java', kotlin: '.kt',
  go: '.go', rust: '.rs',
  sql: '.sql', yaml: '.yaml', yml: '.yml',
  xml: '.xml', shell: '.sh', bash: '.sh',
  c: '.c', cpp: '.cpp', 'c++': '.cpp',
  ruby: '.rb', php: '.php', swift: '.swift',
  dart: '.dart', lua: '.lua', r: '.r',
  toml: '.toml', ini: '.ini', dockerfile: '',
  makefile: '', vue: '.vue', svelte: '.svelte',
};

function extractCodeFiles(text) {
  if (!text) return [];
  const regex = /```(\w+)?\s*\n([\s\S]*?)```/g;
  const files = [];
  let match;
  let counter = 1;

  while ((match = regex.exec(text)) !== null) {
    const lang = (match[1] || '').toLowerCase();
    const code = match[2].trim();
    if (code.length < 30) continue;

    const ext = CODE_FILE_EXTENSIONS[lang];
    if (ext === undefined) continue;

    let filename = '';
    const firstLine = code.split('\n')[0];
    const commentMatch = firstLine.match(/^(?:#|\/\/|\/\*)\s*(?:file(?:name)?[:：]?\s*)?(\S+\.\w+)/i);
    if (commentMatch) {
      filename = commentMatch[1];
    } else {
      filename = `code_${counter}${ext || '.txt'}`;
    }

    files.push({
      name: filename,
      lang: lang || 'text',
      size: `${(new TextEncoder().encode(code).length / 1024).toFixed(1)} KB`,
      content: code,
    });
    counter++;
  }
  return files;
}

const LANG_ICONS = {
  py: 'Python', python: 'Python',
  js: 'JavaScript', javascript: 'JavaScript',
  ts: 'TypeScript', typescript: 'TypeScript',
  jsx: 'React', tsx: 'React',
  json: 'JSON', html: 'HTML', css: 'CSS',
  java: 'Java', go: 'Go', rust: 'Rust',
  sql: 'SQL', yaml: 'YAML', yml: 'YAML',
  vue: 'Vue', svelte: 'Svelte',
};

createApp({
  setup() {
    const inputText = ref('');
    const inputRef = ref(null);
    const messagesContainer = ref(null);
    const isTyping = ref(false);
    const sidebarCollapsed = ref(false);
    const filePanelOpen = ref(false);
    const activeFile = ref(null);
    const showSteps = ref(true);
    const copySuccess = ref(false);

    const sandboxOpen = ref(false);
    const pendingVideos = ref([]);
    const currentRound = ref(0);
    const currentQuestion = ref('');
    const activeSandboxIndex = ref(0);
    const roundCollapseState = ref({});

    const sandboxVideos = computed(() => {
      if (!currentTask.value) return [];
      const allVideos = [];
      for (const msg of currentTask.value.messages) {
        if (msg.role === 'assistant' && msg.sandboxVideos?.length) {
          allVideos.push(...msg.sandboxVideos);
        }
      }
      if (pendingVideos.value.length) {
        allVideos.push(...pendingVideos.value);
      }
      return allVideos;
    });

    const videoGroups = computed(() => {
      const vids = sandboxVideos.value;
      if (!vids.length) return [];
      const groupMap = {};
      const order = [];
      for (const v of vids) {
        const r = v.round || 0;
        if (!groupMap[r]) {
          groupMap[r] = { round: r, question: v.question || '', videos: [] };
          order.push(r);
        }
        groupMap[r].videos.push(v);
      }
      return order.map(r => groupMap[r]);
    });

    const hasMultipleRounds = computed(() => videoGroups.value.length > 1);

    function isRoundExpanded(round) {
      if (roundCollapseState.value[round] !== undefined) {
        return roundCollapseState.value[round];
      }
      const groups = videoGroups.value;
      if (!groups.length) return true;
      return groups[groups.length - 1].round === round;
    }

    function toggleRoundCollapse(round) {
      const current = isRoundExpanded(round);
      roundCollapseState.value = { ...roundCollapseState.value, [round]: !current };
    }

    const isDark = ref(false);

    function toggleTheme() {
      isDark.value = !isDark.value;
      document.documentElement.dataset.theme = isDark.value ? 'dark' : '';
    }

    const tasks = ref([]);
    const currentTask = ref(null);

    const currentMessages = computed(() => {
      if (!currentTask.value) return [];
      return currentTask.value.messages || [];
    });

    let messageIdCounter = 1000;

    function getNow() {
      const d = new Date();
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    function scrollToBottom() {
      nextTick(() => {
        const container = messagesContainer.value;
        if (container) {
          container.scrollTop = container.scrollHeight;
        }
      });
    }

    function formatMessage(text) {
      if (!text) return '';

      const codeBlocks = [];
      let processed = text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
        const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
        const escaped = code.trim()
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
        codeBlocks.push(`<pre class="code-block"><code class="lang-${lang}">${escaped}</code></pre>`);
        return placeholder;
      });

      processed = processed
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      const lines = processed.split('\n');
      const result = [];
      let i = 0;
      let olCounter = 0;

      function isOlLine(ln) { return ln && ln.match(/^\s*\d+\.\s+/); }
      function isUlLine(ln) { return ln && ln.match(/^\s*[-*]\s+/); }
      function peekNextNonEmpty(from) {
        for (let j = from; j < lines.length; j++) {
          if (lines[j].trim() !== '') return lines[j];
        }
        return null;
      }

      while (i < lines.length) {
        const line = lines[i];

        if (line.match(/^__CODE_BLOCK_\d+__$/)) {
          const idx = parseInt(line.match(/\d+/)[0]);
          result.push(codeBlocks[idx]);
          i++;
          continue;
        }

        if (line.trim().match(/^\|(.+\|)+\s*$/) && lines[i + 1] && lines[i + 1].trim().match(/^\|[\s\-:|]+\|$/)) {
          let tableHtml = '<table class="md-table">';
          const headers = line.trim().split('|').filter(c => c.trim() !== '');
          tableHtml += '<thead><tr>';
          for (const h of headers) tableHtml += `<th>${h.trim()}</th>`;
          tableHtml += '</tr></thead><tbody>';
          i += 2;
          while (i < lines.length && lines[i].trim().match(/^\|(.+\|)+\s*$/)) {
            const cells = lines[i].trim().split('|').filter(c => c.trim() !== '');
            tableHtml += '<tr>';
            for (const c of cells) tableHtml += `<td>${c.trim()}</td>`;
            tableHtml += '</tr>';
            i++;
          }
          tableHtml += '</tbody></table>';
          result.push(tableHtml);
          continue;
        }

        if (line.match(/^#{1,6}\s+/) || line.match(/^#{1,6}[^\s#]/)) {
          const m = line.match(/^(#{1,6})\s*/);
          const level = Math.min(m[1].length, 6);
          const content = line.replace(/^#{1,6}\s*/, '');
          const displayLevel = Math.min(level, 3);
          result.push(`<h${displayLevel} class="md-heading md-h${displayLevel}">${content}</h${displayLevel}>`);
          i++;
          continue;
        }

        if (line.trim() === '---' || line.trim() === '***' || line.trim() === '___') {
          result.push('<hr class="md-hr">');
          i++;
          continue;
        }

        if (isOlLine(line)) {
          let listHtml = '<ol class="md-list">';
          while (i < lines.length) {
            if (isOlLine(lines[i])) {
              const item = lines[i].replace(/^\s*\d+\.\s+/, '');
              let liContent = item;
              i++;
              let subUl = '';
              while (i < lines.length && !isOlLine(lines[i]) && !lines[i].match(/^#{1,6}[\s]/)) {
                if (isUlLine(lines[i])) {
                  subUl += '<ul class="md-list md-sublist">';
                  while (i < lines.length && isUlLine(lines[i])) {
                    const subItem = lines[i].replace(/^\s*[-*]\s+/, '');
                    subUl += `<li>${subItem}</li>`;
                    i++;
                  }
                  subUl += '</ul>';
                } else if (lines[i].trim() === '') {
                  const next = peekNextNonEmpty(i);
                  if (isOlLine(next) || isUlLine(next)) {
                    i++;
                  } else {
                    break;
                  }
                } else {
                  liContent += '<br>' + lines[i];
                  i++;
                }
              }
              listHtml += `<li>${liContent}${subUl}</li>`;
            } else {
              break;
            }
          }
          listHtml += '</ol>';
          result.push(listHtml);
          continue;
        }

        if (isUlLine(line)) {
          let listHtml = '<ul class="md-list">';
          while (i < lines.length) {
            if (isUlLine(lines[i])) {
              const item = lines[i].replace(/^\s*[-*]\s+/, '');
              let liContent = item;
              i++;
              while (i < lines.length && !isUlLine(lines[i]) && lines[i].trim() !== '' && !lines[i].match(/^#{1,6}[\s]/) && !isOlLine(lines[i])) {
                liContent += '<br>' + lines[i];
                i++;
              }
              listHtml += `<li>${liContent}</li>`;
              while (i < lines.length && lines[i].trim() === '') {
                const next = peekNextNonEmpty(i);
                if (isUlLine(next)) { i++; } else { break; }
              }
            } else {
              break;
            }
          }
          listHtml += '</ul>';
          result.push(listHtml);
          continue;
        }

        if (line.trim() === '') {
          const prev = result[result.length - 1] || '';
          const isAfterBlock = prev.startsWith('<h') || prev.startsWith('<ul') || prev.startsWith('<ol') || prev.startsWith('<table') || prev.startsWith('<hr') || prev.startsWith('<pre');
          if (!isAfterBlock) {
            result.push('<div class="md-spacer"></div>');
          }
          i++;
          while (i < lines.length && lines[i].trim() === '') i++;
          continue;
        }

        result.push(line);
        i++;
      }

      let html = result.join('\n');
      html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>');
      html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
      html = html.replace(/`(.+?)`/g, '<code class="inline-code">$1</code>');
      html = html.replace(/\n/g, '');
      return html;
    }

    const API_BASE = 'http://localhost:8000';
    const statusPhase = ref('');
    const todoList = ref([]);

    async function sendMessage() {
      const text = inputText.value.trim();
      if (!text || isTyping.value) return;

      if (!currentTask.value) {
        createNewTask();
      }

      const userMsg = {
        id: ++messageIdCounter,
        role: 'user',
        content: text,
        time: getNow(),
      };
      currentTask.value.messages.push(userMsg);
      inputText.value = '';

      autoResizeTextarea();
      scrollToBottom();
      await callBackend(text);
    }

    function sendQuickMessage(text) {
      inputText.value = text;
      sendMessage();
    }

    async function callBackend(userText) {
      isTyping.value = true;
      statusPhase.value = 'planning';
      todoList.value = [];
      pendingVideos.value = [];
      currentRound.value++;
      currentQuestion.value = userText;
      activeSandboxIndex.value = sandboxVideos.value.length;
      roundCollapseState.value = {};
      if (currentTask.value) {
        currentTask.value.status = 'running';
      }
      scrollToBottom();

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: userText }),
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ') && eventType) {
              const data = JSON.parse(line.slice(6));
              handleSSE(eventType, data);
              eventType = '';
            }
          }
        }
      } catch (err) {
        const errorMsg = {
          id: ++messageIdCounter,
          role: 'assistant',
          content: `**连接后端失败：** ${err.message}\n\n请确认后端服务已启动（端口 8000）。`,
          time: getNow(),
          files: [],
          executionLog: [],
        };
        currentTask.value.messages.push(errorMsg);
      } finally {
        isTyping.value = false;
        statusPhase.value = '';
        scrollToBottom();
      }
    }

    function handleSSE(event, data) {
      switch (event) {
        case 'status':
          statusPhase.value = data.phase;
          scrollToBottom();
          break;

        case 'plan':
          statusPhase.value = 'planned';
          todoList.value = data.tasks.map(t => ({
            id: t.id,
            description: t.description,
            status: 'pending',
          }));
          if (currentTask.value) {
            currentTask.value.title = data.goal || currentTask.value.title;
          }
          scrollToBottom();
          break;

        case 'task_start': {
          const todo = todoList.value.find(t => t.id === data.id);
          if (todo) todo.status = 'running';
          scrollToBottom();
          break;
        }

        case 'task_done': {
          const todo = todoList.value.find(t => t.id === data.id);
          if (todo) todo.status = 'done';
          if (data.video_url) {
            pendingVideos.value.push({
              task_id: data.id,
              description: todo ? todo.description : `子任务 ${data.id}`,
              url: `http://localhost:8000${data.video_url}`,
              round: currentRound.value,
              question: currentQuestion.value,
            });
            activeSandboxIndex.value = sandboxVideos.value.length - 1;
            sandboxOpen.value = true;
          }
          scrollToBottom();
          break;
        }

        case 'answer': {
          statusPhase.value = '';
          const codeFiles = extractCodeFiles(data.reply);
          const roundVideos = pendingVideos.value.length
            ? [...pendingVideos.value]
            : (data.sandbox_videos || []).map(v => ({
                ...v,
                url: `http://localhost:8000${v.url}`,
                round: currentRound.value,
                question: currentQuestion.value,
              }));
          const assistantMsg = {
            id: ++messageIdCounter,
            role: 'assistant',
            content: data.reply,
            reasoning: data.reasoning || '',
            reasoningExpanded: false,
            executionLog: data.execution_log || [],
            executionLogExpanded: false,
            sandboxVideos: roundVideos,
            time: data.time,
            files: codeFiles,
          };
          pendingVideos.value = [];
          currentTask.value.messages.push(assistantMsg);
          if (currentTask.value) {
            currentTask.value.status = 'completed';
          }
          if (roundVideos.length) {
            activeSandboxIndex.value = sandboxVideos.value.length - 1;
          }
          scrollToBottom();
          break;
        }

        case 'done':
          break;
      }
    }

    function handleEnter(e) {
      if (!e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    }

    function autoResizeTextarea() {
      nextTick(() => {
        const el = inputRef.value;
        if (el) {
          el.style.height = 'auto';
          el.style.height = Math.min(el.scrollHeight, 120) + 'px';
        }
      });
    }

    function createNewTask() {
      const newTask = {
        id: Date.now(),
        title: '新任务',
        time: '刚刚',
        status: 'pending',
        steps: [],
        messages: [],
      };
      tasks.value.unshift(newTask);
      currentTask.value = newTask;
    }

    function switchTask(task) {
      currentTask.value = task;
      activeSandboxIndex.value = 0;
      roundCollapseState.value = {};
      scrollToBottom();
    }

    function statusText(status) {
      const map = {
        completed: '已完成',
        running: '进行中',
        pending: '待处理',
      };
      return map[status] || status;
    }

    function toggleSteps() {
      showSteps.value = !showSteps.value;
    }

    function openFilePanel(file) {
      activeFile.value = file;
      filePanelOpen.value = true;
      copySuccess.value = false;
    }

    function closeFilePanel() {
      filePanelOpen.value = false;
    }

    function toggleReasoning(msg) {
      msg.reasoningExpanded = !msg.reasoningExpanded;
    }

    function toggleExecutionLog(msg) {
      msg.executionLogExpanded = !msg.executionLogExpanded;
    }

    function getToolLabel(toolName) {
      const map = {
        tavily_search: 'Tavily',
        serper_search: 'Serper',
        baidu_search: '百度',
        browser_search: '浏览器搜索',
        none: '直接推理',
      };
      return map[toolName] || toolName;
    }

    function toggleSandbox() {
      sandboxOpen.value = !sandboxOpen.value;
    }

    function closeSandbox() {
      sandboxOpen.value = false;
    }

    function switchSandboxVideo(index) {
      activeSandboxIndex.value = index;
    }

    const activeSandboxVideo = computed(() => {
      const vids = sandboxVideos.value;
      if (!vids.length) return null;
      return vids[activeSandboxIndex.value] || vids[vids.length - 1];
    });

    function getLangLabel(lang) {
      return LANG_ICONS[lang] || lang.toUpperCase();
    }

    async function copyFileContent() {
      if (!activeFile.value) return;
      try {
        await navigator.clipboard.writeText(activeFile.value.content);
        copySuccess.value = true;
        setTimeout(() => { copySuccess.value = false; }, 2000);
      } catch {
        const ta = document.createElement('textarea');
        ta.value = activeFile.value.content;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        copySuccess.value = true;
        setTimeout(() => { copySuccess.value = false; }, 2000);
      }
    }

    onMounted(() => {
      scrollToBottom();
      const textarea = inputRef.value;
      if (textarea) {
        textarea.addEventListener('input', autoResizeTextarea);
      }
    });

    return {
      inputText,
      inputRef,
      messagesContainer,
      isTyping,
      sidebarCollapsed,
      filePanelOpen,
      activeFile,
      showSteps,
      copySuccess,
      isDark,
      toggleTheme,
      sandboxOpen,
      sandboxVideos,
      activeSandboxIndex,
      activeSandboxVideo,
      videoGroups,
      hasMultipleRounds,
      isRoundExpanded,
      toggleRoundCollapse,
      tasks,
      currentTask,
      currentMessages,
      statusPhase,
      todoList,
      sendMessage,
      sendQuickMessage,
      handleEnter,
      createNewTask,
      switchTask,
      statusText,
      toggleSteps,
      openFilePanel,
      closeFilePanel,
      formatMessage,
      toggleReasoning,
      toggleExecutionLog,
      getToolLabel,
      getLangLabel,
      copyFileContent,
      toggleSandbox,
      closeSandbox,
      switchSandboxVideo,
    };
  },
}).mount('#app');
