/**
 * Hattz Empire - Chat UI JavaScript
 */

const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const projectSelect = document.getElementById('project-select');
const currentAgentDisplay = document.getElementById('current-agent');
const clearBtn = document.getElementById('clear-btn');
const exportBtn = document.getElementById('export-btn');
const newChatBtn = document.getElementById('new-chat-btn');
const sessionItems = document.getElementById('session-items');

// Fixed agent - PM only (PM이 모든 대화의 중심)
const currentAgent = 'pm';

// Current project context
let currentProject = null;
let projectFiles = [];
let currentSessionId = localStorage.getItem('hattz_session_id') || null;
let sessions = [];

// Load projects from API
async function loadProjects() {
    try {
        const response = await fetch('/api/projects');
        const projects = await response.json();

        projectSelect.innerHTML = '<option value="">-- 프로젝트 선택 --</option>';
        projects.forEach(project => {
            const option = document.createElement('option');
            option.value = project.id;
            option.textContent = `${project.name}`;
            option.title = project.description;
            projectSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load projects:', error);
    }
}

// Load project files
async function loadProjectFiles(projectId) {
    if (!projectId) {
        currentProject = null;
        projectFiles = [];
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/files`);
        const data = await response.json();
        currentProject = projectId;
        projectFiles = data.files || [];
        console.log(`Loaded ${projectFiles.length} files from ${projectId}`);
    } catch (error) {
        console.error('Failed to load project files:', error);
    }
}

// Send message
async function sendMessage() {
    let message = messageInput.value.trim();
    if (!message) return;

    const agent = currentAgent;

    // 코드 리뷰 요청 시 프로젝트 컨텍스트 추가
    if (message.includes('코드 리뷰') || message.includes('코드리뷰') || message.includes('code review')) {
        if (currentProject && projectFiles.length > 0) {
            const fileList = projectFiles.slice(0, 20).map(f => f.relative).join('\n- ');
            message = `[프로젝트: ${currentProject}]\n[파일 목록 (${projectFiles.length}개 중 상위 20개)]:\n- ${fileList}\n\n${message}`;
        } else if (!currentProject) {
            message = `⚠️ 프로젝트가 선택되지 않았습니다. 사이드바에서 프로젝트를 먼저 선택해주세요.\n\n${message}`;
        }
    }

    // Clear welcome message if exists
    const welcome = chatMessages.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    // Add user message
    appendMessage('user', messageInput.value.trim(), agent);
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Show loading
    const loadingId = showLoading();

    // Set status to loading
    setStatus('Thinking...', true);

    try {
        // Use streaming endpoint
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, agent })
        });

        // Remove loading indicator
        removeLoading(loadingId);

        // Handle streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let assistantMessage = null;
        let fullContent = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.done) {
                            // Streaming complete
                            break;
                        }

                        if (data.token) {
                            fullContent += data.token;

                            if (!assistantMessage) {
                                assistantMessage = appendMessage('assistant', fullContent, agent, true);
                            } else {
                                updateMessageContent(assistantMessage, fullContent);
                            }
                        }
                    } catch (e) {
                        // Skip invalid JSON
                    }
                }
            }
        }

        setStatus('Ready', false);

        // Reload sessions to update list (name may have changed)
        loadSessions();

    } catch (error) {
        console.error('Error:', error);
        removeLoading(loadingId);
        appendMessage('assistant', `Error: ${error.message}`, agent);
        setStatus('Error', false);
    }
}

// Append message to chat
function appendMessage(role, content, agent, isStreaming = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const time = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });

    messageDiv.innerHTML = `
        <div class="message-header">
            ${role === 'assistant' ? `<span class="agent-badge">${agent}</span>` : ''}
            <span>${time}</span>
        </div>
        <div class="message-content">${formatContent(content)}</div>
    `;

    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return messageDiv;
}

// Update message content (for streaming)
function updateMessageContent(messageDiv, content) {
    const contentDiv = messageDiv.querySelector('.message-content');
    contentDiv.innerHTML = formatContent(content);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Format content (handle code blocks, YAML, etc.)
function formatContent(content) {
    // Handle code blocks
    content = content.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang}">${escapeHtml(code)}</code></pre>`;
    });

    // Handle inline code
    content = content.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Handle bold
    content = content.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Handle newlines
    content = content.replace(/\n/g, '<br>');

    return content;
}

// Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Show loading indicator
function showLoading() {
    const id = 'loading-' + Date.now();
    const loadingDiv = document.createElement('div');
    loadingDiv.id = id;
    loadingDiv.className = 'message assistant';
    loadingDiv.innerHTML = `
        <div class="message-header">
            <span class="agent-badge">${currentAgent}</span>
        </div>
        <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
        </div>
    `;
    chatMessages.appendChild(loadingDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
}

// Remove loading indicator
function removeLoading(id) {
    const loading = document.getElementById(id);
    if (loading) loading.remove();
}

// Set status
function setStatus(text, loading) {
    const statusText = document.getElementById('status-text');
    const dot = document.querySelector('.status-dot');
    const processingBar = document.getElementById('processing-bar');
    const processingText = processingBar?.querySelector('.processing-text');

    // Update status text
    if (statusText) {
        statusText.textContent = text;
    }

    // Update status dot
    if (dot) {
        dot.classList.toggle('loading', loading);
    }

    // Show/hide processing bar
    if (processingBar) {
        if (loading) {
            processingBar.classList.remove('hidden');
            if (processingText) {
                processingText.textContent = text === 'Thinking...' ? 'PM이 생각 중...' : text;
            }
        } else {
            processingBar.classList.add('hidden');
        }
    }
}

// Clear chat
function clearChat() {
    chatMessages.innerHTML = `
        <div class="welcome-message">
            <h2>Hattz Empire AI Team</h2>
            <p>비판적 스탠스로 무장한 AI 팀에게 질문하세요.</p>
            <div class="quick-actions">
                <button class="quick-btn" data-msg="새로운 기능 추가하고 싶어">💡 새 기능 요청</button>
                <button class="quick-btn" data-action="code-review" data-msg="">🔍 코드 리뷰</button>
                <button class="quick-btn" data-action="strategy" data-msg="">📊 전략 분석</button>
                <button class="quick-btn" data-action="ai-team" data-msg="Hattz AI팀 시스템을 개선하고 싶어">🔧 AI팀 수정</button>
                <button class="quick-btn" data-action="web-research" data-msg="외부 데이터를 검색해서 분석해줘">🌐 외부 검색</button>
            </div>
        </div>
    `;

    // Re-attach quick button listeners
    attachQuickButtonListeners();

    // Clear server history
    fetch('/api/history/clear', { method: 'POST' });
}

// Export chat
function exportChat() {
    fetch('/api/history')
        .then(r => r.json())
        .then(history => {
            const content = history.map(msg =>
                `[${msg.timestamp}] ${msg.role.toUpperCase()} (${msg.agent}):\n${msg.content}\n`
            ).join('\n---\n\n');

            const blob = new Blob([content], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `hattz-chat-${new Date().toISOString().slice(0, 10)}.txt`;
            a.click();
        });
}

// Attach quick button listeners
function attachQuickButtonListeners() {
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const action = btn.dataset.action;

            // 특수 액션 처리
            if (action === 'ai-team') {
                // AI팀 수정: hattz_empire 프로젝트 자동 선택
                currentProject = 'hattz_empire';
                projectSelect.value = 'hattz_empire';
                messageInput.value = btn.dataset.msg;
                sendMessage();
            } else if (action === 'code-review') {
                // 코드 리뷰: 특수 프롬프트
                messageInput.value = "코드 리뷰 및 수정이 필요해!";
                sendMessage();
            } else if (action === 'strategy') {
                // 전략 분석: 특수 프롬프트
                messageInput.value = "최고의 전략을 짤 준비가 되셧나요? 책사여!! 세상을 평정해보자!!";
                sendMessage();
            } else if (action === 'web-research') {
                // 외부 데이터 검색
                messageInput.value = btn.dataset.msg;
                sendMessage();
            } else {
                // 기본 동작
                messageInput.value = btn.dataset.msg;
                sendMessage();
            }
        });
    });
}

