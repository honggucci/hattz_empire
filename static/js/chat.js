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

// Current mode (일반/논의/코딩)
let currentMode = 'normal';  // default: 일반

// AbortController for canceling requests
let currentAbortController = null;
let currentStreamId = null;  // 서버측 중단용
const abortBtn = document.getElementById('abort-btn');

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

// =============================================================================
// Jobs API 모드 vs SSE 모드 선택
// =============================================================================
let useJobsApi = true;  // true: Jobs API (브라우저 닫아도 계속), false: SSE (실시간 스트리밍)
let currentJobId = null;  // 현재 진행 중인 Job ID
let jobPollingInterval = null;  // Job 결과 폴링 인터벌

// Send message
async function sendMessage() {
    let message = messageInput.value.trim();
    if (!message) return;

    // ========================================
    // 프로젝트 선택 강제 체크
    // ========================================
    if (!currentProject) {
        showProjectRequiredModal();
        return;  // 메시지 전송 차단
    }

    const agent = currentAgent;

    // 프로젝트 컨텍스트를 모든 메시지에 추가
    const projectContext = `[PROJECT: ${currentProject}]`;
    if (!message.startsWith('[PROJECT:')) {
        message = `${projectContext}\n${message}`;
    }

    // 코드 리뷰 요청 시 파일 목록도 추가
    if (message.includes('코드 리뷰') || message.includes('코드리뷰') || message.includes('code review')) {
        if (projectFiles.length > 0) {
            const fileList = projectFiles.slice(0, 20).map(f => f.relative).join('\n- ');
            message = `${projectContext}\n[파일 목록 (${projectFiles.length}개 중 상위 20개)]:\n- ${fileList}\n\n${message}`;
        }
    }

    // Clear welcome message if exists
    const welcome = chatMessages.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    // Add user message
    appendMessage('user', messageInput.value.trim(), agent);
    const originalMessage = messageInput.value.trim();
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Jobs API 모드 vs SSE 모드
    if (useJobsApi) {
        await sendMessageViaJobsApi(message, originalMessage, agent);
    } else {
        await sendMessageViaSSE(message, agent);
    }
}

// =============================================================================
// Jobs API 모드 - 브라우저 닫아도 백그라운드에서 계속 실행
// =============================================================================
async function sendMessageViaJobsApi(message, originalMessage, agent) {
    // Show loading
    const loadingId = showLoading();
    setStatus('Submitting to queue...', true, 'thinking');

    // 위젯 표시
    removeWidgetTask('streaming-current');
    const widgetTaskId = showStreamingInWidget(originalMessage || message);

    try {
        // 1. Jobs API로 작업 생성
        const response = await fetch('/api/chat/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                agent: agent,
                session_id: currentSessionId,
                project: currentProject,
                mode: currentMode  // v2.6.4: 모드 전송
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to submit job');
        }

        // 세션 ID 업데이트
        if (data.session_id) {
            currentSessionId = data.session_id;
            localStorage.setItem('hattz_session_id', data.session_id);
        }

        currentJobId = data.job_id;
        console.log('[Jobs] Created:', data.job_id);

        // 2. 작업 결과 폴링 시작
        removeLoading(loadingId);
        setStatus('Processing...', true, 'thinking');

        updateWidgetTask(widgetTaskId, {
            message: originalMessage || message,
            stage: 'waiting',
            progress: 10,
            startedAt: new Date().toISOString()
        });

        // 폴링 시작
        startJobPolling(data.job_id, widgetTaskId, agent);

    } catch (error) {
        console.error('[Jobs] Error:', error);
        removeLoading(loadingId);
        setStatus('Error', false);
        updateWidgetTask(widgetTaskId, {
            message: '오류 발생',
            stage: 'failed',
            progress: 0
        });
        setTimeout(() => removeWidgetTask(widgetTaskId), 3000);
        appendMessage('assistant', `Error: ${error.message}`, agent);
    }
}

// Job 결과 Long Polling
async function startJobPolling(jobId, widgetTaskId, agent) {
    let retryCount = 0;
    const maxRetries = 20;  // 최대 20회 (30초 × 20 = 10분)
    let progressEstimate = 10;

    const poll = async () => {
        if (retryCount >= maxRetries) {
            setStatus('Timeout', false);
            updateWidgetTask(widgetTaskId, {
                message: '시간 초과',
                stage: 'failed',
                progress: 0
            });
            appendMessage('assistant', '⚠️ 작업 시간이 초과되었습니다. 백그라운드에서 계속 처리 중일 수 있습니다.', agent);
            currentJobId = null;
            return;
        }

        try {
            // Long Polling: 서버가 완료/변경될 때까지 최대 30초 대기
            const response = await fetch(`/api/chat/job/${jobId}?wait=true&timeout=30`);
            const data = await response.json();

            if (data.status === 'completed') {
                // 작업 완료!
                currentJobId = null;
                setStatus('Ready', false);
                completeStreamingInWidget(widgetTaskId);
                dismissRecoveryBanner();  // 복구 배너 닫기

                // 응답 표시
                if (data.response) {
                    const msgDiv = appendMessage('assistant', data.response, agent);
                    if (data.model_info) {
                        addModelBadge(msgDiv, data.model_info);
                    }
                }

                loadSessions();
                return;  // 폴링 종료

            } else if (data.status === 'failed') {
                // 작업 실패
                currentJobId = null;
                setStatus('Failed', false);
                dismissRecoveryBanner();  // 복구 배너 닫기
                updateWidgetTask(widgetTaskId, {
                    message: '작업 실패',
                    stage: 'failed',
                    progress: 0
                });
                setTimeout(() => removeWidgetTask(widgetTaskId), 3000);
                appendMessage('assistant', `⚠️ 작업 실패: ${data.error || '알 수 없는 오류'}`, agent);
                return;  // 폴링 종료

            } else {
                // 진행 중 - 상태 업데이트 후 다시 Long Polling
                const stage = data.stage || 'thinking';
                progressEstimate = Math.min(progressEstimate + 5, 90);

                setStatus(`Processing (${stage})...`, true, stage, data.sub_agent);
                updateWidgetTask(widgetTaskId, {
                    message: data.status_message || '처리 중...',
                    stage: stage,
                    progress: progressEstimate,
                    sub_agent: data.sub_agent
                });

                retryCount++;
                poll();  // 재귀 호출로 다음 Long Polling
            }
        } catch (error) {
            console.error('[Jobs] Poll error:', error);
            // 네트워크 에러 시 잠시 대기 후 재시도
            retryCount++;
            setTimeout(poll, 2000);  // 2초 후 재시도
        }
    };

    poll();  // 첫 번째 Long Polling 시작
}

// Job 폴링 중단
function stopJobPolling() {
    if (jobPollingInterval) {
        clearInterval(jobPollingInterval);
        jobPollingInterval = null;
    }
}

