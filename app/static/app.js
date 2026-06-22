/* ============================================================
   AI Email Agent — app.js
   Handles: status polling, inbox, reply logs, tabs, modal
   ============================================================ */

// ── Avatar color palette ──────────────────────────────────────
const AVATAR_COLORS = [
    '#5b6ef5', '#22c98b', '#f59e2c', '#f05a5a', '#3bbdf7',
    '#a855f7', '#ec4899', '#14b8a6', '#f97316', '#6366f1'
];

function getAvatarColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function getInitials(name, email) {
    const src = name && name.trim() ? name : email;
    const parts = src.trim().split(/[\s@.]+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return src.slice(0, 2).toUpperCase();
}

// ── Time helpers ─────────────────────────────────────────────
function formatRelativeTime(isoStr) {
    if (!isoStr) return '—';
    const date = new Date(isoStr);
    if (isNaN(date)) return isoStr;
    const diff = (Date.now() - date.getTime()) / 1000;
    if (diff < 60)  return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatDateTime(isoStr) {
    if (!isoStr) return '—';
    const date = new Date(isoStr);
    if (isNaN(date)) return isoStr;
    return date.toLocaleString([], {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

// ── State ─────────────────────────────────────────────────────
let currentTab = 'inbox';
let isConnected = false;

// ── DOM refs ──────────────────────────────────────────────────
const els = {};

document.addEventListener('DOMContentLoaded', () => {
    els.liveDot    = document.getElementById('live-dot');
    els.liveLabel  = document.getElementById('live-label');
    els.pending    = document.getElementById('pending-count');
    els.captured   = document.getElementById('captured-count');
    els.sent       = document.getElementById('sent-count');
    els.toggle     = document.getElementById('service-toggle');
    els.toggleWrap = document.getElementById('toggle-wrap');
    els.toggleLbl  = document.getElementById('toggle-label');
    els.ctrlDesc   = document.getElementById('control-desc');
    els.inboxPill  = document.getElementById('inbox-pill');
    els.repliesPill= document.getElementById('replies-pill');
    els.inboxList  = document.getElementById('inbox-list');
    els.logsList   = document.getElementById('logs-list');
    els.lastUpdate = document.getElementById('last-updated');
    els.queuePanel = document.getElementById('queue-panel');
    els.queueList  = document.getElementById('queue-list');
    els.queueCount = document.getElementById('queue-count');
    els.toastContainer = document.getElementById('toast-container');
    els.workersGrid = document.getElementById('workers-grid');

    // Toggle service
    els.toggle.addEventListener('change', handleToggle);

    // Keyboard support for toggle wrap
    els.toggleWrap.addEventListener('keydown', (e) => {
        if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            els.toggle.click();
        }
    });

    // Initial load
    fetchStatus();
    fetchInbox();
    fetchLogs();

    // Poll every 30 seconds
    setInterval(() => {
        fetchStatus();
        fetchInbox();
        fetchLogs();
    }, 30000);
});

// ── Tab Switching ─────────────────────────────────────────────
window.switchTab = function(tab) {
    currentTab = tab;
    document.getElementById('panel-inbox').classList.toggle('panel--hidden', tab !== 'inbox');
    document.getElementById('panel-replies').classList.toggle('panel--hidden', tab !== 'replies');
    document.getElementById('tab-inbox').classList.toggle('tab-btn--active', tab === 'inbox');
    document.getElementById('tab-replies').classList.toggle('tab-btn--active', tab === 'replies');
    document.getElementById('tab-inbox').setAttribute('aria-selected', tab === 'inbox');
    document.getElementById('tab-replies').setAttribute('aria-selected', tab === 'replies');
};

// ── Status Fetch ──────────────────────────────────────────────
async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Connection indicator
        setConnected(true);

        // Update brand name/email dynamically if returned
        if (data.user_name) {
            const brandNameEl = document.querySelector('.brand-name');
            if (brandNameEl) brandNameEl.textContent = `${data.user_name}'s AI Agent`;
        }
        if (data.user_email) {
            const brandSubEl = document.querySelector('.brand-sub');
            if (brandSubEl) brandSubEl.textContent = data.user_email;
        }

        // Counts
        animateNumber(els.pending,  data.pending_emails  ?? 0);
        animateNumber(els.captured, data.captured_emails ?? 0);
        animateNumber(els.sent,     data.sent_emails     ?? 0);

        // Toggle state (don't fire event)
        const isOn = data.service_on;
        els.toggle.checked = isOn;
        updateToggleUI(isOn);

        // Update queue and workers status
        updateQueueUI(data.queue || [], data.workers || [], data.service_on);

        // Timestamp
        els.lastUpdate.textContent = 'Updated ' + formatRelativeTime(new Date().toISOString());

    } catch (err) {
        setConnected(false);
        console.error('[Status] Failed:', err);
    }
}

// ── Toggle Service ────────────────────────────────────────────
async function handleToggle(e) {
    const isTurnedOn = e.target.checked;
    updateToggleUI(isTurnedOn);

    try {
        const res = await fetch('/api/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ service_on: isTurnedOn })
        });
        const data = await res.json();
        updateToggleUI(data.service_on);
    } catch (err) {
        // Revert on error
        els.toggle.checked = !isTurnedOn;
        updateToggleUI(!isTurnedOn);
        console.error('[Toggle] Failed:', err);
    }
}

function updateToggleUI(isOn) {
    els.toggleLbl.textContent = isOn ? 'ON' : 'OFF';
    els.toggleLbl.className = 'toggle-label' + (isOn ? ' on' : '');
    els.toggleWrap.setAttribute('aria-checked', String(isOn));
    els.ctrlDesc.textContent = isOn
        ? '✅ Agent is running. Auto-replies will be sent when new emails arrive.'
        : 'Service is paused. Toggle ON to start auto-replying to incoming emails.';
}

// ── Inbox Fetch ───────────────────────────────────────────────
let _searchTimer = null;

window.onInboxSearch = function(value) {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => fetchInbox(value), 300);
};

