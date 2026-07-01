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

// 从缓存加载
async function loadFromCache() {
    showLoading(true);
    try {
        const response = await fetch('/api/scan?cache=true');
        allEnvironments = await response.json();
        filteredEnvironments = allEnvironments.slice();

        currentPage = 1;
        displayEnvironments(filteredEnvironments);
        updateCategoryFilter();
        updateStats();
        updatePagination();
    } catch (error) {
        console.error('加载缓存失败:', error);
        document.getElementById('envList').innerHTML = '<div class="empty">加载失败，请点击重新扫描</div>';
    } finally {
        showLoading(false);
    }
}

// 强制重新扫描 — 直接利用 refresh-cache 返回的 count，不再冗余请求 scan
async function forceRescan() {
    if (!confirm('确定要重新扫描所有环境吗？这会清除缓存并重新检查所有环境。')) return;

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
             <div class="stat-item"><div class="stat-value">${stats.with_exploit}</div><div class="stat-label">漏洞利用脚本</div></div>
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