// =============================================================================
// SSE 모드 - 실시간 스트리밍 (기존 방식)
// =============================================================================
async function sendMessageViaSSE(message, agent) {
    // Show loading
    const loadingId = showLoading();

    // Set status to loading
    setStatus('Thinking...', true);

    // 이전 위젯 정리 후 새 위젯 표시
    removeWidgetTask('streaming-current');
    const widgetTaskId = showStreamingInWidget(message);

    // Create AbortController for this request
    currentAbortController = new AbortController();

    // 로컬 요청 플래그 설정 (SSE 이벤트 중복 방지)
    isLocalRequest = true;

    try {
        // Use streaming endpoint - 세션 ID 함께 전송
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                agent,
                session_id: currentSessionId,
                mode: currentMode  // v2.6.4: 모드 전송
            }),
            signal: currentAbortController.signal
        });

        // Remove loading indicator
        removeLoading(loadingId);

        // Handle streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let assistantMessage = null;
        let fullContent = '';
        let isComplete = false;  // done: true 받았는지 추적
        let modelInfo = null;  // 모델 정보 저장
        let finalResponseMessage = null;  // 최종 PM 응답 메시지 (하위 에이전트 호출 후)
        let finalResponseContent = '';  // 최종 응답 내용

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

                        // 스트림 ID 저장 (서버측 중단용)
                        if (data.stream_id) {
                            currentStreamId = data.stream_id;
                            console.log('[Stream] ID:', data.stream_id);
                        }

                        // 서버측에서 중단됨
                        if (data.aborted) {
                            console.log('[Stream] Aborted by server');
                            if (data.partial && assistantMessage) {
                                updateMessageContent(assistantMessage, data.partial + '\n\n[응답 중단됨]');
                            } else if (!assistantMessage) {
                                appendMessage('assistant', '[응답이 중단되었습니다]', agent);
                            }
                            isComplete = true;
                            break;
                        }

                        // 모델 정보 수신
                        if (data.model_info) {
                            modelInfo = data.model_info;
                            console.log('[Model]', modelInfo.model_name, `(${modelInfo.tier})`);
                        }

                        // 작업 단계 업데이트
                        if (data.stage) {
                            // 하위 에이전트 정보 포함 업데이트
                            let stageText = data.stage;
                            let widgetMessage = message;

                            // 하위 에이전트 호출 시 추가 정보 표시
                            if (data.stage === 'calling' && data.sub_agent) {
                                stageText = `calling_${data.sub_agent}`;
                                widgetMessage = `${data.sub_agent.toUpperCase()} 호출 중 (${data.progress || ''})`;
                            } else if (data.stage === 'sub_agent_done' && data.sub_agent) {
                                widgetMessage = `${data.sub_agent.toUpperCase()} 완료 (${data.progress || ''})`;
                            } else if (data.stage === 'delegating' && data.agents) {
                                widgetMessage = `위임: ${data.agents.join(', ')}`;
                            }

                            updateProcessingStage(data.stage, data.sub_agent);

                            // 위젯도 업데이트
                            const progressMap = {
                                'thinking': 15,
                                'responding': 30,
                                'delegating': 35,
                                'calling': 50,
                                'sub_agent_done': 70,
                                'summarizing': 80,
                                'final_response': 90,
                                'executing': 60,
                                'analyzing': 75
                            };
                            updateWidgetTask(widgetTaskId, {
                                message: widgetMessage,
                                stage: data.stage,
                                progress: progressMap[data.stage] || 50,
                                startedAt: new Date().toISOString(),
                                sub_agent: data.sub_agent,
                                total_agents: data.total_agents
                            });
                        }

                        // PM 응답 완료 (하위 에이전트 호출 전)
                        if (data.pm_done) {
                            console.log('[PM] Response done, checking for sub-agent calls...');
                            // pm_done은 done이 아님 - 위젯 유지
                        }

                        // 팩트체크 결과 처리
                        if (data.fact_check) {
                            console.log('[FactCheck]', data.fact_check.valid ? '✅ Valid' : '⚠️ Hallucination detected');
                            if (!data.fact_check.valid) {
                                // 거짓말 탐지 경고 표시
                                showFactCheckWarning(data.fact_check);
                            }
                        }

                        if (data.done) {
                            // 모델 정보가 done과 함께 오면 업데이트
                            if (data.model_info) {
                                modelInfo = data.model_info;
                            }
                            // Streaming complete - 세션 ID 확인
                            if (data.session_id && currentSessionId !== data.session_id) {
                                currentSessionId = data.session_id;
                                localStorage.setItem('hattz_session_id', data.session_id);
                            }
                            isComplete = true;  // 완료 플래그 설정
                            break;
                        }

                        // 하위 에이전트 완료 시 로그만 (UI에 내용 표시 안 함)
                        if (data.stage === 'sub_agent_done' && data.sub_agent) {
                            console.log(`[Sub-Agent] ${data.sub_agent} completed (${data.progress})`);
                        }

                        if (data.token) {
                            // is_final 토큰이면 최종 PM 응답 (새 메시지 박스)
                            if (data.is_final) {
                                if (!finalResponseMessage) {
                                    // 최종 응답용 새 메시지 박스 생성
                                    finalResponseContent = '';
                                    finalResponseMessage = appendMessage('assistant', '', agent, true);
                                }
                                finalResponseContent += data.token;
                                updateMessageContent(finalResponseMessage, finalResponseContent);
                            } else {
                                // 첫 토큰 받으면 응답 단계로 전환
                                if (!assistantMessage) {
                                    updateProcessingStage('responding');
                                    assistantMessage = appendMessage('assistant', fullContent, agent, true);
                                }

                                fullContent += data.token;
                                updateMessageContent(assistantMessage, fullContent);
                            }
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
        currentAbortController = null;
        isLocalRequest = false;  // 로컬 요청 완료

        // 모델 정보 뱃지 추가 (응답 완료 후)
        // 최종 응답 메시지가 있으면 거기에, 없으면 첫 응답에 추가
        const targetMessage = finalResponseMessage || assistantMessage;
        if (targetMessage && modelInfo) {
            addModelBadge(targetMessage, modelInfo);
        }

        // 위젯 완료 표시
        completeStreamingInWidget(widgetTaskId);

        // Reload sessions to update list (name may have changed)
        loadSessions();

    } catch (error) {
        currentAbortController = null;
        isLocalRequest = false;  // 로컬 요청 완료 (에러 시에도)

        // AbortError는 사용자가 중단한 것
        if (error.name === 'AbortError') {
            console.log('Request aborted by user');
            removeLoading(loadingId);
            removeWidgetTask(widgetTaskId);

            // 중단된 응답에 표시
            if (fullContent) {
                updateMessageContent(assistantMessage, fullContent + '\n\n[응답 중단됨]');
            } else {
                appendMessage('assistant', '[응답이 중단되었습니다]', agent);
            }

            setStatus('Aborted', false);
            return;
        }

        console.error('Error:', error);
        removeLoading(loadingId);

        // 위젯에 실패 표시
        updateWidgetTask(widgetTaskId, {
            message: '오류 발생',
            stage: 'failed',
            progress: 0
        });
        setTimeout(() => removeWidgetTask(widgetTaskId), 3000);

        appendMessage('assistant', `Error: ${error.message}`, agent);
        setStatus('Error', false);
    }
}