// Auto-resize textarea
function autoResize() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
}

// Event listeners
sendBtn.addEventListener('click', sendMessage);

messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

messageInput.addEventListener('input', autoResize);

projectSelect.addEventListener('change', () => {
    loadProjectFiles(projectSelect.value);
});

clearBtn.addEventListener('click', clearChat);
exportBtn.addEventListener('click', exportChat);

// Check all APIs and show overall status
async function checkAllApis() {
    const btn = document.getElementById('check-all-btn');
    const overallEl = document.getElementById('health-overall');

    btn.classList.add('loading');
    overallEl.textContent = '🔄';
    overallEl.title = '체크 중...';

    const providers = ['anthropic', 'openai', 'google'];
    const results = [];

    for (const provider of providers) {
        try {
            const response = await fetch(`/api/health/${provider}`);
            const data = await response.json();
            results.push({ provider, ok: data.status === 'ok', message: data.message });
        } catch (error) {
            results.push({ provider, ok: false, message: error.message });
        }
    }

    btn.classList.remove('loading');

    const allOk = results.every(r => r.ok);
    const failedCount = results.filter(r => !r.ok).length;

    if (allOk) {
        overallEl.textContent = '✅';
        overallEl.title = '모든 API 정상';
    } else {
        overallEl.textContent = '❌';
        const failed = results.filter(r => !r.ok).map(r => r.provider).join(', ');
        overallEl.title = `실패: ${failed}`;
    }
}

