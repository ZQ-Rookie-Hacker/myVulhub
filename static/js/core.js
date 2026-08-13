/**
 * core.js — 全局状态、初始化、环境加载与搜索筛选
 */

let allEnvironments = [];
let filteredEnvironments = [];
let currentPage = 1;
const itemsPerPage = 21;

document.addEventListener('DOMContentLoaded', () => {
    loadFromCache();

    document.getElementById('btnGitSync')?.addEventListener('click', showGitSyncModal);
    document.getElementById('btnRescan')?.addEventListener('click', forceRescan);
    document.getElementById('searchInput')?.addEventListener('input', searchEnv);
    document.getElementById('categoryFilter')?.addEventListener('change', filterByCategory);
    document.getElementById('exploitFilter')?.addEventListener('change', filterByExploit);
    document.getElementById('runningFilter')?.addEventListener('change', filterByRunning);
    document.getElementById('downloadedFilter')?.addEventListener('change', filterByDownloaded);
    document.getElementById('btnChangePath')?.addEventListener('click', showChangePathDialog);

    loadVulhubPath();
});

// 列表为空时诊断原因：vulhub 路径不存在 / 目录中没有 compose 文件
async function renderEmptyListHint() {
    try {
        const resp = await fetch('/api/vulhub-path');
        const info = await resp.json();
        const list = document.getElementById('envList');
        if (!list) return;

        if (info.exists === false) {
            list.innerHTML = `<div class="empty">
                <p>⚠ Vulhub 目录不存在：<code>${escapeHtml(info.configured_path || info.path)}</code></p>
                <p>请先在服务器上克隆 vulhub 仓库：<code>git clone https://github.com/vulhub/vulhub.git</code>，<br>
                或点击上方 <b>更改</b> 按钮，将路径配置为实际克隆的目录。</p>
            </div>`;
        } else if (info.has_environments === false) {
            list.innerHTML = `<div class="empty">
                <p>⚠ Vulhub 目录中没有找到任何 docker-compose.yml（可能克隆不完整）：<code>${escapeHtml(info.path)}</code></p>
                <p>请确认目录内容，或点击上方 <b>Git 同步</b> 重新拉取仓库。</p>
            </div>`;
        }
    } catch (e) {
        console.error('诊断空列表失败:', e);
    }
}

// 从缓存加载
async function loadFromCache() {
    showLoading(true);
    try {
        const response = await fetch('/api/scan?cache=true');
        if (!response.ok) {
            throw new Error(`服务器返回错误 (${response.status})`);
        }
        const data = await response.json();
        if (!Array.isArray(data)) {
            throw new Error((data && data.error) || '扫描返回数据格式错误');
        }
        allEnvironments = data;
        filteredEnvironments = allEnvironments.slice();

        currentPage = 1;
        displayEnvironments(filteredEnvironments);
        updateCategoryFilter();
        updateStats();
        updatePagination();

        if (allEnvironments.length === 0) {
            await renderEmptyListHint();
        }
    } catch (error) {
        console.error('cache load failed:', error);
        document.getElementById('envList').innerHTML =
            `<div class="empty">加载失败：${escapeHtml(error.message)}<br>请点击“重新扫描”重试</div>`;
    } finally {
        showLoading(false);
    }
}

// 强制重新扫描 — 直接利用 refresh-cache 返回的 count，不再冗余请求 scan
// skipConfirm：改路径后由流程自动触发，无需二次确认（避免用户取消后缓存已被清空、列表停留为空）
async function forceRescan(skipConfirm = false) {
    if (!skipConfirm && !confirm('确定要重新扫描所有环境吗？\n这会清除缓存并重新检查所有环境。')) return;

    showLoading(true);
    try {
        const refreshResponse = await fetch('/api/refresh-cache', { method: 'POST' });
        const refreshResult = await refreshResponse.json();

        if (!refreshResult.success) {
            throw new Error(refreshResult.error || '重新扫描失败');
        }

        // refresh-cache 已扫描并缓存，直接取缓存即可
        const response = await fetch('/api/scan?cache=true');
        allEnvironments = await response.json();
        filteredEnvironments = allEnvironments.slice();

        currentPage = 1;
        displayEnvironments(filteredEnvironments);
        updateCategoryFilter();
        updateStats();
        updatePagination();
        showNotification(`扫描完成，共找到 ${refreshResult.count} 个环境`, 'success');

        if (allEnvironments.length === 0) {
            await renderEmptyListHint();
        }
    } catch (error) {
        console.error('扫描失败:', error);
        showNotification('重新扫描失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

async function scanEnvironments(useCache = false) {
    if (useCache) {
        await loadFromCache();
    } else {
        await forceRescan();
    }
}

// 统计
async function updateStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();
        document.getElementById('stats').innerHTML =
            `<div class="stat-item"><div class="stat-value">${stats.total}</div><div class="stat-label">总环境</div></div>
             <div class="stat-item"><div class="stat-value">${stats.running}</div><div class="stat-label">运行中</div></div>
             <div class="stat-item"><div class="stat-value">${stats.with_exploit}</div><div class="stat-label">漏洞利用</div></div>
             <div class="stat-item"><div class="stat-value">${stats.with_images || 0}</div><div class="stat-label">已有镜像</div></div>
             <div class="stat-item"><div class="stat-value">${Object.keys(stats.categories).length}</div><div class="stat-label">分类数</div></div>`;
    } catch (error) {
        console.error('更新统计失败:', error);
    }
}

function updateCategoryFilter() {
    const categories = [...new Set(allEnvironments.map(e => e.category))].sort();
    const select = document.getElementById('categoryFilter');
    if (!select) return;
    select.innerHTML = '<option value="">所有分类</option>' +
        categories.map(c => `<option value="${c}">${c}</option>`).join('');
}

// === 搜索 / 筛选 ===
let searchTimeout;
function searchEnv() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => performSearch(), 300);
}

function filterByCategory() { performSearch(); }
function filterByExploit() { performSearch(); }
function filterByRunning() { performSearch(); }
function filterByDownloaded() { performSearch(); }

function performSearch() {
    const q = (document.getElementById('searchInput')?.value || '').toLowerCase();
    const category = document.getElementById('categoryFilter')?.value || '';
    const onlyExploit = !!document.getElementById('exploitFilter')?.checked;
    const onlyRunning = !!document.getElementById('runningFilter')?.checked;
    const onlyDownloaded = !!document.getElementById('downloadedFilter')?.checked;

    filteredEnvironments = allEnvironments.filter(env => {
        if (q && !(env.name.toLowerCase().includes(q) ||
                   (env.cve || '').toLowerCase().includes(q) ||
                   (env.category || '').toLowerCase().includes(q))) return false;
        if (category && env.category !== category) return false;
        if (onlyExploit && !env.has_exploit) return false;
        if (onlyRunning && env.status !== 'running') return false;
        if (onlyDownloaded && !env.has_docker_images) return false;
        return true;
    });

    currentPage = 1;
    displayEnvironments(filteredEnvironments);
    updatePagination();
}