// Abort current request (v2.4.3: CLI 프로세스 강제 종료 추가)
async function abortRequest() {
    console.log('Aborting request...');

    // 1. 서버측 스트림 + CLI 프로세스 중단
    if (currentStreamId) {
        try {
            const response = await fetch('/api/chat/abort', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    stream_id: currentStreamId,
                    session_id: currentSessionId,  // v2.4.3: CLI 프로세스 종료용
                    kill_cli: true
                })
            });
            const result = await response.json();
            console.log('[Abort] 결과:', result);
        } catch (e) {
            console.error('[Abort] 실패:', e);
        }
        currentStreamId = null;
    }

    // 2. 클라이언트측 fetch 중단
    if (currentAbortController) {
        currentAbortController.abort();
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

// 작업 단계 정보 (하위 에이전트 포함)
const PROCESSING_STAGES = {
    'thinking': { icon: '🤔', text: 'PM이 생각 중', stage: 'ANALYZING REQUEST' },
    'responding': { icon: '✍️', text: 'PM 응답 중', stage: 'PM RESPONDING' },
    'delegating': { icon: '🚀', text: '에이전트 위임 중', stage: 'DELEGATING TO AGENTS' },
    'calling': { icon: '📞', text: '에이전트 호출 중', stage: 'CALLING SUB-AGENT' },
    'sub_agent_done': { icon: '✅', text: '에이전트 완료', stage: 'SUB-AGENT DONE' },
    'summarizing': { icon: '📝', text: 'PM이 결과 종합 중', stage: 'PM SUMMARIZING' },
    'final_response': { icon: '✨', text: 'PM 최종 응답 중', stage: 'FINAL RESPONSE' },
    'executing': { icon: '⚡', text: '명령 실행 중', stage: 'EXECUTING COMMANDS' },
    'analyzing': { icon: '🔍', text: '결과 분석 중', stage: 'ANALYZING RESULTS' }
};

// Set status with processing stage
function setStatus(text, loading, stage = 'thinking', subAgent = null) {
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
                // 하위 에이전트 정보 포함
                let displayText = stageInfo.text;
                if (subAgent && (stage === 'calling' || stage === 'sub_agent_done')) {
                    displayText = `${subAgent.toUpperCase()} ${stage === 'calling' ? '작업 중' : '완료'}`;
                }
                const dotsHtml = '<span class="processing-dots"><span></span><span></span><span></span></span>';
                processingText.innerHTML = `${displayText}${dotsHtml}`;
            }
            if (processingStage) {
                // 하위 에이전트 표시
                let stageDisplay = stageInfo.stage;
                if (subAgent) {
                    stageDisplay = `${subAgent.toUpperCase()} → ${stageInfo.stage}`;
                }
                processingStage.textContent = stageDisplay;
            }
        } else {
            processingBar.classList.add('hidden');
        }
    }
}