// =============================================================================
// Session Management
// =============================================================================

// Load sessions from API
async function loadSessions() {
    console.log('[DEBUG] loadSessions() called');
    try {
        const response = await fetch('/api/sessions');
        console.log('[DEBUG] /api/sessions response status:', response.status);
        sessions = await response.json();
        console.log('[DEBUG] Sessions loaded:', sessions.length, 'sessions');
        console.log('[DEBUG] Sessions data:', sessions);
        renderSessionList();
    } catch (error) {
        console.error('[DEBUG] Failed to load sessions:', error);
    }
}

// Render session list
function renderSessionList() {
    console.log('[DEBUG] renderSessionList() called');
    console.log('[DEBUG] sessionItems element:', sessionItems);

    if (!sessionItems) {
        console.error('[DEBUG] sessionItems element NOT FOUND!');
        return;
    }

    sessionItems.innerHTML = '';

    if (sessions.length === 0) {
        console.log('[DEBUG] No sessions to render');
        sessionItems.innerHTML = '<div class="no-sessions">No chat history</div>';
        return;
    }

    console.log('[DEBUG] Rendering', sessions.length, 'sessions');
    sessions.forEach(session => {
        const item = document.createElement('div');
        item.className = `session-item${session.id === currentSessionId ? ' active' : ''}`;
        item.dataset.sessionId = session.id;

        const name = session.name || 'New Chat';
        const date = new Date(session.updated_at).toLocaleDateString('ko-KR', {
            month: 'short',
            day: 'numeric'
        });

        item.innerHTML = `
            <div class="session-name">${escapeHtml(name)}</div>
            <div class="session-meta">
                <span class="session-agent">${session.agent}</span>
                <span>${date}</span>
            </div>
            <button class="delete-btn" title="Delete">×</button>
        `;

        // Click to switch session
        item.addEventListener('click', (e) => {
            if (!e.target.classList.contains('delete-btn')) {
                switchSession(session.id);
            }
        });

        // Delete button
        item.querySelector('.delete-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            deleteSession(session.id);
        });

        sessionItems.appendChild(item);
    });
}

