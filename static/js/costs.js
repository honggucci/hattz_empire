/**
 * Hattz Empire - Cost Dashboard JavaScript
 * 비용 대시보드 기능
 */

// 현재 선택된 기간 (일)
let currentPeriod = 30;

/**
 * 초기화
 */
document.addEventListener('DOMContentLoaded', () => {
    initPeriodButtons();
    loadAllData();
});

/**
 * 기간 버튼 이벤트 초기화
 */
function initPeriodButtons() {
    const buttons = document.querySelectorAll('.period-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentPeriod = parseInt(btn.dataset.days);
            loadAllData();
        });
    });
}

/**
 * 모든 데이터 로드
 */
async function loadAllData() {
    try {
        const response = await fetch(`/costs/all?days=${currentPeriod}`);
        const data = await response.json();

        renderSummaryCards(data.summary);
        renderDailyChart(data.daily);
        renderTierChart(data.tiers);
        renderModelStats(data.models);
        renderAgentStats(data.agents);
        renderEfficiencyMetrics(data.efficiency);
    } catch (error) {
        console.error('Failed to load cost data:', error);
        showError();
    }
}

/**
 * 숫자 포맷팅
 */
function formatCost(cost) {
    if (cost >= 1) {
        return `$${cost.toFixed(2)}`;
    } else if (cost >= 0.01) {
        return `$${cost.toFixed(3)}`;
    } else {
        return `$${cost.toFixed(4)}`;
    }
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toLocaleString();
}

/**
 * 요약 카드 렌더링
 */
function renderSummaryCards(summary) {
    const container = document.getElementById('summary-cards');

    if (!summary) {
        container.innerHTML = '<div class="summary-card"><div class="label">데이터 없음</div></div>';
        return;
    }

    const changeHtml = (change, inverse = false) => {
        if (change === null || change === undefined) return '';
        const isUp = change > 0;
        const className = inverse ? (isUp ? 'down' : 'up') : (isUp ? 'up' : 'down');
        const arrow = isUp ? '↑' : '↓';
        return `<div class="change ${className}">${arrow} ${Math.abs(change).toFixed(1)}%</div>`;
    };

    container.innerHTML = `
        <div class="summary-card">
            <div class="label">총 비용 (${currentPeriod}일)</div>
            <div class="value cost">${formatCost(summary.total_cost || 0)}</div>
            <div class="sub">${formatNumber(summary.total_calls || 0)} API 호출</div>
        </div>
        <div class="summary-card">
            <div class="label">일 평균 비용</div>
            <div class="value">${formatCost(summary.daily_average || 0)}</div>
            ${changeHtml(summary.cost_change)}
        </div>
        <div class="summary-card">
            <div class="label">월간 예상</div>
            <div class="value">${formatCost(summary.monthly_estimate || 0)}</div>
            <div class="sub">현재 추세 기준</div>
        </div>
        <div class="summary-card">
            <div class="label">평균 호출 비용</div>
            <div class="value">${formatCost(summary.avg_cost_per_call || 0)}</div>
            <div class="sub">호출당</div>
        </div>
    `;
}

/**
 * 일별 차트 렌더링
 */
function renderDailyChart(dailyData) {
    const container = document.getElementById('daily-chart-container');

    if (!dailyData || dailyData.length === 0) {
        container.innerHTML = '<div class="loading">데이터 없음</div>';
        return;
    }

    // 최대값 계산
    const maxCost = Math.max(...dailyData.map(d => d.cost || 0), 0.01);

    // 최근 N일만 표시 (최대 14일)
    const displayData = dailyData.slice(-14);

    const barsHtml = displayData.map(d => {
        const height = Math.max((d.cost / maxCost) * 100, 5);
        const date = new Date(d.date);
        const dayLabel = `${date.getMonth() + 1}/${date.getDate()}`;
        return `<div class="daily-bar" style="height: ${height}%" data-value="${formatCost(d.cost)}"></div>`;
    }).join('');

    const labelsHtml = displayData.map(d => {
        const date = new Date(d.date);
        return `<span>${date.getMonth() + 1}/${date.getDate()}</span>`;
    }).join('');

    container.innerHTML = `
        <div class="daily-chart">${barsHtml}</div>
        <div class="daily-labels">${labelsHtml}</div>
    `;
}

/**
 * 티어 분포 차트 렌더링
 */
function renderTierChart(tierData) {
    const container = document.getElementById('tier-chart-container');

    if (!tierData || Object.keys(tierData).length === 0) {
        container.innerHTML = '<div class="loading">데이터 없음</div>';
        return;
    }

    const tierColors = {
        'budget': { class: 'budget', label: 'Budget', color: 'var(--accent-green)' },
        'standard': { class: 'standard', label: 'Standard', color: 'var(--accent-blue)' },
        'premium': { class: 'premium', label: 'Premium', color: 'var(--accent-purple)' },
        'thinking': { class: 'thinking', label: 'Thinking', color: 'var(--accent-yellow)' },
        'research': { class: 'research', label: 'Research', color: 'var(--accent-red)' }
    };

    const total = Object.values(tierData).reduce((sum, t) => sum + (t.calls || 0), 0);

    if (total === 0) {
        container.innerHTML = '<div class="loading">호출 데이터 없음</div>';
        return;
    }

    // 티어 바 생성
    const segments = Object.entries(tierData)
        .filter(([_, data]) => data.calls > 0)
        .map(([tier, data]) => {
            const percentage = (data.calls / total) * 100;
            const config = tierColors[tier] || { class: tier, label: tier, color: 'var(--text-secondary)' };
            return `<div class="tier-segment ${config.class}" style="flex: ${percentage}">${percentage.toFixed(0)}%</div>`;
        }).join('');

    // 레전드 생성
    const legendItems = Object.entries(tierData)
        .filter(([_, data]) => data.calls > 0)
        .map(([tier, data]) => {
            const config = tierColors[tier] || { class: tier, label: tier, color: 'var(--text-secondary)' };
            return `
                <div class="tier-legend-item">
                    <div class="tier-legend-dot" style="background: ${config.color}"></div>
                    <span>${config.label}: ${formatNumber(data.calls)}회 (${formatCost(data.cost)})</span>
                </div>
            `;
        }).join('');

    container.innerHTML = `
        <div class="tier-chart">${segments}</div>
        <div class="tier-legend">${legendItems}</div>
    `;
}