// Update processing stage (can be called during streaming)
function updateProcessingStage(stage, subAgent = null) {
    const processingBar = document.getElementById('processing-bar');
    if (processingBar && !processingBar.classList.contains('hidden')) {
        // 하위 에이전트 정보가 있으면 텍스트에 추가
        let statusText = 'Processing...';
        if (subAgent) {
            statusText = `${subAgent.toUpperCase()} 처리 중...`;
        }
        setStatus(statusText, true, stage, subAgent);
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

// Abort button listener
if (abortBtn) {
    abortBtn.addEventListener('click', abortRequest);
}

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
    console.log('[DEBUG] switchSession called with:', sessionId);
    try {
        const response = await fetch(`/api/sessions/${sessionId}/switch`, {
            method: 'POST'
        });
        const data = await response.json();
        console.log('[DEBUG] switchSession response:', data);

        currentSessionId = sessionId;
        localStorage.setItem('hattz_session_id', sessionId);

        // Update UI
        renderSessionList();

        // Clear and load messages
        chatMessages.innerHTML = '';

        if (data.messages && data.messages.length > 0) {
            console.log('[DEBUG] Loading', data.messages.length, 'messages');
            data.messages.forEach(msg => {
                appendMessage(msg.role, msg.content, msg.agent || data.session.agent);
            });
        } else {
            console.log('[DEBUG] No messages, showing welcome');
            showWelcomeMessage();
        }

        // 모바일에서 사이드바 닫기
        if (typeof closeMobileSidebar === 'function') {
            closeMobileSidebar();
        }

        // SSE 재연결 (새 세션으로)
        if (typeof reconnectProgressSSE === 'function') {
            reconnectProgressSSE();
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

// =============================================================================
// Session Continue Modal - 이전 세션에서 이어가기 (v2.6.9)
// =============================================================================

const continueSessionBtn = document.getElementById('continue-session-btn');
const sessionContinueModal = document.getElementById('session-continue-modal');
const closeContinueModal = document.getElementById('close-continue-modal');
const cancelContinueBtn = document.getElementById('cancel-continue-btn');
const confirmContinueBtn = document.getElementById('confirm-continue-btn');
const sessionSelectList = document.getElementById('session-select-list');
const sessionSearchInput = document.getElementById('session-search-input');
const selectedSessionPreview = document.getElementById('selected-session-preview');

let selectedParentSessionId = null;

// 모달 열기
function openContinueModal() {
    if (sessionContinueModal) {
        sessionContinueModal.classList.remove('hidden');
        renderSessionSelectList();
        selectedParentSessionId = null;
        if (confirmContinueBtn) confirmContinueBtn.disabled = true;
        if (selectedSessionPreview) {
            selectedSessionPreview.innerHTML = '<div class="preview-placeholder">세션을 선택하면 미리보기가 표시됩니다</div>';
        }
    }
}

// 모달 닫기
function closeContinueModalHandler() {
    if (sessionContinueModal) {
        sessionContinueModal.classList.add('hidden');
        selectedParentSessionId = null;
    }
}

// 세션 선택 목록 렌더링
function renderSessionSelectList(filter = '') {
    if (!sessionSelectList) return;

    const filteredSessions = sessions.filter(session => {
        const name = (session.name || 'New Chat').toLowerCase();
        const project = (session.project || '').toLowerCase();
        const searchTerm = filter.toLowerCase();
        return name.includes(searchTerm) || project.includes(searchTerm);
    });

    if (filteredSessions.length === 0) {
        sessionSelectList.innerHTML = '<div class="no-sessions-select">이어갈 수 있는 세션이 없습니다</div>';
        return;
    }

    sessionSelectList.innerHTML = filteredSessions.map(session => {
        const name = session.name || 'New Chat';
        const date = new Date(session.updated_at).toLocaleDateString('ko-KR', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
        const isSelected = session.id === selectedParentSessionId;

        return `
            <div class="session-select-item ${isSelected ? 'selected' : ''}"
                 data-session-id="${session.id}"
                 onclick="selectParentSession('${session.id}')">
                <div class="session-select-icon">${isSelected ? '✓' : '💬'}</div>
                <div class="session-select-info">
                    <div class="session-select-name">${escapeHtml(name)}</div>
                    <div class="session-select-meta">
                        <span class="session-select-project">${session.project || '프로젝트 없음'}</span>
                        <span class="session-select-date">${date}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// 부모 세션 선택
async function selectParentSession(sessionId) {
    selectedParentSessionId = sessionId;
    if (confirmContinueBtn) confirmContinueBtn.disabled = false;

    // 선택 상태 업데이트
    document.querySelectorAll('.session-select-item').forEach(item => {
        item.classList.toggle('selected', item.dataset.sessionId === sessionId);
        const icon = item.querySelector('.session-select-icon');
        if (icon) {
            icon.textContent = item.dataset.sessionId === sessionId ? '✓' : '💬';
        }
    });

    // 미리보기 로드
    if (selectedSessionPreview) {
        selectedSessionPreview.innerHTML = '<div class="preview-loading">미리보기 로드 중...</div>';

        try {
            // 세션 메시지 가져오기
            const response = await fetch(`/api/sessions/${sessionId}/messages`);
            const messages = await response.json();

            const session = sessions.find(s => s.id === sessionId);
            const sessionName = session?.name || 'New Chat';
            const messageCount = messages.length;

            // 최근 3개 메시지 미리보기
            const recentMessages = messages.slice(-6).map(msg => {
                const role = msg.role === 'user' ? '👤' : '🤖';
                const content = (msg.content || '').slice(0, 100);
                return `<div class="preview-message ${msg.role}">
                    <span class="preview-role">${role}</span>
                    <span class="preview-content">${escapeHtml(content)}${msg.content?.length > 100 ? '...' : ''}</span>
                </div>`;
            }).join('');

            selectedSessionPreview.innerHTML = `
                <div class="preview-header">
                    <strong>${escapeHtml(sessionName)}</strong>
                    <span class="preview-count">${messageCount}개 메시지</span>
                </div>
                <div class="preview-messages">
                    ${recentMessages || '<div class="preview-empty">메시지 없음</div>'}
                </div>
                <div class="preview-footer">
                    <small>💡 이 세션의 요약과 최근 대화가 새 세션에 주입됩니다</small>
                </div>
            `;
        } catch (error) {
            selectedSessionPreview.innerHTML = '<div class="preview-error">미리보기를 불러올 수 없습니다</div>';
        }
    }
}

// 이전 세션에서 이어가기로 새 세션 생성
async function createSessionFromParent() {
    if (!selectedParentSessionId) {
        alert('이어갈 세션을 선택해주세요');
        return;
    }

    // 프로젝트 선택 확인
    if (!currentProject) {
        alert('프로젝트를 먼저 선택해주세요');
        closeContinueModalHandler();
        showProjectRequiredModal();
        return;
    }

    try {
        if (confirmContinueBtn) {
            confirmContinueBtn.disabled = true;
            confirmContinueBtn.textContent = '생성 중...';
        }

        const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent: currentAgent,
                project: currentProject,
                parent_session_id: selectedParentSessionId
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to create session');
        }

        currentSessionId = data.session_id;
        localStorage.setItem('hattz_session_id', data.session_id);

        // 모달 닫기
        closeContinueModalHandler();

        // 채팅 영역 초기화 및 컨텍스트 표시
        chatMessages.innerHTML = '';

        // 이전 세션 컨텍스트가 있으면 시스템 메시지로 표시
        if (data.parent_context) {
            const contextDiv = document.createElement('div');
            contextDiv.className = 'message system context-message';
            contextDiv.innerHTML = `
                <div class="message-header">
                    <span class="agent-badge system">📚 이전 세션 컨텍스트</span>
                </div>
                <div class="message-content">
                    <details>
                        <summary>이전 세션 요약 펼치기</summary>
                        <div class="context-content">${formatContent(data.parent_context)}</div>
                    </details>
                </div>
            `;
            chatMessages.appendChild(contextDiv);
        }

        // 환영 메시지 표시
        const welcomeDiv = document.createElement('div');
        welcomeDiv.className = 'welcome-message continue-welcome';
        welcomeDiv.innerHTML = `
            <h2>🔗 이전 세션에서 이어가기</h2>
            <p>이전 세션의 컨텍스트가 로드되었습니다. 대화를 이어가세요!</p>
        `;
        chatMessages.appendChild(welcomeDiv);

        // 세션 목록 새로고침
        await loadSessions();

        console.log('[Session] Created with parent:', selectedParentSessionId);

    } catch (error) {
        console.error('Failed to create session from parent:', error);
        alert(`세션 생성 실패: ${error.message}`);
    } finally {
        if (confirmContinueBtn) {
            confirmContinueBtn.disabled = false;
            confirmContinueBtn.textContent = '새 세션 시작';
        }
    }
}

// 이벤트 리스너 등록
if (continueSessionBtn) {
    continueSessionBtn.addEventListener('click', openContinueModal);
}

if (closeContinueModal) {
    closeContinueModal.addEventListener('click', closeContinueModalHandler);
}

if (cancelContinueBtn) {
    cancelContinueBtn.addEventListener('click', closeContinueModalHandler);
}

if (confirmContinueBtn) {
    confirmContinueBtn.addEventListener('click', createSessionFromParent);
}

if (sessionSearchInput) {
    sessionSearchInput.addEventListener('input', (e) => {
        renderSessionSelectList(e.target.value);
    });
}

// 모달 외부 클릭 시 닫기
if (sessionContinueModal) {
    sessionContinueModal.addEventListener('click', (e) => {
        if (e.target === sessionContinueModal) {
            closeContinueModalHandler();
        }
    });
}

// ESC 키로 모달 닫기
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sessionContinueModal && !sessionContinueModal.classList.contains('hidden')) {
        closeContinueModalHandler();
    }
});

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
async function showBackgroundTaskResult(taskId, task) {
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
        // 환영 메시지 제거
        const welcome = chatMessages.querySelector('.welcome-message');
        if (welcome) welcome.remove();

        appendMessage('assistant', task.result, task.agent_role || currentAgent);
        loadSessions();  // 세션 목록 갱신
    }

    // 결과 확인했음을 서버에 알림
    try {
        await fetch(`/api/task/${taskId}/shown`, { method: 'POST' });
    } catch (e) {
        console.error('[BackgroundTask] Mark shown error:', e);
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
        // 1. 실행 중인 작업 조회
        const runningResponse = await fetch(`/api/tasks?session_id=${currentSessionId}`);
        const runningData = await runningResponse.json();

        for (const task of runningData.tasks || []) {
            if (task.status === 'running' || task.status === 'pending') {
                activeBackgroundTasks[task.id] = {
                    message: task.message,
                    status: task.status
                };
                showBackgroundTaskNotification(task.id, task.message, task.status);
            }
        }

        if (Object.keys(activeBackgroundTasks).length > 0) {
            startTaskPolling();
        }

        // 2. 완료되었지만 아직 보지 못한 작업 조회 (별도 API)
        const unshownResponse = await fetch(`/api/tasks/unshown?session_id=${currentSessionId}`);
        const unshownData = await unshownResponse.json();

        if (unshownData.tasks && unshownData.tasks.length > 0) {
            console.log(`[BackgroundTask] Found ${unshownData.tasks.length} unshown completed tasks`);

            // 약간의 딜레이 후 순차적으로 표시 (사용자 경험 향상)
            for (let i = 0; i < unshownData.tasks.length; i++) {
                const task = unshownData.tasks[i];
                setTimeout(() => {
                    showBackgroundTaskResult(task.id, task);
                    playNotificationSound();
                }, i * 1000);  // 1초 간격으로 표시
            }
        }

        // 3. 백그라운드 채팅 결과 조회 (폰 꺼도 계속 실행된 채팅)
        await checkPendingChatResults();

    } catch (error) {
        console.error('[BackgroundTask] Check pending error:', error);
    }
}

// 백그라운드 채팅 결과 조회 (재접속 시)
async function checkPendingChatResults() {
    try {
        const response = await fetch('/api/chat/background/pending');
        const data = await response.json();

        if (data.tasks && data.tasks.length > 0) {
            console.log(`[BackgroundChat] Found ${data.count} pending chat results`);

            // 환영 메시지 제거
            const welcome = chatMessages.querySelector('.welcome-message');
            if (welcome) welcome.remove();

            // 순차적으로 결과 표시
            for (let i = 0; i < data.tasks.length; i++) {
                const task = data.tasks[i];
                setTimeout(() => {
                    // 원본 질문 표시 (이미 DB에 있지만 UI에 없을 수 있음)
                    if (task.original_message) {
                        appendMessage('user', task.original_message, task.agent);
                    }

                    // AI 응답 표시
                    const msgDiv = appendMessage('assistant', task.response, task.agent);

                    // 모델 정보 뱃지 추가
                    if (task.model_info) {
                        addModelBadge(msgDiv, task.model_info);
                    }

                    // 백그라운드 완료 표시
                    const bgBadge = document.createElement('span');
                    bgBadge.className = 'background-complete-badge';
                    bgBadge.innerHTML = '📱 백그라운드 완료';
                    bgBadge.title = `완료: ${task.completed_at}`;
                    msgDiv.querySelector('.message-header').appendChild(bgBadge);

                    playNotificationSound();
                }, i * 500);  // 0.5초 간격으로 표시
            }

            // 세션 목록 새로고침
            loadSessions();
        }
    } catch (error) {
        console.error('[BackgroundChat] Check pending error:', error);
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


// =============================================================================
// Background Tasks Widget - 진행 상태 위젯
// =============================================================================

const bgTasksWidget = document.getElementById('bg-tasks-widget');
const widgetToggle = document.getElementById('widget-toggle');
const widgetTasks = document.getElementById('widget-tasks');

// 위젯 토글 (최소화/확장)
if (widgetToggle) {
    widgetToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        bgTasksWidget.classList.toggle('minimized');
        widgetToggle.textContent = bgTasksWidget.classList.contains('minimized') ? '+' : '−';
    });
}

// 위젯 표시/숨김
function showTasksWidget() {
    if (bgTasksWidget) {
        bgTasksWidget.classList.remove('hidden');
    }
}

function hideTasksWidget() {
    if (bgTasksWidget) {
        bgTasksWidget.classList.add('hidden');
    }
}

// 위젯에 작업 추가/업데이트
function updateWidgetTask(taskId, taskData) {
    if (!widgetTasks) return;

    showTasksWidget();

    let taskEl = document.getElementById(`widget-task-${taskId}`);

    if (!taskEl) {
        taskEl = document.createElement('div');
        taskEl.id = `widget-task-${taskId}`;
        taskEl.className = 'widget-task-item';
        widgetTasks.appendChild(taskEl);
    }

    const stageInfo = {
        'waiting': { icon: '⏳', text: '대기 중', class: 'waiting' },
        'thinking': { icon: '🤔', text: 'PM이 분석 중', class: 'thinking' },
        'responding': { icon: '✍️', text: 'PM 응답 중', class: 'responding' },
        'delegating': { icon: '🚀', text: '에이전트 위임 중', class: 'delegating' },
        'calling': { icon: '📞', text: '에이전트 호출 중', class: 'executing' },
        'sub_agent_done': { icon: '✅', text: '에이전트 완료', class: 'sub-done' },
        'summarizing': { icon: '📝', text: 'PM 결과 종합 중', class: 'thinking' },
        'final_response': { icon: '✨', text: 'PM 최종 응답 중', class: 'responding' },
        'executing': { icon: '⚡', text: '명령 실행 중', class: 'executing' },
        'analyzing': { icon: '🔍', text: '결과 분석 중', class: 'thinking' },
        'finalizing': { icon: '📝', text: '마무리 중', class: 'responding' },
        'completed': { icon: '✅', text: '완료!', class: 'completed' },
        'failed': { icon: '❌', text: '실패', class: 'failed' }
    };

    const stage = taskData.stage || 'thinking';
    const info = stageInfo[stage] || stageInfo['thinking'];
    const progress = taskData.progress || 0;
    const message = taskData.message || '작업 처리 중...';
    const elapsedTime = taskData.startedAt
        ? Math.floor((Date.now() - new Date(taskData.startedAt).getTime()) / 1000)
        : 0;

    // 하위 에이전트 정보 표시
    let stageDisplayText = info.text;
    if (taskData.sub_agent) {
        stageDisplayText = `${taskData.sub_agent.toUpperCase()} ${stage === 'calling' ? '작업 중' : '완료'}`;
    }

    // 전체 에이전트 진행 상황 표시
    let agentProgress = '';
    if (taskData.total_agents && taskData.total_agents > 1) {
        agentProgress = ` (${taskData.progress_count || 1}/${taskData.total_agents})`;
    }

    taskEl.className = `widget-task-item ${info.class}`;
    taskEl.innerHTML = `
        <div class="widget-task-icon ${stage !== 'completed' && stage !== 'failed' ? 'spinning' : ''}">
            ${info.icon}
        </div>
        <div class="widget-task-info">
            <div class="widget-task-title">${escapeHtml(message.slice(0, 40))}${message.length > 40 ? '...' : ''}</div>
            <div class="widget-task-stage">
                <span class="widget-task-stage-text">${stageDisplayText}${agentProgress}</span>
            </div>
            <div class="widget-progress">
                <div class="widget-progress-fill" style="width: ${progress}%"></div>
            </div>
            ${elapsedTime > 0 ? `<div class="widget-task-time">경과: ${formatElapsedTime(elapsedTime)}</div>` : ''}
        </div>
        <button class="widget-task-cancel" onclick="removeWidgetTask('${taskId}')" title="${stage === 'completed' || stage === 'failed' ? '닫기' : '취소'}">✕</button>
    `;
}

// 경과 시간 포맷
function formatElapsedTime(seconds) {
    if (seconds < 60) return `${seconds}초`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}분 ${secs}초`;
}

// 위젯에서 작업 제거
function removeWidgetTask(taskId) {
    const taskEl = document.getElementById(`widget-task-${taskId}`);
    if (taskEl) {
        taskEl.style.opacity = '0';
        taskEl.style.transform = 'translateX(20px)';
        setTimeout(() => {
            taskEl.remove();
            // 모든 작업이 완료되면 위젯 숨김
            if (widgetTasks && widgetTasks.children.length === 0) {
                setTimeout(hideTasksWidget, 1000);
            }
        }, 300);
    }
}

// 위젯에서 작업 취소
async function cancelWidgetTask(taskId) {
    await cancelBackgroundTask(taskId);
    removeWidgetTask(taskId);
}

// 일반 채팅에서도 위젯 표시 (스트리밍 중)
function showStreamingInWidget(message) {
    const streamTaskId = 'streaming-current';
    updateWidgetTask(streamTaskId, {
        message: message,
        stage: 'thinking',
        progress: 10,
        startedAt: new Date().toISOString()
    });
    return streamTaskId;
}

// 스트리밍 단계 업데이트
function updateStreamingStage(taskId, stage, progress) {
    updateWidgetTask(taskId, {
        message: activeBackgroundTasks[taskId]?.message || '처리 중...',
        stage: stage,
        progress: progress,
        startedAt: activeBackgroundTasks[taskId]?.startedAt
    });
}

// 스트리밍 완료
function completeStreamingInWidget(taskId) {
    updateWidgetTask(taskId, {
        message: '완료!',
        stage: 'completed',
        progress: 100
    });
    // 15초 후 자동으로 위젯 제거
    setTimeout(() => removeWidgetTask(taskId), 15000);
}


// =============================================================================
// Fact Check Warning - 거짓말/환각 탐지 경고
// =============================================================================

function showFactCheckWarning(factCheck) {
    const { warning, hallucinations, confidence } = factCheck;

    // 경고 배너 생성
    const warningBanner = document.createElement('div');
    warningBanner.className = 'fact-check-warning';
    warningBanner.innerHTML = `
        <div class="fact-check-header">
            <span class="fact-check-icon">⚠️</span>
            <span class="fact-check-title">팩트체크 경고</span>
            <span class="fact-check-confidence">신뢰도: ${Math.round(confidence * 100)}%</span>
            <button class="fact-check-close" onclick="this.parentElement.parentElement.remove()">✕</button>
        </div>
        <div class="fact-check-content">
            ${hallucinations.map(h => `
                <div class="hallucination-item ${h.severity || 'medium'}">
                    <span class="hallucination-type">${getHallucinationTypeLabel(h.type)}</span>
                    <span class="hallucination-claim">"${(h.claim || '').substring(0, 100)}..."</span>
                    ${h.reason ? `<span class="hallucination-reason">${h.reason}</span>` : ''}
                </div>
            `).join('')}
        </div>
        <div class="fact-check-footer">
            <small>PM이 [EXEC] 태그 없이 실행/완료를 주장했습니다. 실제 검증이 필요합니다.</small>
        </div>
    `;

    // 마지막 메시지 박스 뒤에 삽입
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
        chatMessages.appendChild(warningBanner);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}

function getHallucinationTypeLabel(type) {
    const labels = {
        'test_executed': '🧪 테스트 실행 주장',
        'file_read': '📖 파일 확인 주장',
        'file_written': '📝 파일 생성/수정 주장',
        'command_executed': '⚡ 명령어 실행 주장',
        'feature_exists': '✨ 기능 존재 주장'
    };
    return labels[type] || type;
}


// =============================================================================
// Model Badge - 응답에 사용된 모델 정보 표시
// =============================================================================

/**
 * 메시지에 모델 정보 뱃지 추가
 * @param {HTMLElement} messageDiv - 메시지 DOM 요소
 * @param {Object} modelInfo - 모델 정보 {model_name, tier, reason, provider, latency_ms}
 */
function addModelBadge(messageDiv, modelInfo) {
    if (!messageDiv || !modelInfo) return;

    // 티어별 색상/아이콘 매핑
    const tierConfig = {
        'budget': { icon: '💰', color: '#4ade80', label: 'Budget' },
        'standard': { icon: '⚡', color: '#60a5fa', label: 'Standard' },
        'vip': { icon: '👑', color: '#f59e0b', label: 'VIP' },
        'research': { icon: '🔍', color: '#a78bfa', label: 'Research' },
        'mock': { icon: '🎭', color: '#9ca3af', label: 'Mock' }
    };

    const config = tierConfig[modelInfo.tier] || tierConfig['standard'];

    // 피드백 버튼 찾기
    const feedbackButtons = messageDiv.querySelector('.feedback-buttons');

    // 모델 뱃지 컨테이너 생성
    const badgeContainer = document.createElement('div');
    badgeContainer.className = 'model-badge-container';

    // 레이턴시 표시 (있는 경우)
    const latencyText = modelInfo.latency_ms
        ? ` · ${(modelInfo.latency_ms / 1000).toFixed(1)}s`
        : '';

    // CEO 프리픽스 표시 (있는 경우)
    const prefixBadge = modelInfo.ceo_prefix
        ? `<span class="ceo-prefix-badge">${modelInfo.ceo_prefix}</span>`
        : '';

    badgeContainer.innerHTML = `
        <div class="model-badge tier-${modelInfo.tier}" title="${modelInfo.reason}">
            <span class="model-icon">${config.icon}</span>
            <span class="model-name">${modelInfo.model_name}</span>
            <span class="model-tier">${config.label}</span>
            ${prefixBadge}
            <span class="model-latency">${latencyText}</span>
        </div>
    `;

    // 피드백 버튼이 있으면 그 앞에, 없으면 메시지 끝에 추가
    if (feedbackButtons) {
        messageDiv.insertBefore(badgeContainer, feedbackButtons);
    } else {
        messageDiv.appendChild(badgeContainer);
    }
}


// =============================================================================
// Admin Dropdown - 관리자 드롭다운 메뉴
// =============================================================================

const adminDropdown = document.querySelector('.admin-dropdown');
const adminDropdownBtn = document.getElementById('admin-dropdown-btn');

if (adminDropdownBtn && adminDropdown) {
    // 버튼 클릭 시 토글
    adminDropdownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        adminDropdown.classList.toggle('open');
    });

    // 외부 클릭 시 닫기
    document.addEventListener('click', (e) => {
        if (!adminDropdown.contains(e.target)) {
            adminDropdown.classList.remove('open');
        }
    });

    // ESC 키로 닫기
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            adminDropdown.classList.remove('open');
        }
    });
}

// =============================================================================
// 프로젝트 선택 강제 모달
// =============================================================================

function showProjectRequiredModal() {
    // 이미 모달이 있으면 제거
    const existingModal = document.getElementById('project-required-modal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.id = 'project-required-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal-content project-required-modal">
            <div class="modal-icon">⚠️</div>
            <h3>프로젝트를 선택해주세요</h3>
            <p>메시지를 보내려면 먼저 프로젝트를 선택해야 합니다.</p>
            <p class="modal-hint">프로젝트를 선택하면 PM이 해당 프로젝트의 파일을 읽고 수정할 수 있습니다.</p>
            <div class="modal-actions">
                <button class="btn-primary" id="modal-select-project">프로젝트 선택하기</button>
                <button class="btn-secondary" id="modal-close">닫기</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // 프로젝트 선택 버튼 - 드롭다운 포커스
    document.getElementById('modal-select-project').addEventListener('click', () => {
        modal.remove();
        projectSelect.focus();
        // 드롭다운 열기 (클릭 시뮬레이션)
        projectSelect.dispatchEvent(new MouseEvent('mousedown'));
    });

    // 닫기 버튼
    document.getElementById('modal-close').addEventListener('click', () => {
        modal.remove();
    });

    // 오버레이 클릭으로 닫기
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });

    // ESC로 닫기
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            modal.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

// 프로젝트 선택 상태 표시 업데이트
function updateProjectStatus() {
    const projectIndicator = document.querySelector('.project-status-indicator');
    if (!projectIndicator) {
        // 인디케이터 없으면 생성
        const indicator = document.createElement('div');
        indicator.className = 'project-status-indicator';
        const inputArea = document.querySelector('.chat-input-area');
        if (inputArea) {
            inputArea.insertBefore(indicator, inputArea.firstChild);
        }
    }

    const indicator = document.querySelector('.project-status-indicator');
    if (indicator) {
        if (currentProject) {
            indicator.innerHTML = `<span class="project-badge">📁 ${currentProject}</span>`;
            indicator.classList.remove('no-project');
        } else {
            indicator.innerHTML = `<span class="project-warning">⚠️ 프로젝트를 선택하세요</span>`;
            indicator.classList.add('no-project');
        }
    }
}

// 프로젝트 선택 시 상태 업데이트
projectSelect.addEventListener('change', async (e) => {
    await loadProjectFiles(e.target.value);
    updateProjectStatus();
});

// 초기 로드 시 상태 표시
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(updateProjectStatus, 500);  // 프로젝트 로드 후 실행

    // Jobs API 모드: 진행 중인 작업 복구 체크
    if (useJobsApi) {
        setTimeout(checkPendingJobs, 1000);
    }
});