window.fetchInbox = async function(search = '') {
    try {
        const url = search ? `/api/inbox?search=${encodeURIComponent(search)}` : '/api/inbox';
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const emails = data.emails || [];

        // Update pill
        els.inboxPill.textContent = emails.length;

        if (emails.length === 0) {
            els.inboxList.innerHTML = emptyState(
                'No emails captured yet',
                'Emails will appear here once the agent detects them in your inbox.'
            );
            return;
        }

        els.inboxList.innerHTML = emails.map(email => buildInboxItem(email)).join('');

    } catch (err) {
        els.inboxList.innerHTML = errorState('Could not load inbox. Is the server running?');
        console.error('[Inbox] Failed:', err);
    }
};

function buildInboxItem(email) {
    const initials = getInitials(email.sender_name, email.sender);
    const color = getAvatarColor(email.sender);
    const time = formatRelativeTime(email.captured_at);
    const displayName = email.sender_name || email.sender;
    const snippet = email.snippet ? escHtml(email.snippet.slice(0, 90)) : '(No preview)';
    const statusClass = email.is_replied ? 'email-status--replied' : 'email-status--pending';
    const statusText  = email.is_replied ? '✓ Replied' : '⏳ Pending';

    return `
    <div class="email-item" onclick="openInboxModal(${JSON.stringify(email).replace(/"/g, '&quot;')})" 
         role="button" tabindex="0" aria-label="Email from ${escHtml(displayName)}">
        <div class="email-avatar" style="background:${color};">${escHtml(initials)}</div>
        <div class="email-body">
            <div class="email-subject">${escHtml(email.subject || '(No Subject)')}</div>
            <div class="email-from">
                <strong>${escHtml(displayName)}</strong>
                ${email.sender_name ? `<span style="color:var(--text-muted);">&lt;${escHtml(email.sender)}&gt;</span>` : ''}
            </div>
            <div class="email-snippet">${snippet}</div>
        </div>
        <div class="email-meta">
            <span class="email-time">${time}</span>
            <span class="email-status ${statusClass}">${statusText}</span>
        </div>
    </div>`;
}

