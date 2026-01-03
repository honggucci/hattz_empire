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
        // Use streaming endpoint - 세션 ID 함께 전송
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, agent, session_id: currentSessionId })
        });

        // Remove loading indicator
        removeLoading(loadingId);

        // Handle streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let assistantMessage = null;
        let fullContent = '';
        let isComplete = false;  // done: true 받았는지 추적

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));

                        // 서버에서 세션 ID를 받으면 저장 (새 세션인 경우)
                        if (data.session_id && !currentSessionId) {
                            currentSessionId = data.session_id;
                            localStorage.setItem('hattz_session_id', data.session_id);
                            console.log('[Session] New session created:', data.session_id);
                        }

                        // 작업 단계 업데이트
                        if (data.stage) {
                            updateProcessingStage(data.stage);
                        }

                        if (data.done) {
                            // Streaming complete - 세션 ID 확인
                            if (data.session_id && currentSessionId !== data.session_id) {
                                currentSessionId = data.session_id;
                                localStorage.setItem('hattz_session_id', data.session_id);
                            }
                            isComplete = true;  // 완료 플래그 설정
                            break;
                        }

                        if (data.token) {
                            // 첫 토큰 받으면 응답 단계로 전환
                            if (!assistantMessage) {
                                updateProcessingStage('responding');
                                assistantMessage = appendMessage('assistant', fullContent, agent, true);
                            }

                            fullContent += data.token;
                            updateMessageContent(assistantMessage, fullContent);
                        }
                    } catch (e) {
                        // Skip invalid JSON
                    }
                }
            }

            // done: true 받으면 루프 종료
            if (isComplete) break;
        }

        // done: true 받았을 때만 프로그레스바 숨김
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

// Message counter for unique IDs
let messageCounter = 0;