// Switch to a session
async function switchSession(sessionId) {
    try {
        const response = await fetch(`/api/sessions/${sessionId}/switch`, {
            method: 'POST'
        });
        const data = await response.json();

        currentSessionId = sessionId;
        localStorage.setItem('hattz_session_id', sessionId);

        // Update UI
        renderSessionList();

        // Clear and load messages
        chatMessages.innerHTML = '';

        if (data.messages && data.messages.length > 0) {
            data.messages.forEach(msg => {
                appendMessage(msg.role, msg.content, msg.agent || data.session.agent);
            });
        } else {
            showWelcomeMessage();
        }

    } catch (error) {
        console.error('Failed to switch session:', error);
    }
}

// Create new session
async function createNewSession() {
    try {
        const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent: currentAgent,
                project: currentProject
            })
        });
        const data = await response.json();

        currentSessionId = data.session_id;
        localStorage.setItem('hattz_session_id', data.session_id);

        // Clear chat and show welcome
        chatMessages.innerHTML = '';
        showWelcomeMessage();

        // Reload session list
        await loadSessions();

    } catch (error) {
        console.error('Failed to create session:', error);
    }
}

// Delete session
async function deleteSession(sessionId) {
    if (!confirm('이 대화를 삭제하시겠습니까?')) return;

    try {
        await fetch(`/api/sessions/${sessionId}`, {
            method: 'DELETE'
        });

        // If deleted current session, clear it
        if (sessionId === currentSessionId) {
            currentSessionId = null;
            localStorage.removeItem('hattz_session_id');
            chatMessages.innerHTML = '';
            showWelcomeMessage();
        }

        // Reload session list
        await loadSessions();

    } catch (error) {
        console.error('Failed to delete session:', error);
    }
}

// Show welcome message
function showWelcomeMessage() {
    chatMessages.innerHTML = `
        <div class="welcome-message">
            <h2>Hattz Empire AI Team</h2>
            <p>비판적 스탠스로 무장한 AI 팀에게 질문하세요.</p>
            <div class="quick-actions">
                <button class="quick-btn" data-msg="새로운 기능 추가하고 싶어">💡 새 기능 요청</button>
                <button class="quick-btn" data-action="code-review" data-msg="">🔍 코드 리뷰</button>
                <button class="quick-btn" data-action="strategy" data-msg="">📊 전략 분석</button>
                <button class="quick-btn" data-action="ai-team" data-msg="Hattz AI팀 시스템을 개선하고 싶어">🔧 AI팀 수정</button>
                <button class="quick-btn" data-action="web-research" data-msg="외부 데이터를 검색해서 분석해줘">🌐 외부 검색</button>
            </div>
        </div>
    `;
    attachQuickButtonListeners();
}

// Load current session on page load
async function loadCurrentSession() {
    console.log('[DEBUG] loadCurrentSession() called');
    console.log('[DEBUG] currentSessionId from localStorage:', currentSessionId);

    // If we have a session ID in localStorage, load that session
    if (currentSessionId) {
        try {
            const response = await fetch(`/api/sessions/${currentSessionId}/switch`, {
                method: 'POST'
            });

            if (!response.ok) {
                console.log('[DEBUG] Session not found, clearing localStorage');
                localStorage.removeItem('hattz_session_id');
                currentSessionId = null;
                return;
            }

            const data = await response.json();

            if (data.session) {
                console.log('[DEBUG] Loaded session:', data.session.id);

                if (data.messages && data.messages.length > 0) {
                    chatMessages.innerHTML = '';
                    data.messages.forEach(msg => {
                        appendMessage(msg.role, msg.content, msg.agent || data.session.agent);
                    });
                }

                // Update session list to highlight active session
                renderSessionList();
            }
        } catch (error) {
            console.error('[DEBUG] Failed to load session:', error);
            localStorage.removeItem('hattz_session_id');
            currentSessionId = null;
        }
    } else {
        console.log('[DEBUG] No session ID in localStorage, showing welcome');
    }
}

// New Chat button handler
newChatBtn.addEventListener('click', createNewSession);

// Initialize
loadProjects();
loadSessions();
loadCurrentSession();
attachQuickButtonListeners();
document.getElementById('check-all-btn').addEventListener('click', checkAllApis);

// Auto-check API health on page load
checkAllApis();