/**
 * 모델 통계 렌더링
 */
function renderModelStats(modelData) {
    const container = document.getElementById('model-stats-container');

    if (!modelData || !modelData.models || modelData.models.length === 0) {
        container.innerHTML = '<div class="loading">데이터 없음</div>';
        return;
    }

    // 쏠림 현상 경고
    let warningHtml = '';
    if (modelData.concentration_warning) {
        const severity = modelData.concentration_index > 0.6 ? '' : 'warning';
        warningHtml = `
            <div class="concentration-alert ${severity}">
                <span>⚠️</span>
                <span>모델 사용 집중도: ${(modelData.concentration_index * 100).toFixed(1)}% -
                특정 모델에 호출이 집중되고 있습니다. 다양한 모델 활용을 권장합니다.</span>
            </div>
        `;
    }

    const tierClasses = {
        'budget': 'budget',
        'standard': 'standard',
        'premium': 'premium',
        'thinking': 'thinking',
        'research': 'research'
    };

    const maxCalls = Math.max(...modelData.models.map(m => m.calls || 0), 1);

    const modelsHtml = modelData.models.slice(0, 10).map(model => {
        const barWidth = (model.calls / maxCalls) * 100;
        const tierClass = tierClasses[model.tier] || '';
        const percentage = ((model.calls / modelData.total_calls) * 100).toFixed(1);

        // 모델명 단축
        const shortName = model.model.replace('claude-', '').replace('gemini-', 'gem-').replace('-20250514', '');

        return `
            <div class="model-item">
                <div class="info">
                    <div class="name" title="${model.model}">${shortName}</div>
                    <span class="tier ${tierClass}">${model.tier}</span>
                </div>
                <div class="bar-container">
                    <div class="bar" style="width: ${barWidth}%"></div>
                </div>
                <div class="stats">
                    <div class="calls">${formatNumber(model.calls)}</div>
                    <div class="percentage">${percentage}%</div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = `
        ${warningHtml}
        <div class="model-list">${modelsHtml}</div>
    `;
}

/**
 * 에이전트 통계 렌더링
 */
function renderAgentStats(agentData) {
    const container = document.getElementById('agent-stats-container');

    if (!agentData || Object.keys(agentData).length === 0) {
        container.innerHTML = '<div class="loading">데이터 없음</div>';
        return;
    }

    const agentIcons = {
        'orchestrator': '🎯',
        'researcher': '🔍',
        'analyst': '📊',
        'writer': '✍️',
        'critic': '🎭',
        'executor': '⚡',
        'advisor': '💡',
        'default': '🤖'
    };

    const agentsHtml = Object.entries(agentData).map(([agent, data]) => {
        const icon = agentIcons[agent.toLowerCase()] || agentIcons['default'];
        return `
            <div class="agent-card">
                <div class="role">${icon}</div>
                <div class="name">${agent}</div>
                <div class="cost">${formatCost(data.cost || 0)}</div>
                <div class="calls">${formatNumber(data.calls || 0)} 호출</div>
            </div>
        `;
    }).join('');

    container.innerHTML = `<div class="agent-grid">${agentsHtml}</div>`;
}

/**
 * 효율성 지표 렌더링
 */
function renderEfficiencyMetrics(efficiency) {
    const container = document.getElementById('efficiency-container');

    if (!efficiency) {
        container.innerHTML = '<div class="loading">데이터 없음</div>';
        return;
    }

    const budgetRatio = efficiency.budget_tier_ratio || 0;
    const monthlyEstimate = efficiency.monthly_estimate || 0;

    // 티어별 효율성
    const tierEfficiency = efficiency.tier_efficiency || {};

    let tierMetricsHtml = '';
    Object.entries(tierEfficiency).forEach(([tier, data]) => {
        if (data.calls > 0) {
            tierMetricsHtml += `
                <div class="efficiency-item">
                    <div class="metric-label">${tier.toUpperCase()} 평균 비용</div>
                    <div class="metric-value">${formatCost(data.avg_cost)}</div>
                    <div class="metric-sub">${formatNumber(data.calls)} 호출</div>
                </div>
            `;
        }
    });

    container.innerHTML = `
        <div class="efficiency-grid">
            <div class="efficiency-item">
                <div class="metric-label">Budget 티어 비율</div>
                <div class="metric-value">${(budgetRatio * 100).toFixed(1)}%</div>
                <div class="metric-sub">저비용 모델 활용도</div>
            </div>
            <div class="efficiency-item">
                <div class="metric-label">월간 비용 예상</div>
                <div class="metric-value">${formatCost(monthlyEstimate)}</div>
                <div class="metric-sub">현재 사용 패턴 기준</div>
            </div>
            ${tierMetricsHtml}
        </div>
    `;
}

/**
 * 에러 표시
 */
function showError() {
    const containers = [
        'summary-cards',
        'daily-chart-container',
        'tier-chart-container',
        'model-stats-container',
        'agent-stats-container',
        'efficiency-container'
    ];

    containers.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.innerHTML = '<div class="loading" style="color: var(--accent-red);">데이터 로드 실패</div>';
        }
    });
}