// =============================================================================
// 페이지 로드 시 진행 중인 Job 복구
// =============================================================================
async function checkPendingJobs() {
    try {
        // 현재 세션의 진행 중인 작업 조회
        const response = await fetch(`/api/chat/jobs?status=processing`);
        const data = await response.json();

        if (data.jobs && data.jobs.length > 0) {
            const pendingJob = data.jobs[0];  // 가장 최근 작업
            console.log('[Jobs] Found pending job:', pendingJob.id);

            // 상태바에 복구 알림 표시
            showJobRecoveryBanner(pendingJob);
        }
    } catch (error) {
        console.error('[Jobs] Failed to check pending jobs:', error);
    }
}

// 진행 중인 Job 복구 배너 표시
function showJobRecoveryBanner(job) {
    // 기존 배너 제거
    const existingBanner = document.getElementById('job-recovery-banner');
    if (existingBanner) existingBanner.remove();

    const banner = document.createElement('div');
    banner.id = 'job-recovery-banner';
    banner.className = 'job-recovery-banner';
    banner.innerHTML = `
        <div class="recovery-content">
            <span class="recovery-icon">⏳</span>
            <span class="recovery-text">백그라운드 작업 진행 중 (${job.stage || 'processing'})</span>
            <button class="recovery-btn resume-btn" onclick="resumeJob('${job.id}')">결과 보기</button>
            <button class="recovery-btn dismiss-btn" onclick="dismissRecoveryBanner()">닫기</button>
        </div>
    `;

    // 헤더 아래에 삽입
    const header = document.querySelector('.chat-header');
    if (header) {
        header.parentNode.insertBefore(banner, header.nextSibling);
    } else {
        document.body.prepend(banner);
    }

    // 자동으로 폴링 시작
    currentJobId = job.id;
    startJobPolling(job.id, 'recovery-widget', 'pm');
}