// Append message to chat
function appendMessage(role, content, agent, isStreaming = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const messageId = `msg_${Date.now()}_${messageCounter++}`;
    messageDiv.dataset.messageId = messageId;

    const time = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });

    // Assistant 메시지에만 피드백 버튼 추가
    const feedbackButtons = role === 'assistant' ? `
        <div class="feedback-buttons" data-message-id="${messageId}">
            <button class="feedback-btn approve" onclick="sendFeedback('${messageId}', 'approve')" title="좋아요">👍</button>
            <button class="feedback-btn reject" onclick="sendFeedback('${messageId}', 'reject')" title="별로예요">👎</button>
            <button class="feedback-btn redo" onclick="sendFeedback('${messageId}', 'redo')" title="다시 해줘">🔄</button>
        </div>
    ` : '';

    messageDiv.innerHTML = `
        <div class="message-header">
            ${role === 'assistant' ? `<span class="agent-badge">${agent}</span>` : ''}
            <span>${time}</span>
        </div>
        <div class="message-content">${formatContent(content)}</div>
        ${feedbackButtons}
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

// 작업 단계 정보
const PROCESSING_STAGES = {
    'thinking': { icon: '🤔', text: 'PM이 생각 중', stage: 'ANALYZING REQUEST' },
    'calling': { icon: '📞', text: '에이전트 호출 중', stage: 'CALLING SUB-AGENTS' },
    'executing': { icon: '⚡', text: '명령 실행 중', stage: 'EXECUTING COMMANDS' },
    'analyzing': { icon: '🔍', text: '결과 분석 중', stage: 'ANALYZING RESULTS' },
    'responding': { icon: '✍️', text: '응답 작성 중', stage: 'GENERATING RESPONSE' }
};

// Set status with processing stage
function setStatus(text, loading, stage = 'thinking') {
    const statusText = document.getElementById('status-text');
    const dot = document.querySelector('.status-dot');
    const processingBar = document.getElementById('processing-bar');
    const processingIcon = processingBar?.querySelector('.processing-icon');
    const processingText = processingBar?.querySelector('.processing-text');
    const processingStage = document.getElementById('processing-stage');

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
            processingBar.dataset.stage = stage;

            const stageInfo = PROCESSING_STAGES[stage] || PROCESSING_STAGES['thinking'];

            if (processingIcon) {
                processingIcon.textContent = stageInfo.icon;
            }
            if (processingText) {
                // 기존 dots 보존하면서 텍스트만 업데이트
                const dotsHtml = '<span class="processing-dots"><span></span><span></span><span></span></span>';
                processingText.innerHTML = `${stageInfo.text}${dotsHtml}`;
            }
            if (processingStage) {
                processingStage.textContent = stageInfo.stage;
            }
        } else {
            processingBar.classList.add('hidden');
        }
    }
}

// Update processing stage (can be called during streaming)
function updateProcessingStage(stage) {
    const processingBar = document.getElementById('processing-bar');
    if (processingBar && !processingBar.classList.contains('hidden')) {
        setStatus('Processing...', true, stage);
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

// =============================================================================
// CEO Feedback System
// =============================================================================

// Send feedback to server
async function sendFeedback(messageId, feedbackType) {
    const feedbackBtns = document.querySelector(`.feedback-buttons[data-message-id="${messageId}"]`);
    if (!feedbackBtns) return;

    // Disable buttons
    feedbackBtns.querySelectorAll('.feedback-btn').forEach(btn => btn.disabled = true);

    // Map feedback types
    const feedbackMap = {
        'approve': 'ceo_approve',
        'reject': 'ceo_reject',
        'redo': 'ceo_redo'
    };

    try {
        const response = await fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message_id: messageId,
                feedback_type: feedbackMap[feedbackType],
                session_id: currentSessionId
            })
        });

        const data = await response.json();

        // Show result
        if (feedbackType === 'approve') {
            feedbackBtns.innerHTML = '<span class="feedback-result success">👍 평가 완료 (+20점)</span>';
        } else if (feedbackType === 'reject') {
            feedbackBtns.innerHTML = '<span class="feedback-result fail">👎 평가 완료 (-25점)</span>';
        } else if (feedbackType === 'redo') {
            feedbackBtns.innerHTML = '<span class="feedback-result redo">🔄 재작업 요청됨 (-10점)</span>';
            // TODO: Trigger re-generation
        }

        // Update scorecard display if exists
        updateScoreDisplay();

    } catch (error) {
        console.error('Feedback error:', error);
        feedbackBtns.querySelectorAll('.feedback-btn').forEach(btn => btn.disabled = false);
    }
}

// Update score display in UI
async function updateScoreDisplay() {
    try {
        const response = await fetch('/api/scores');
        const data = await response.json();

        // If there's a score display element, update it
        const scoreDisplay = document.getElementById('score-display');
        if (scoreDisplay && data.leaderboard) {
            const top3 = data.leaderboard.slice(0, 3);
            scoreDisplay.innerHTML = top3.map(s =>
                `<div class="score-item">${s.model}:${s.role} = ${s.total_score}pts</div>`
            ).join('');
        }
    } catch (error) {
        console.log('Score fetch skipped:', error.message);
    }
}

// =============================================================================
// Background Tasks - 웹 닫아도 계속 실행!
// =============================================================================

// 활성화된 백그라운드 작업 추적
let activeBackgroundTasks = {};
let taskPollingInterval = null;

// 백그라운드 작업 시작
async function startBackgroundTask(message) {
    try {
        const response = await fetch('/api/task/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                agent: currentAgent,
                session_id: currentSessionId
            })
        });

        const data = await response.json();

        if (data.task_id) {
            activeBackgroundTasks[data.task_id] = {
                message: message,
                status: 'running',
                startedAt: new Date()
            };

            // 세션 ID 업데이트
            if (data.session_id && !currentSessionId) {
                currentSessionId = data.session_id;
                localStorage.setItem('hattz_session_id', data.session_id);
            }

            // UI에 작업 시작 표시
            showBackgroundTaskNotification(data.task_id, message, 'running');

            // 폴링 시작
            startTaskPolling();

            return data.task_id;
        }
    } catch (error) {
        console.error('[BackgroundTask] Start error:', error);
    }
    return null;
}

// 작업 상태 폴링
function startTaskPolling() {
    if (taskPollingInterval) return;  // 이미 실행 중

    taskPollingInterval = setInterval(async () => {
        const taskIds = Object.keys(activeBackgroundTasks);

        if (taskIds.length === 0) {
            clearInterval(taskPollingInterval);
            taskPollingInterval = null;
            return;
        }

        for (const taskId of taskIds) {
            try {
                const response = await fetch(`/api/task/${taskId}`);
                const task = await response.json();

                if (task.status === 'success') {
                    // 완료!
                    delete activeBackgroundTasks[taskId];
                    showBackgroundTaskResult(taskId, task);
                    playNotificationSound();
                } else if (task.status === 'failed') {
                    // 실패
                    delete activeBackgroundTasks[taskId];
                    showBackgroundTaskError(taskId, task);
                } else {
                    // 진행 중 - 프로그래스 업데이트
                    updateBackgroundTaskProgress(taskId, task);
                }
            } catch (error) {
                console.error(`[BackgroundTask] Poll error for ${taskId}:`, error);
            }
        }
    }, 3000);  // 3초마다 체크
}

// 백그라운드 작업 알림 표시
function showBackgroundTaskNotification(taskId, message, status) {
    // 기존 알림 영역 찾기 또는 생성
    let notifArea = document.getElementById('background-tasks-area');
    if (!notifArea) {
        notifArea = document.createElement('div');
        notifArea.id = 'background-tasks-area';
        notifArea.className = 'background-tasks-area';
        document.querySelector('.chat-container').prepend(notifArea);
    }

    const taskDiv = document.createElement('div');
    taskDiv.id = `task-${taskId}`;
    taskDiv.className = 'background-task-item running';
    taskDiv.innerHTML = `
        <div class="task-icon">🔄</div>
        <div class="task-info">
            <div class="task-message">${escapeHtml(message.slice(0, 50))}...</div>
            <div class="task-status">
                <span class="status-text">실행 중</span>
                <span class="progress-bar"><span class="progress-fill" style="width: 0%"></span></span>
            </div>
        </div>
        <button class="task-cancel" onclick="cancelBackgroundTask('${taskId}')" title="취소">✕</button>
    `;

    notifArea.appendChild(taskDiv);
}

// 진행률 업데이트
function updateBackgroundTaskProgress(taskId, task) {
    const taskDiv = document.getElementById(`task-${taskId}`);
    if (!taskDiv) return;

    const progressFill = taskDiv.querySelector('.progress-fill');
    const statusText = taskDiv.querySelector('.status-text');

    if (progressFill) {
        progressFill.style.width = `${task.progress}%`;
    }
    if (statusText) {
        const stageText = {
            'waiting': '대기 중',
            'thinking': 'PM이 생각 중',
            'executing': '명령 실행 중',
            'analyzing': '결과 분석 중',
            'finalizing': '마무리 중'
        };
        statusText.textContent = stageText[task.stage] || task.stage;
    }
}

// 작업 완료 결과 표시
function showBackgroundTaskResult(taskId, task) {
    const taskDiv = document.getElementById(`task-${taskId}`);
    if (taskDiv) {
        taskDiv.classList.remove('running');
        taskDiv.classList.add('completed');
        taskDiv.querySelector('.task-icon').textContent = '✅';
        taskDiv.querySelector('.status-text').textContent = '완료!';
        taskDiv.querySelector('.progress-fill').style.width = '100%';

        // 5초 후 자동 숨김
        setTimeout(() => {
            taskDiv.style.opacity = '0';
            setTimeout(() => taskDiv.remove(), 300);
        }, 5000);
    }

    // 채팅에 결과 추가
    if (task.result) {
        appendMessage('assistant', task.result, currentAgent);
        loadSessions();  // 세션 목록 갱신
    }

    // 브라우저 알림 (권한 있는 경우)
    if (Notification.permission === 'granted') {
        new Notification('Hattz Empire', {
            body: '백그라운드 작업이 완료되었습니다!',
            icon: '/static/img/logo.png'
        });
    }
}

// 작업 실패 표시
function showBackgroundTaskError(taskId, task) {
    const taskDiv = document.getElementById(`task-${taskId}`);
    if (taskDiv) {
        taskDiv.classList.remove('running');
        taskDiv.classList.add('failed');
        taskDiv.querySelector('.task-icon').textContent = '❌';
        taskDiv.querySelector('.status-text').textContent = '실패';
    }

    appendMessage('assistant', `⚠️ 백그라운드 작업 실패: ${task.error}`, currentAgent);
}

// 작업 취소
async function cancelBackgroundTask(taskId) {
    try {
        await fetch(`/api/task/${taskId}/cancel`, { method: 'POST' });
        delete activeBackgroundTasks[taskId];

        const taskDiv = document.getElementById(`task-${taskId}`);
        if (taskDiv) {
            taskDiv.remove();
        }
    } catch (error) {
        console.error('[BackgroundTask] Cancel error:', error);
    }
}

// 알림 소리 재생
function playNotificationSound() {
    try {
        const audio = new Audio('/static/audio/notification.mp3');
        audio.volume = 0.5;
        audio.play().catch(() => {});  // 자동 재생 차단 시 무시
    } catch (e) {}
}

// 페이지 로드 시 미완료 작업 체크
async function checkPendingTasks() {
    if (!currentSessionId) return;

    try {
        const response = await fetch(`/api/tasks?session_id=${currentSessionId}`);
        const data = await response.json();

        for (const task of data.tasks || []) {
            if (task.status === 'running' || task.status === 'pending') {
                activeBackgroundTasks[task.id] = {
                    message: task.message,
                    status: task.status
                };
                showBackgroundTaskNotification(task.id, task.message, task.status);
            } else if (task.status === 'success' && !task.result_shown) {
                // 완료되었지만 아직 보지 못한 작업
                showBackgroundTaskResult(task.id, task);
            }
        }

        if (Object.keys(activeBackgroundTasks).length > 0) {
            startTaskPolling();
        }
    } catch (error) {
        console.error('[BackgroundTask] Check pending error:', error);
    }
}

// 브라우저 알림 권한 요청
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

// 초기화 시 호출
requestNotificationPermission();
checkPendingTasks();