// ── Reply Logs Fetch ──────────────────────────────────────────
let seenRepliedIds = null;

window.fetchLogs = async function() {
    try {
        const res = await fetch('/api/logs');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const logs = data.logs || [];

        // Update pill
        els.repliesPill.textContent = logs.length;

        // Process logs for toast notification
        if (seenRepliedIds === null) {
            seenRepliedIds = new Set(logs.map(log => log.message_id || log.id));
        } else {
            logs.forEach(log => {
                const logId = log.message_id || log.id;
                if (!seenRepliedIds.has(logId)) {
                    seenRepliedIds.add(logId);
                    showToast('Auto-Reply Sent', `Replied to: ${log.sender}`);
                }
            });
        }

        if (logs.length === 0) {
            els.logsList.innerHTML = emptyState(
                'No replies sent yet',
                'AI replies will appear here after the agent processes emails.'
            );
            return;
        }

        els.logsList.innerHTML = logs.map(log => buildLogItem(log)).join('');

    } catch (err) {
        els.logsList.innerHTML = errorState('Could not load reply history.');
        console.error('[Logs] Failed:', err);
    }
};

function buildLogItem(log) {
    const initials = getInitials('', log.sender);
    const color = getAvatarColor(log.sender);
    const time = formatRelativeTime(log.timestamp);
    const preview = log.reply_body ? escHtml(log.reply_body.slice(0, 80)) + '…' : '—';

    return `
    <div class="email-item email-item--reply" onclick="openReplyModal(${JSON.stringify(log).replace(/"/g, '&quot;')})"
         role="button" tabindex="0" aria-label="Reply to ${escHtml(log.sender)}">
        <div class="email-avatar" style="background:${color};">${escHtml(initials)}</div>
        <div class="email-body">
            <div class="email-subject">${escHtml(log.subject || '(No Subject)')}</div>
            <div class="email-from"><strong>${escHtml(log.sender)}</strong></div>
            <div class="email-snippet">${preview}</div>
        </div>
        <div class="email-meta">
            <span class="email-time">${time}</span>
            <span class="email-status email-status--replied">✓ Sent</span>
        </div>
    </div>`;
}

// ── Modal ─────────────────────────────────────────────────────
window.openInboxModal = function(emailObj) {
    let email;
    try { email = typeof emailObj === 'string' ? JSON.parse(emailObj) : emailObj; }
    catch { return; }

    const displayName = email.sender_name || email.sender;
    document.getElementById('modal-title').textContent = email.subject || '(No Subject)';
    document.getElementById('modal-meta').innerHTML = `
        <div><strong>From:</strong> ${escHtml(displayName)} &lt;${escHtml(email.sender)}&gt;</div>
        <div><strong>Captured:</strong> ${formatDateTime(email.captured_at)}</div>
        <div><strong>Status:</strong> ${email.is_replied ? '✅ Auto-replied' : '⏳ Awaiting reply'}</div>
    `;
    document.getElementById('modal-body').textContent =
        email.snippet || 'No preview available. Full body is fetched by the agent at reply time.';
    openModal();
};

window.openReplyModal = function(logObj) {
    let log;
    try { log = typeof logObj === 'string' ? JSON.parse(logObj) : logObj; }
    catch { return; }

    document.getElementById('modal-title').textContent = 'AI Reply — ' + (log.subject || '(No Subject)');
    document.getElementById('modal-meta').innerHTML = `
        <div><strong>To:</strong> ${escHtml(log.sender)}</div>
        <div><strong>Subject:</strong> ${escHtml(log.subject || '—')}</div>
        <div><strong>Sent at:</strong> ${formatDateTime(log.timestamp)}</div>
    `;
    document.getElementById('modal-body').textContent = log.reply_body || '(No body)';
    openModal();
};

function openModal() {
    document.getElementById('modal-overlay').classList.add('open');
    document.body.style.overflow = 'hidden';
}

window.closeModal = function() {
    document.getElementById('modal-overlay').classList.remove('open');
    document.body.style.overflow = '';
};

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ── Connection Indicator ──────────────────────────────────────
function setConnected(ok) {
    isConnected = ok;
    els.liveDot.className = 'live-dot ' + (ok ? 'connected' : 'error');
    els.liveLabel.textContent = ok ? 'Connected' : 'Disconnected';
}