// Job 결과 보기 (배너에서 클릭)
function resumeJob(jobId) {
    console.log('[Jobs] Resuming job:', jobId);
    dismissRecoveryBanner();

    // 위젯 표시 및 폴링 시작
    const widgetTaskId = showStreamingInWidget('이전 작업 결과 대기 중...');
    currentJobId = jobId;
    startJobPolling(jobId, widgetTaskId, 'pm');
}

// 복구 배너 닫기
function dismissRecoveryBanner() {
    const banner = document.getElementById('job-recovery-banner');
    if (banner) {
        banner.classList.add('fade-out');
        setTimeout(() => banner.remove(), 300);
    }
}

// ========================================
// Mobile Sidebar Toggle
// ========================================
const mobileMenuBtn = document.getElementById('mobile-menu-btn');
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');

function openMobileSidebar() {
    if (sidebar && sidebarOverlay) {
        sidebar.classList.add('open');
        sidebarOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';  // 배경 스크롤 방지
    }
}

function closeMobileSidebar() {
    if (sidebar && sidebarOverlay) {
        sidebar.classList.remove('open');
        sidebarOverlay.classList.remove('active');
        document.body.style.overflow = '';
    }
}

if (mobileMenuBtn) {
    mobileMenuBtn.addEventListener('click', openMobileSidebar);
}

