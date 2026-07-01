/**
 * utils.js — 纯工具函数（无状态依赖）
 */

function escapeHtml(text) {
    if (text == null) return '';
    const map = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'};
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

// 全局 loading 计数器（支持嵌套调用）
let _loadingDepth = 0;

function showLoading(show) {
    if (show) {
        _loadingDepth++;
    } else {
        _loadingDepth = Math.max(0, _loadingDepth - 1);
    }
    const el = document.getElementById('loading');
    if (el) el.style.display = (_loadingDepth > 0) ? 'flex' : 'none';
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => notification.classList.add('show'), 10);
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => { if (notification.parentNode) notification.remove(); }, 300);
    }, 3000);
}

function showProgressModal() {
    const m = document.getElementById('progressModal');
    if (m) {
        const log = document.getElementById('progressLog');
        if (log) log.textContent = '';
        m.style.display = 'block';
    }
}

function hideProgressModal() {
    const m = document.getElementById('progressModal');
    if (m) m.style.display = 'none';
}

function appendProgress(line) {
    const el = document.getElementById('progressLog');
    if (!el) return;
    el.textContent += (line + '\n');
    el.scrollTop = el.scrollHeight;
}