// ── Animated number counter ───────────────────────────────────
function animateNumber(el, target) {
    const current = parseInt(el.textContent) || 0;
    if (current === target || el.textContent === '—') {
        el.textContent = target;
        return;
    }
    const step = target > current ? 1 : -1;
    const diff = Math.abs(target - current);
    const delay = diff <= 5 ? 80 : diff <= 20 ? 40 : 20;
    let val = current;
    const timer = setInterval(() => {
        val += step;
        el.textContent = val;
        if (val === target) clearInterval(timer);
    }, delay);
}

// ── Helpers ───────────────────────────────────────────────────
function escHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function emptyState(title, sub) {
    return `
    <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
            <polyline points="22,6 12,13 2,6"/>
        </svg>
        <p>${escHtml(title)}</p>
        <span>${escHtml(sub)}</span>
    </div>`;
}

function errorState(msg) {
    return `
    <div class="empty-state">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <p style="color:var(--danger)">${escHtml(msg)}</p>
    </div>`;
}

// ── Queue UI and Toast Notifications ──
function updateQueueUI(queue, workers, serviceOn) {
    if (!els.queuePanel || !els.queueList || !els.queueCount || !els.workersGrid) return;
    
    els.queueCount.textContent = queue.length;
    
    if (!serviceOn) {
        els.queuePanel.style.display = 'none';
        return;
    }
    
    els.queuePanel.style.display = 'block';
    
    // Render active queue list
    if (queue.length === 0) {
        els.queueList.innerHTML = `
            <div style="font-size: 0.82rem; color: var(--text-secondary); padding: 8px 4px; display: flex; align-items: center; gap: 8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 3s linear infinite;">
                    <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                </svg>
                Engine is idle. Waiting for incoming emails...
            </div>
        `;
    } else {
        els.queueList.innerHTML = queue.map(item => {
            const displayName = item.sender_name || item.sender;
            return `
                <div class="queue-item" id="queue-item-${item.id}">
                    <div class="queue-item-header">
                        <span class="queue-item-sender" title="${escHtml(displayName)}">${escHtml(displayName)}</span>
                        <span class="queue-item-status">Replying...</span>
                    </div>
                    <div class="queue-item-subject" title="${escHtml(item.subject)}">${escHtml(item.subject || '(No Subject)')}</div>
                    <div class="queue-progress-bar"></div>
                </div>
            `;
        }).join('');
    }
    
    // Render workers grid
    if (workers && workers.length > 0) {
        els.workersGrid.innerHTML = workers.map(w => {
            const isActive = w.status === 'Active';
            const cardClass = isActive ? 'worker-card worker-card--active' : 'worker-card';
            const statusText = isActive ? (w.task.step || 'Processing') : 'Idle';
            const detailText = isActive ? `to: ${w.task.sender}` : 'Ready';
            
            return `
                <div class="${cardClass}">
                    <div class="worker-indicator"></div>
                    <div class="worker-info">
                        <div class="worker-name">Worker #${w.id}</div>
                        <div class="worker-status-text" title="${escHtml(detailText)}">${escHtml(statusText)}</div>
                    </div>
                </div>
            `;
        }).join('');
    } else {
        els.workersGrid.innerHTML = '<div style="font-size: 0.8rem; color: var(--text-muted)">No workers configured</div>';
    }
}


function showToast(title, message) {
    if (!els.toastContainer) return;
    
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
        <div class="toast-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
        </div>
        <div class="toast-content">
            <h4 class="toast-title">${escHtml(title)}</h4>
            <p class="toast-message">${escHtml(message)}</p>
        </div>
        <button class="toast-close" aria-label="Close notification">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
        </button>
    `;
    
    // Bind close button
    toast.querySelector('.toast-close').addEventListener('click', () => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px) scale(0.9)';
        setTimeout(() => toast.remove(), 300);
    });
    
    els.toastContainer.appendChild(toast);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px) scale(0.9)';
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