if (sidebarOverlay) {
    sidebarOverlay.addEventListener('click', closeMobileSidebar);
}

// 세션 선택 시 모바일에서 사이드바 닫기 (이벤트 리스너에서 처리)


// =============================================================================
// SSE Progress Sync - Cross-device Progress Bar Synchronization
// =============================================================================

let progressEventSource = null;
let isLocalRequest = false;  // 현재 디바이스에서 요청 중인지

/**
 * SSE 연결 시작 (다른 디바이스의 진행 상태 수신)
 */
function connectProgressSSE() {
    // 이미 연결되어 있으면 무시
    if (progressEventSource && progressEventSource.readyState !== EventSource.CLOSED) {
        return;
    }

    // 세션 ID가 없으면 global로 구독
    const sessionParam = currentSessionId ? `?session_id=${currentSessionId}` : '?session_id=global';
    progressEventSource = new EventSource(`/api/events/progress${sessionParam}`);

    progressEventSource.onopen = () => {
        console.log('[SSE] Progress stream connected');
    };

    progressEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            // heartbeat 무시
            if (data.event_type === 'heartbeat') {
                return;
            }

            // 현재 디바이스에서 요청 중이면 SSE 이벤트 무시 (중복 방지)
            if (isLocalRequest && data.event_type !== 'complete') {
                return;
            }

            console.log('[SSE] Progress event:', data.event_type, data.stage);

            // 이벤트 타입별 처리
            switch (data.event_type) {
                case 'progress':
                case 'stage_change':
                    showRemoteProgress(data);
                    break;
                case 'complete':
                    hideRemoteProgress();
                    break;
                case 'error':
                    showRemoteError(data.message);
                    break;
            }
        } catch (e) {
            console.error('[SSE] Parse error:', e);
        }
    };

    progressEventSource.onerror = (error) => {
        console.error('[SSE] Connection error:', error);
        // 5초 후 재연결 시도
        setTimeout(() => {
            if (progressEventSource) {
                progressEventSource.close();
            }
            connectProgressSSE();
        }, 5000);
    };
}

/**
 * SSE 연결 종료
 */
function disconnectProgressSSE() {
    if (progressEventSource) {
        progressEventSource.close();
        progressEventSource = null;
        console.log('[SSE] Progress stream disconnected');
    }
}

/**
 * 다른 디바이스의 진행 상태 표시
 */
function showRemoteProgress(data) {
    const processingBar = document.getElementById('processing-bar');
    if (!processingBar) return;

    // 프로그레스바 표시
    processingBar.classList.remove('hidden');

    // 단계별 텍스트 매핑
    const stageInfo = {
        'thinking': { icon: '🤔', text: 'PM이 생각 중' },
        'responding': { icon: '✍️', text: 'PM 응답 중' },
        'delegating': { icon: '🚀', text: '에이전트 위임 중' },
        'calling': { icon: '📞', text: '에이전트 호출 중' },
        'sub_agent_done': { icon: '✅', text: '에이전트 완료' },
        'summarizing': { icon: '📝', text: 'PM이 결과 종합 중' },
        'final_response': { icon: '✨', text: 'PM 최종 응답 중' },
        'idle': { icon: '⏸️', text: '대기 중' }
    };

    const info = stageInfo[data.stage] || stageInfo['thinking'];

    // 프로그레스바 업데이트
    const processingIcon = processingBar.querySelector('.processing-icon');
    const processingText = processingBar.querySelector('.processing-text');
    const processingStage = document.getElementById('processing-stage');

    if (processingIcon) {
        processingIcon.textContent = info.icon;
    }

    if (processingText) {
        let displayText = info.text;
        // 하위 에이전트 정보 포함
        if (data.sub_agent && (data.stage === 'calling' || data.stage === 'sub_agent_done')) {
            displayText = `${data.sub_agent.toUpperCase()} ${data.stage === 'calling' ? '작업 중' : '완료'}`;
        }
        const dotsHtml = '<span class="processing-dots"><span></span><span></span><span></span></span>';
        processingText.innerHTML = `${displayText}${dotsHtml}`;
    }

    if (processingStage) {
        let stageDisplay = data.stage.toUpperCase().replace('_', ' ');
        if (data.sub_agent) {
            stageDisplay = `${data.sub_agent.toUpperCase()} → ${stageDisplay}`;
        }
        processingStage.textContent = stageDisplay;
    }

    // 상태 dot 업데이트
    const statusDot = document.querySelector('.status-dot');
    if (statusDot) {
        statusDot.classList.add('loading');
    }

    // 원격 표시 배지 (다른 디바이스에서 실행 중임을 표시)
    if (!processingBar.querySelector('.remote-badge')) {
        const remoteBadge = document.createElement('span');
        remoteBadge.className = 'remote-badge';
        remoteBadge.textContent = '📱 다른 기기';
        remoteBadge.title = '다른 기기에서 작업이 진행 중입니다';
        processingBar.appendChild(remoteBadge);
    }
}

/**
 * 원격 진행 상태 숨기기
 */
function hideRemoteProgress() {
    const processingBar = document.getElementById('processing-bar');
    if (!processingBar) return;

    // 프로그레스바 숨기기
    processingBar.classList.add('hidden');

    // 원격 배지 제거
    const remoteBadge = processingBar.querySelector('.remote-badge');
    if (remoteBadge) {
        remoteBadge.remove();
    }

    // 상태 dot 업데이트
    const statusDot = document.querySelector('.status-dot');
    if (statusDot) {
        statusDot.classList.remove('loading');
    }

    // 세션 목록 새로고침 (새 메시지가 추가되었을 수 있음)
    loadSessions();
}

/**
 * 원격 에러 표시
 */
function showRemoteError(message) {
    console.error('[SSE] Remote error:', message);
    hideRemoteProgress();
}

/**
 * 세션 변경 시 SSE 재연결
 */
function reconnectProgressSSE() {
    disconnectProgressSSE();
    setTimeout(connectProgressSSE, 100);
}

// 페이지 로드 시 SSE 연결
document.addEventListener('DOMContentLoaded', () => {
    // 약간의 딜레이 후 SSE 연결 (세션 ID 로드 후)
    setTimeout(connectProgressSSE, 1000);
});

// 페이지 종료 시 SSE 연결 해제
window.addEventListener('beforeunload', () => {
    disconnectProgressSSE();
});

// 가시성 변경 시 SSE 재연결 (탭 전환 등)
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        // 탭이 다시 활성화되면 재연결
        reconnectProgressSSE();
    }
});

// =============================================================================
// Mode Selector - 일반/논의/코딩 모드 전환 (v2.6.4)
// =============================================================================

// 모드 버튼 이벤트 리스너 등록
function initializeModeButtons() {
    const modeButtons = document.querySelectorAll('.mode-btn');

    modeButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            // 모든 버튼에서 active 클래스 제거
            modeButtons.forEach(b => b.classList.remove('active'));

            // 클릭한 버튼에 active 클래스 추가
            this.classList.add('active');

            // 현재 모드 업데이트
            currentMode = this.dataset.mode;

            console.log('[Mode] Switched to:', currentMode);

            // 모드 변경 피드백 (선택사항)
            showModeChangeNotification(currentMode);
        });
    });
}

// 모드 변경 알림 표시 (선택사항)
function showModeChangeNotification(mode) {
    const modeLabels = {
        'normal': '💬 일반 모드',
        'discuss': '🧠 논의 모드',
        'code': '💻 코딩 모드'
    };

    const label = modeLabels[mode] || mode;

    // 임시 알림 배너 표시
    const notification = document.createElement('div');
    notification.className = 'mode-change-notification';
    notification.textContent = `${label}로 전환되었습니다`;
    notification.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        background: rgba(37, 99, 235, 0.9);
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        z-index: 10000;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        animation: slideInRight 0.3s ease-out;
    `;

    document.body.appendChild(notification);

    // 2초 후 자동 제거
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(20px)';
        notification.style.transition = 'all 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 2000);
}

// 페이지 로드 시 모드 버튼 초기화
document.addEventListener('DOMContentLoaded', () => {
    initializeModeButtons();
});
