// === 修正版：修复筛选功能、避免重复扫描、移除运行中容器 ===

let allEnvironments = [];
let filteredEnvironments = [];
let currentPage = 1;
const itemsPerPage = 21;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    // 只用缓存，不重新扫描
    loadFromCache();
    
    // 绑定事件监听器
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

// 只从缓存加载（不重新扫描）
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

// 强制重新扫描（清除缓存并重建）
async function forceRescan() {
    if (!confirm('确定要重新扫描所有环境吗？这会清除缓存并重新检查所有环境。')) {
        return;
    }
    
    showLoading(true);
    try {
        // 调用强制重新整理 API
        const refreshResponse = await fetch('/api/refresh-cache', { method: 'POST' });
        const refreshResult = await refreshResponse.json();
        
        if (!refreshResult.success) {
            throw new Error(refreshResult.error || '重新扫描失败');
        }
        
        // 重新加载数据
        const response = await fetch('/api/scan?cache=false');
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

// 兼容旧的 scanEnvironments 函数
async function scanEnvironments(useCache = false) {
    if (useCache) {
        await loadFromCache();
    } else {
        await forceRescan();
    }
}

// 显示环境列表
function displayEnvironments(envs) {
    const list = document.getElementById('envList');
    try {
        if (!Array.isArray(envs)) throw new Error('scan 返回不是数组');

        filteredEnvironments = envs.slice();

        const total = envs.length;
        const start = (currentPage - 1) * itemsPerPage;
        const end = Math.min(start + itemsPerPage, total);
        const pageItems = envs.slice(start, end);

        list.innerHTML = '';

        if (pageItems.length === 0) {
            list.innerHTML = '<div class="empty">没有符合条件的环境</div>';
            return;
        }

        for (const env of pageItems) {
            const category = (env && env.category) || (env?.name?.split('/')[0] || 'unknown');
            const cve = (env && env.cve) || (env?.name?.split('/').slice(-1)[0] || 'unknown');
            const status = (env && env.status) || 'unknown';
            const portsObj = (env && env.ports && typeof env.ports === 'object') ? env.ports : {};
            const portEntries = Object.entries(portsObj);
            const firstPort = portEntries.length ? String(portEntries[0][1]) : '';

            const card = document.createElement('div');
            card.className = 'env-card';

            // header
            const header = document.createElement('div');
            header.className = 'env-header';

            const title = document.createElement('div');
            title.className = 'env-title';
            title.textContent = `${category} / ${cve}`;

            const statusEl = document.createElement('div');
            statusEl.className = 'env-status ' + (status === 'running' ? 'running' : (status === 'stopped' ? 'stopped' : 'unknown'));
            statusEl.textContent = (status === 'running' ? '运行中' : (status === 'stopped' ? '已停止' : '未知'));

            header.appendChild(title);
            header.appendChild(statusEl);

            // meta
            const meta = document.createElement('div');
            meta.className = 'env-meta';

            // 前两个 ports
            for (const [svc, port] of portEntries.slice(0, 2)) {
                const tag = document.createElement('span');
                tag.className = 'tag tag-port';
                tag.textContent = `📌 ${svc}:${port}`;
                meta.appendChild(tag);
            }
            if (portEntries.length > 2) {
                const more = document.createElement('span');
                more.className = 'tag';
                more.textContent = `+${portEntries.length - 2} 个端口`;
                meta.appendChild(more);
            }

            // exploit 标签
            if (env && env.has_exploit) {
                const exp = document.createElement('span');
                exp.className = 'tag tag-exploit';
                exp.textContent = '💣 漏洞利用脚本';
                meta.appendChild(exp);
            }

            // Docker 镜像标签
            if (env && env.has_docker_images) {
                const dockerTag = document.createElement('span');
                dockerTag.className = 'tag tag-docker';
                dockerTag.textContent = '🐳 已有镜像';
                meta.appendChild(dockerTag);
            }

            // 路径标签
            const pathTag = document.createElement('span');
            pathTag.className = 'tag';
            pathTag.textContent = `📁 ${env?.name || ''}`;
            meta.appendChild(pathTag);

            // actions
            const actions = document.createElement('div');
            actions.className = 'env-actions';

            const btnStartStop = document.createElement('button');
            if (status === 'running') {
                btnStartStop.className = 'btn btn-danger';
                btnStartStop.textContent = '⏹ 停止';
                btnStartStop.onclick = () => stopEnv(env.name);
            } else {
                btnStartStop.className = 'btn btn-success';
                btnStartStop.textContent = '▶️ 启动';
                btnStartStop.onclick = () => startEnv(env.name);
            }
            actions.appendChild(btnStartStop);

            if (status === 'running' && firstPort) {
                const btnOpen = document.createElement('button');
                btnOpen.className = 'btn btn-primary';
                btnOpen.textContent = '🌐 打开';
                btnOpen.onclick = () => openEnv(firstPort);
                actions.appendChild(btnOpen);
            }

            // 如果有 Exploit，添加查看按钮
            if (env && env.has_exploit) {
                const btnExploit = document.createElement('button');
                btnExploit.className = 'btn';
                btnExploit.textContent = '💣 漏洞利用脚本';
                btnExploit.onclick = () => showExploit(env.name);
                actions.appendChild(btnExploit);
            }

            // 如果已有镜像，添加删除镜像按钮
            if (env && env.has_docker_images) {
                const btnRemoveImages = document.createElement('button');
                btnRemoveImages.className = 'btn btn-danger';
                btnRemoveImages.textContent = '🗑️ 删除镜像';
                btnRemoveImages.onclick = () => removeImages(env.name);
                actions.appendChild(btnRemoveImages);
            }

            const btnDetail = document.createElement('button');
            btnDetail.className = 'btn';
            btnDetail.textContent = '📖 详情';
            btnDetail.onclick = () => showDetail(env.name);
            actions.appendChild(btnDetail);

            card.appendChild(header);
            card.appendChild(meta);
            card.appendChild(actions);
            list.appendChild(card);
        }

        renderPagination(total);
    } catch (e) {
        console.error('渲染列表发生错误：', e);
        list.innerHTML = `<div class="empty">渲染错误：${e.message}</div>`;
    }
}

// 分页
function renderPagination(total) {
    const totalPages = Math.max(1, Math.ceil(total / itemsPerPage));
    const pag = document.getElementById('pagination');
    if (!pag) return;

    let html = '';

    // 上一页
    html += `
      <button class="btn-page ${currentPage === 1 ? 'disabled' : ''}"
              onclick="changePage(${Math.max(1, currentPage - 1)})"
              ${currentPage === 1 ? 'disabled' : ''}>← 上一页</button>`;

    // 页码
    const maxVisiblePages = 7;
    let startPage = Math.max(1, currentPage - 3);
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    if (startPage > 1) {
        html += `<button class="btn-page" onclick="changePage(1)">1</button>`;
        if (startPage > 2) html += `<span class="page-ellipsis">...</span>`;
    }
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="btn-page ${i === currentPage ? 'active' : ''}" onclick="changePage(${i})">${i}</button>`;
    }
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<span class="page-ellipsis">...</span>`;
        html += `<button class="btn-page" onclick="changePage(${totalPages})">${totalPages}</button>`;
    }

    // 下一页
    html += `
      <button class="btn-page ${currentPage === totalPages ? 'disabled' : ''}"
              onclick="changePage(${Math.min(totalPages, currentPage + 1)})"
              ${currentPage === totalPages ? 'disabled' : ''}>下一页 →</button>`;

    // 跳页
    html += `
      <div class="page-jump">
        跳至 <input type="number" id="pageJumpInput" min="1" max="${totalPages}" value="${currentPage}"
                    onkeypress="if(event.key==='Enter') jumpToPage()">
        <button class="btn-page" onclick="jumpToPage()">Go</button>
      </div>`;

    pag.innerHTML = html;
}

function changePage(page) {
    const totalPages = Math.max(1, Math.ceil(filteredEnvironments.length / itemsPerPage));
    if (page < 1 || page > totalPages) return;
    currentPage = page;
    displayEnvironments(filteredEnvironments);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function jumpToPage() {
    const input = document.getElementById('pageJumpInput');
    const page = parseInt(input.value, 10);
    if (!isNaN(page)) changePage(page);
}

function updatePagination() {
    const totalPages = Math.max(1, Math.ceil(filteredEnvironments.length / itemsPerPage));
    if (currentPage > totalPages && totalPages > 0) currentPage = totalPages;
}

async function updateStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();
        document.getElementById('stats').innerHTML = `
            <div class="stat-item"><div class="stat-value">${stats.total}</div><div class="stat-label">总环境</div></div>
            <div class="stat-item"><div class="stat-value">${stats.running}</div><div class="stat-label">运行中</div></div>
            <div class="stat-item"><div class="stat-value">${stats.with_exploit}</div><div class="stat-label">漏洞利用脚本</div></div>
            <div class="stat-item"><div class="stat-value">${stats.with_images || 0}</div><div class="stat-label">已有镜像</div></div>
            <div class="stat-item"><div class="stat-value">${Object.keys(stats.categories).length}</div><div class="stat-label">分类数</div></div>
        `;
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

function filterByCategory() {
    performSearch();
}

function filterByExploit() {
    performSearch();
}

function filterByRunning() {
    performSearch();
}

function filterByDownloaded() {
    performSearch();
}

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
        // 使用 has_docker_images 来判断是否已有镜像
        if (onlyDownloaded && !env.has_docker_images) return false;
        return true;
    });

    currentPage = 1;
    displayEnvironments(filteredEnvironments);
    updatePagination();
}

// === 启停 ===
async function startEnv(name) {
    try {
        // 检查是否缺镜像（这个很快，可以显示遮罩）
        showLoading(true);
        const ci = await fetch(`/api/check-images?name=${encodeURIComponent(name)}`).then(r => r.json());
        showLoading(false);
        
        if (!ci.success) throw new Error(ci.error || "check-images 失败");
        const missing = ci.missing || [];
        
        let useProxyForPull = false;
        if (missing.length > 0) {
            // 显示自定义对话框让用户选择是否拉取镜像和是否使用代理
            const shouldPull = await showImagePullDialog('需要下载镜像', 
                `${missing.join("\n- ")}`,
                missing);
            
            if (!shouldPull.pull) {
                showNotification('用户取消了镜像拉取操作', 'info');
                return;
            }
            
            useProxyForPull = shouldPull.useProxy;
            
            // 下载镜像时不用遮罩，已经有进度窗口了
            showProgressModal();
            appendProgress(`[Info] 开始下载镜像：\n- ${missing.join("\n- ")}`);
            if (useProxyForPull) {
                appendProgress('[Info] 使用proxychains4代理模式拉取镜像...');
            } else {
                appendProgress('[Info] 使用直接连接拉取镜像...');
            }
            await pullWithProgress(name, useProxyForPull);
        }

        // 启动容器时显示遮罩
        showLoading(true);
        const resp = await fetch('/api/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const result = await resp.json();
        showLoading(false);

        if (!result.success) {
            if (result.port_conflict) {
                let message = `端口已被占用`;
                if (result.conflicting_containers && result.conflicting_containers.length > 0) {
                    message += `\n占用的容器: ${result.conflicting_containers.join(', ')}`;
                }
                message += '\n\n建议：\n1. 停止占用端口的容器\n2. 或修改 docker-compose.yml 使用其他端口';
                alert(message);
            } else {
                showNotification('启动失败: ' + (result.error || '未知错误'), 'error');
            }
            hideProgressModal();
            return;
        }

        updateEnvStatus(name, 'running');
        showNotification('环境启动成功', 'success');

        // 等服务就绪（这个也可能要等一段时间，但不显示遮罩）
        const wait = await fetch(`/api/wait-ready?name=${encodeURIComponent(name)}&timeout=20`).then(r=>r.json());
        if (wait.success && wait.ready && wait.port) {
            hideProgressModal();
            openEnv(String(wait.port));
        } else {
            hideProgressModal();
            showNotification('已启动，但无法确认服务就绪（可稍后再开）', 'warning');
        }
    } catch (e) {
        showLoading(false);
        hideProgressModal();
        showNotification('启动失败: ' + e.message, 'error');
    }
}

// 显示镜像拉取选择对话框
function showImagePullDialog(title, message, missingImages) {
    return new Promise((resolve) => {
        // 创建半透明背景
        const overlay = document.createElement('div');
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, rgba(106, 89, 198, 0.7), rgba(111, 117, 209, 0.7));
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            backdrop-filter: blur(4px);
        `;
        
        // 创建对话框
        const dialog = document.createElement('div');
        dialog.style.cssText = `
            background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
            padding: 30px;
            border-radius: 16px;
            max-width: 520px;
            width: 90%;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(255, 255, 255, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.3);
            animation: scaleIn 0.3s ease-out;
        `;
        
        // 添加动画样式
        const style = document.createElement('style');
        style.textContent = `
            @keyframes scaleIn {
                from { transform: scale(0.8); opacity: 0; }
                to { transform: scale(1); opacity: 1; }
            }
            .proxy-option-container {
                display: flex;
                align-items: center;
            }
            .proxy-option-container input[type="checkbox"] {
                position: absolute; opacity: 0; width: 0; height: 0; /* 隐藏原生复选框但保持功能 */
            }
            .custom-checkbox {
                width: 18px;
                height: 18px;
                border: 2px solid #6366f1;
                border-radius: 4px;
                display: inline-block;
                position: relative;
                cursor: pointer;
                margin-right: 8px;
                vertical-align: middle;
                background: white;
                flex-shrink: 0;
            }
            .proxy-option-container input[type="checkbox"]:checked ~ .custom-checkbox::after {
                content: "✓";
                position: absolute;
                top: -2px;
                left: 2px;
                color: white;
                font-size: 12px;
                font-weight: bold;
            }
            .proxy-option-container input[type="checkbox"]:checked ~ .custom-checkbox {
                background: #6366f1;
            }
        `;
        document.head.appendChild(style);
        
        // 标题
        const titleEl = document.createElement('h3');
        titleEl.style.cssText = 'margin-top: 0; margin-bottom: 12px; color: #1e293b; font-size: 20px; display: flex; align-items: center;';
        titleEl.innerHTML = '🐳 ' + title;
        
        // 消息
        const messageEl = document.createElement('p');
        messageEl.style.cssText = 'white-space: pre-line; margin-bottom: 16px; color: #334155; line-height: 1.5;';
        messageEl.textContent = message;
        
        // 显示缺失的镜像列表
        if (missingImages && missingImages.length > 0) {
            const imageList = document.createElement('div');
            imageList.style.cssText = 'background: #f1f5f9; border-radius: 10px; padding: 16px; margin: 12px 0; max-height: 180px; overflow-y: auto; border: 1px solid #e2e8f0;';
            
            const listTitle = document.createElement('h4');
            listTitle.style.cssText = 'margin: 0 0 10px 0; font-size: 14px; color: #475569; display: flex; align-items: center;';
            listTitle.innerHTML = '📦 缺失的镜像:';
            
            const ul = document.createElement('ul');
            ul.style.cssText = 'margin: 0; padding-left: 16px;';
            missingImages.forEach(img => {
                const li = document.createElement('li');
                li.style.cssText = 'margin-bottom: 6px; font-family: monospace; font-size: 13px; color: #475569; background: #f8fafc; padding: 4px 8px; border-radius: 6px; border-left: 3px solid #6366f1;';
                li.textContent = img;
                ul.appendChild(li);
            });
            
            imageList.appendChild(listTitle);
            imageList.appendChild(ul);
            
            dialog.appendChild(imageList);
        }
        
        // 代理选项复选框（视觉上呈现为圆形按钮）
        const proxyContainer = document.createElement('div');
        proxyContainer.className = 'proxy-option-container';
        proxyContainer.style.cssText = 'display: flex; align-items: center; margin: 18px 0; padding: 14px; background: linear-gradient(to right, #f0f9ff, #e0f2fe); border-radius: 10px; border: 1px solid #bae6fd;';
        
        const proxyCheckbox = document.createElement('input');
        proxyCheckbox.type = 'checkbox';
        proxyCheckbox.id = 'useProxyCheckbox';
        // 使用CSS隐藏但保持可访问性
        proxyCheckbox.style.cssText = 'position: absolute; opacity: 0; width: 0; height: 0;';
        
        const proxyCheckboxWrapper = document.createElement('span');
        proxyCheckboxWrapper.className = 'custom-checkbox';
        proxyCheckboxWrapper.style.cursor = 'pointer';
        
        // 仅为自定义复选框添加点击事件，不使用label关联
        proxyCheckboxWrapper.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            proxyCheckbox.checked = !proxyCheckbox.checked;
            // 手动触发change事件，确保其他可能的监听器也被调用
            proxyCheckbox.dispatchEvent(new Event('change'));
        });
        
        const proxyLabel = document.createElement('div'); // 使用div而不是label，避免自动关联复选框
        proxyLabel.textContent = 'proxychains4';
        proxyLabel.style.cssText = 'cursor: default; margin-left: 10px; color: #0c4a6e; font-weight: 500; flex-grow: 1;';
        
        proxyContainer.appendChild(proxyCheckbox);
        proxyContainer.appendChild(proxyCheckboxWrapper);
        proxyContainer.appendChild(proxyLabel);
        
        // 提示文本
        const hint = document.createElement('small');
        hint.style.cssText = 'color: #64748b; display: block; margin: 12px 0 20px 0; padding: 10px; background: #fefce8; border-radius: 8px; border-left: 3px solid #fbbf24;';
        hint.textContent = '💡 提示：如果网络受限无法拉取镜像，请勾选此项并确保已配置好proxychains4';
        
        // 按钮容器
        const buttonContainer = document.createElement('div');
        buttonContainer.style.cssText = 'display: flex; gap: 12px; justify-content: flex-end;';
        
        // 取消按钮
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn';
        cancelBtn.textContent = '❌ 取消';
        cancelBtn.style.cssText = 'padding: 10px 20px; font-weight: 500; border-radius: 8px; transition: all 0.2s;';
        cancelBtn.onmouseenter = () => cancelBtn.style.transform = 'translateY(-2px)';
        cancelBtn.onmouseleave = () => cancelBtn.style.transform = 'translateY(0)';
        cancelBtn.onclick = () => {
            document.body.removeChild(overlay);
            resolve({ pull: false, useProxy: false }); // 用户取消操作
        };
        
        // 确定按钮
        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn btn-success';
        confirmBtn.textContent = '✅ 确定';
        confirmBtn.style.cssText = 'padding: 10px 20px; font-weight: 500; border-radius: 8px; transition: all 0.2s;';
        confirmBtn.onmouseenter = () => confirmBtn.style.transform = 'translateY(-2px)';
        confirmBtn.onmouseleave = () => confirmBtn.style.transform = 'translateY(0)';
        confirmBtn.onclick = () => {
            document.body.removeChild(overlay);
            resolve({ pull: true, useProxy: proxyCheckbox.checked }); // 用户确认拉取，以及是否使用代理
        };
        
        buttonContainer.appendChild(cancelBtn);
        buttonContainer.appendChild(confirmBtn);
        
        dialog.appendChild(titleEl);
        dialog.appendChild(messageEl);
        dialog.appendChild(proxyContainer);
        dialog.appendChild(hint);
        dialog.appendChild(buttonContainer);
        overlay.appendChild(dialog);
        
        document.body.appendChild(overlay);
        
        // 点击背景关闭对话框
        overlay.onclick = (e) => {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
                // 从DOM中移除样式元素
                if (style.parentNode) style.parentNode.removeChild(style);
                resolve({ pull: false, useProxy: false });
            }
        };
        
        // 默认聚焦确定按钮
        setTimeout(() => confirmBtn.focus(), 100);
    });
}

// 保持原有的兼容函数
function showProxyDialog(title, message) {
    return new Promise((resolve) => {
        showImagePullDialog(title, message, []).then(result => {
            resolve(result.useProxy); // 返回是否使用代理的布尔值
        });
    });
}

async function stopEnv(name) {
    showLoading(true);
    try {
        const response = await fetch('/api/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const result = await response.json();
        if (result.success) {
            showNotification('环境已停止', 'success');
            updateEnvStatus(name, 'stopped');
        } else {
            showNotification('停止失败: ' + (result.error || '未知错误'), 'error');
        }
    } catch (error) {
        showNotification('停止失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

function updateEnvStatus(name, status) {
    const env = allEnvironments.find(e => e.name === name);
    if (env) env.status = status;
    const filteredEnv = filteredEnvironments.find(e => e.name === name);
    if (filteredEnv) filteredEnv.status = status;
    displayEnvironments(filteredEnvironments);
    updateStats();
}

// === 详情与 Exploit ===
async function showDetail(name) {
    showLoading(true);
    try {
        const [envResponse, readmeResponse] = await Promise.all([
            fetch(`/api/env/${name}`),
            fetch(`/api/readme/${name}`)
        ]);
        const env = await envResponse.json();
        const readme = await readmeResponse.json();

        let content = `
            <h2>${env.name}</h2>
            <div class="env-meta" style="margin: 1rem 0;">
                <span class="tag">分类: ${env.category}</span>
                <span class="tag">CVE: ${env.cve}</span>
                ${env.exploit_files && env.exploit_files.length > 0 ? 
                    `<span class="tag tag-exploit">漏洞利用脚本: ${env.exploit_files.join(', ')}</span>` : ''}
            </div>
        `;

        if (env.images && env.images.length > 0) {
            content += '<h3>截图</h3>';
            env.images.forEach(img => {
                content += `<img src="${img.data}" class="screenshot" alt="${img.name}" loading="lazy">`;
            });
        }

        content += '<h3>说明文档</h3>';
        content += `<div class="readme-content">${readme.html || ''}</div>`;

        content += '<h3>Docker Compose 配置</h3>';
        content += `<pre class="code-block">${escapeHtml(env.compose || '')}</pre>`;

        const cont = document.getElementById('modalContent');
        cont.innerHTML = content;
        cont.style.maxHeight = '75vh';
        cont.style.overflow = 'auto';

        const modal = document.getElementById('detailModal');
        modal.style.display = 'block';
        modal.style.overflowY = 'auto';
    } catch (error) {
        showNotification('加载详情失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

async function showExploit(name) {
    showLoading(true);
    try {
        const response = await fetch(`/api/exploit/${name}`);
        const exploits = await response.json();

        if (!Array.isArray(exploits) || exploits.length === 0) {
            showNotification('没有找到漏洞利用脚本', 'warning');
            return;
        }

        let content = `<h2>漏洞利用脚本 - ${name}</h2>
        <div style="background:#fef3c7; color:#78350f; padding:12px; border-radius:8px; margin:10px 0;">
            ⚠️ <strong>警告</strong>：仅供学术研究与授权测试使用，使用者需自负法律责任
        </div>`;

        exploits.forEach(exploit => {
            content += `
                <div style="border:1px solid #e5e7eb; border-radius:8px; padding:12px; margin:12px 0;">
                    <h3 style="margin-top:0;">${exploit.filename}</h3>
                    <div style="margin: 8px 0;">
                        <span class="tag">大小: ${exploit.size} 字节</span>
                        <span class="tag">行数: ${exploit.lines}</span>
                        <span class="tag">路径: ${exploit.path}</span>
                    </div>
                    ${exploit.usage ? `<div style="background:#f3f4f6; padding:8px; border-radius:6px; margin:8px 0;">
                        <strong>使用说明：</strong> ${escapeHtml(exploit.usage)}
                    </div>` : ''}
                    <h4>代码：</h4>
                    <pre class="code-block" style="max-height:400px; overflow:auto;">${escapeHtml(exploit.content)}</pre>
                </div>
            `;
        });

        const cont = document.getElementById('modalContent');
        cont.innerHTML = content;
        cont.style.maxHeight = '75vh';
        cont.style.overflow = 'auto';

        const modal = document.getElementById('detailModal');
        modal.style.display = 'block';
        modal.style.overflowY = 'auto';
    } catch (error) {
        showNotification('加载漏洞利用脚本失败: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

// === 其它小工具 ===
function openEnv(port) {
    // window.open(`http://localhost:${port}`,function openEnv(port) {
    // 从当前页面URL获取服务器地址
    const currentHost = window.location.hostname;
    const currentProtocol = window.location.protocol;
    window.open(`${currentProtocol}//${currentHost}:${port}`, '_blank');
}

async function removeImages(name) {
    if (!confirm(`确定要删除环境 "${name}" 的所有镜像吗？\n\n⚠️ 此操作不可逆！\n镜像删除后将需要重新下载。`)) {
        return;
    }

    showLoading(true);
    try {
        const response = await fetch('/api/remove-images', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name})
        });
        const result = await response.json();
        showLoading(false);

        if (result.success) {
            showNotification(`镜像删除成功！删除了 ${result.removed?.length || 0} 个镜像`, 'success');
            // 重新扫描以更新状态
            await forceRescan();
        } else {
            let errorMsg = result.error || '删除失败';
            if (result.details && result.details.failed) {
                errorMsg += `\n失败镜像: ${result.details.failed.join(', ')}`;
            }
            showNotification(errorMsg, 'error');
        }
    } catch (error) {
        showLoading(false);
        showNotification('删除镜像失败: ' + error.message, 'error');
    }
}

function closeModal() {
    const m = document.getElementById('detailModal');
    if (m) m.style.display = 'none';
}

window.onclick = function(event) {
    const modal = document.getElementById('detailModal');
    if (event.target === modal) modal.style.display = 'none';
};

function showLoading(show) {
    const el = document.getElementById('loading');
    if (el) el.style.display = show ? 'flex' : 'none';
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => notification.classList.add('show'), 10);
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => document.body.removeChild(notification), 300);
    }, 3000);
}

function escapeHtml(text) {
    if (text == null) return '';
    const map = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'};
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

// === 下载进度 Modal & SSE ===
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

function pullWithProgress(name, useProxy = false) {
    const proxyParam = useProxy ? '&proxy=true' : '';
    return new Promise((resolve, reject) => {
        const es = new EventSource(`/api/pull-stream?name=${encodeURIComponent(name)}${proxyParam}`);
        es.addEventListener('log', (ev) => appendProgress(ev.data));
        es.addEventListener('done', () => { 
            es.close(); 
            appendProgress('[OK] 镜像下载完成'); 
            resolve(); 
        });
        es.onerror = () => { 
            es.close(); 
            appendProgress('[Error] 下载中断'); 
            reject(new Error('pull 失败')); 
        };
    });
}

// Git 同步功能
function showGitSyncModal() {
    const modal = document.createElement('div');
    modal.id = 'gitSyncModal';
    modal.style.cssText = `
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    `;
    
    modal.innerHTML = `
        <div style="background: white; padding: 24px; border-radius: 12px; max-width: 500px; width: 90%; position: relative;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <h3 style="margin: 0;">🔄 Git 同步</h3>
                <button id="settingsBtn" onclick="showGitSettingsModal()" 
                        style="background: none; border: none; font-size: 18px; cursor: pointer; padding: 4px;">
                    ⚙️
                </button>
            </div>
            
            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 600;">同步方式:</label>
                <select id="syncMethod" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                    <option value="https">HTTPS</option>
                    <option value="ssh">SSH</option>
                    <option value="gh">GitHub CLI</option>
                </select>
            </div>
            
            <div style="margin-bottom: 16px; padding: 16px; background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border: 1px solid #e0e0e0; border-radius: 8px; font-size: 0.9em; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <span style="background: #007bff; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; margin-right: 8px;">📋</span>
                    <span style="font-weight: 600; color: #495057;">当前设置</span>
                </div>
                <div style="display: flex; align-items: center; margin-bottom: 4px;">
                    <span style="color: #6c757d; font-size: 0.85em; min-width: 80px;">远程仓库:</span>
                    <span id="currentSettings" style="font-family: 'Courier New', monospace; background: rgba(0,123,255,0.1); padding: 2px 6px; border-radius: 3px; color: #0056b3; font-size: 0.85em; word-break: break-all;">https://github.com/vulhub/vulhub.git</span>
                </div>
                <div id="proxySettings" style="display: none; align-items: center;">
                    <span style="color: #6c757d; font-size: 0.85em; min-width: 80px;">代理设置:</span>
                    <span style="font-family: 'Courier New', monospace; background: rgba(40,167,69,0.1); padding: 2px 6px; border-radius: 3px; color: #28a745; font-size: 0.85em;">未启用</span>
                </div>
                <div style="margin-top: 8px; font-size: 0.8em; color: #6c757d; font-style: italic;">
                    点击右上角 ⚙️ 图标可修改设置
                </div>
            </div>
            
            <div style="display: flex; gap: 8px; justify-content: flex-end;">
                <button onclick="closeGitSyncModal()" class="btn">取消</button>
                <button onclick="startGitSync()" class="btn btn-primary">开始同步</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // 加载当前设置并更新显示
    loadCurrentSettings();
    
    // 添加事件监听器
    const syncMethodSelect = document.getElementById('syncMethod');
    syncMethodSelect.addEventListener('change', function() {
        loadCurrentSettings();
    });
}

async function loadCurrentSettings() {
    const method = document.getElementById('syncMethod').value;
    
    try {
        // 获取当前 Git 配置
        const response = await fetch('/api/git-config');
        const config = await response.json();
        
        let remoteUrl = config.remote_url || 'https://github.com/vulhub/vulhub.git';
        let useProxy = config.use_proxy || false;
        
        // 根据选择的同步方式更新显示
        const currentSettings = document.getElementById('currentSettings');
        const proxySettings = document.getElementById('proxySettings');
        const proxySpan = proxySettings.querySelector('span:last-child');
        
        // 更新远程仓库显示
        if (method === 'ssh' && remoteUrl.startsWith('git@')) {
            currentSettings.textContent = remoteUrl;
            currentSettings.style.background = 'rgba(220,53,69,0.1)';
            currentSettings.style.color = '#dc3545';
        } else if (method === 'https' && remoteUrl.startsWith('https://')) {
            currentSettings.textContent = remoteUrl;
            currentSettings.style.background = 'rgba(0,123,255,0.1)';
            currentSettings.style.color = '#0056b3';
        } else {
            // 如果当前配置与选择的方式不匹配，显示默认值
            if (method === 'ssh') {
                currentSettings.textContent = 'git@github.com:vulhub/vulhub.git';
                currentSettings.style.background = 'rgba(220,53,69,0.1)';
                currentSettings.style.color = '#dc3545';
            } else {
                currentSettings.textContent = 'https://github.com/vulhub/vulhub.git';
                currentSettings.style.background = 'rgba(0,123,255,0.1)';
                currentSettings.style.color = '#0056b3';
            }
        }
        
        // 更新代理设置显示
        if (method === 'https') {
            proxySettings.style.display = 'flex';
            if (useProxy) {
                proxySpan.textContent = '已启用 (proxychains4)';
                proxySpan.style.background = 'rgba(40,167,69,0.1)';
                proxySpan.style.color = '#28a745';
            } else {
                proxySpan.textContent = '未启用';
                proxySpan.style.background = 'rgba(108,117,125,0.1)';
                proxySpan.style.color = '#6c757d';
            }
        } else {
            proxySettings.style.display = 'none';
        }
        
    } catch (error) {
        console.error('加载设置失败:', error);
        // 显示默认设置
        const currentSettings = document.getElementById('currentSettings');
        const proxySettings = document.getElementById('proxySettings');
        const proxySpan = proxySettings.querySelector('span:last-child');
        
        if (method === 'ssh') {
            currentSettings.textContent = 'git@github.com:vulhub/vulhub.git';
            currentSettings.style.background = 'rgba(220,53,69,0.1)';
            currentSettings.style.color = '#dc3545';
        } else {
            currentSettings.textContent = 'https://github.com/vulhub/vulhub.git';
            currentSettings.style.background = 'rgba(0,123,255,0.1)';
            currentSettings.style.color = '#0056b3';
        }
        
        if (method === 'https') {
            proxySettings.style.display = 'flex';
            proxySpan.textContent = '未启用';
            proxySpan.style.background = 'rgba(108,117,125,0.1)';
            proxySpan.style.color = '#6c757d';
        } else {
            proxySettings.style.display = 'none';
        }
    }
}

function showGitSettingsModal() {
    const currentMethod = document.getElementById('syncMethod').value;
    
    const settingsModal = document.createElement('div');
    settingsModal.id = 'gitSettingsModal';
    settingsModal.style.cssText = `
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1001;
    `;
    
    // 根据当前方法设置默认 URL 和占位符
    let defaultUrl, placeholder, protocol;
    if (currentMethod === 'https') {
        defaultUrl = 'https://github.com/vulhub/vulhub.git';
        placeholder = '例如: https://github.com/vulhub/vulhub.git';
        protocol = 'https';
    } else { // ssh
        defaultUrl = 'git@github.com:vulhub/vulhub.git';
        placeholder = '例如: git@github.com:vulhub/vulhub.git';
        protocol = 'ssh';
    }
    
    settingsModal.innerHTML = `
        <div style="background: white; padding: 24px; border-radius: 12px; max-width: 500px; width: 90%;">
            <h3 style="margin: 0 0 16px 0;">⚙️ Git 设置</h3>
            
            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 600;">远程仓库 URL:</label>
                <input type="text" id="remoteUrlInput" placeholder="${placeholder}" value="${defaultUrl}"
                       style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
            </div>
            
            <!-- 仅 HTTPS 显示代理选项 -->
            ${currentMethod === 'https' ? `
            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 8px; font-weight: 600;">使用代理:</label>
                <label style="display: flex; align-items: center; gap: 8px;">
                    <input type="checkbox" id="useProxyCheckbox" style="width: auto;">
                    <span>通过 proxychains4 使用代理</span>
                </label>
            </div>
            ` : ''}
            
            <div style="display: flex; gap: 8px; justify-content: flex-end;">
                <button onclick="closeGitSettingsModal()" class="btn">取消</button>
                <button onclick="saveGitSettings()" class="btn btn-primary">保存设置</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(settingsModal);
    
    // 加载当前设置
    loadCurrentGitSettings(currentMethod);
}

async function loadCurrentGitSettings(method) {
    try {
        const response = await fetch('/api/git-config');
        const config = await response.json();
        
        const remoteUrlInput = document.getElementById('remoteUrlInput');
        const useProxyCheckbox = document.getElementById('useProxyCheckbox');
        
        if (remoteUrlInput && config.remote_url) {
            remoteUrlInput.value = config.remote_url;
        }
        
        if (useProxyCheckbox && config.use_proxy !== undefined) {
            useProxyCheckbox.checked = config.use_proxy;
        }
        
    } catch (error) {
        console.error('加载 Git 设置失败:', error);
    }
}

async function saveGitSettings() {
    const currentMethod = document.getElementById('syncMethod').value;
    const remoteUrl = document.getElementById('remoteUrlInput').value.trim();
    const useProxy = document.getElementById('useProxyCheckbox')?.checked || false;
    
    if (!remoteUrl) {
        showNotification('请输入远程仓库 URL', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/git-config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                remote_url: remoteUrl,
                use_proxy: useProxy,
                protocol: currentMethod
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('设置保存成功', 'success');
            closeGitSettingsModal();
            // 重新加载当前设置显示
            loadCurrentSettings();
        } else {
            showNotification('设置保存失败: ' + result.error, 'error');
        }
        
    } catch (error) {
        showNotification('保存设置异常: ' + error.message, 'error');
    }
}

function closeGitSettingsModal() {
    const settingsModal = document.getElementById('gitSettingsModal');
    if (settingsModal) {
        settingsModal.remove();
    }
}

function closeGitSyncModal() {
    const modal = document.getElementById('gitSyncModal');
    if (modal) {
        modal.remove();
    }
}

async function startGitSync() {
    const method = document.getElementById('syncMethod').value;
    
    // 获取当前设置
    let remoteUrl, useProxy = false;
    
    try {
        const response = await fetch('/api/git-config');
        const config = await response.json();
        
        remoteUrl = config.remote_url;
        useProxy = config.use_proxy || false;
        
        // 如果没有设置，使用默认值
        if (!remoteUrl) {
            switch(method) {
                case 'ssh':
                    remoteUrl = 'git@github.com:vulhub/vulhub.git';
                    break;
                case 'https':
                    remoteUrl = 'https://github.com/vulhub/vulhub.git';
                    break;
                case 'gh':
                    remoteUrl = 'vulhub/vulhub';
                    break;
                default:
                    remoteUrl = 'https://github.com/vulhub/vulhub.git';
                    break;
            }
        }
        
        // 如果是 HTTPS 并且启用了代理，则使用 https_proxy 方法
        let effectiveMethod = method;
        if (method === 'https' && useProxy) {
            effectiveMethod = 'https_proxy';
        }
        
        closeGitSyncModal();
        showProgressModal();
        appendProgress(`[Info] 开始 Git 同步...`);
        appendProgress(`[Info] 同步方式: ${effectiveMethod}`);
        appendProgress(`[Info] 远程仓库: ${remoteUrl}`);
        if (useProxy && method === 'https') {
            appendProgress(`[Info] 代理设置: 已启用 (proxychains4)`);
        }
        
        try {
            const response = await fetch('/api/git-sync', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({method: effectiveMethod, remote_url: remoteUrl})
            });
            
            const result = await response.json();
            
            if (result.success) {
                appendProgress(`[Success] ${result.message || '同步成功'}`);
                if (result.output) {
                    appendProgress(result.output);
                }
                
                // 显示变更摘要
                if (result.changes) {
                    appendProgress('\n[Info] ==================== 同步变更摘要 ====================');
                    if (result.changes.new) {
                        appendProgress(`[Info] ✅ 新仓库初始化成功`);
                        appendProgress(`[Info] 📦 总提交数: ${result.changes.total_commits}`);
                        appendProgress(`[Info] 🐳 总环境数: ${result.changes.total_environments}`);
                    } else {
                        appendProgress(`[Info] ✅ 同步完成`);
                        appendProgress(`[Info] 🔄 新增提交: ${result.changes.commits_ahead || 0}`);
                        appendProgress(`[Info] 📊 文件变更: 修改=${result.changes.files_changed || 0}, 新增=${result.changes.files_added || 0}, 删除=${result.changes.files_deleted || 0}`);
                        appendProgress(`[Info] 🐳 总环境数: ${result.changes.total_environments || 0}`);
                        
                        // 显示变更的CVE
                        if (result.changes.changed_cves && result.changes.changed_cves.length > 0) {
                            appendProgress(`[Info] 🔥 变更的CVE环境:`);
                            result.changes.changed_cves.forEach(cve => {
                                let emoji = '📝';
                                if (cve.type === '新增') emoji = '🆕';
                                if (cve.type === '删除') emoji = '🗑️';
                                appendProgress(`[Info]   ${emoji} ${cve.cve} (${cve.type}) - ${cve.path}`);
                            });
                        }
                        
                        // 显示最新提交信息
                        if (result.latest_commit) {
                            appendProgress(`[Info] 📝 最新提交: ${result.latest_commit.message}`);
                            appendProgress(`[Info]   作者: ${result.latest_commit.author} | 时间: ${result.latest_commit.date} (${result.latest_commit.hash})`);
                        }
                    }
                    appendProgress('[Info] =====================================================');
                }
                
                setTimeout(() => {
                    hideProgressModal();
                    showNotification('Git 同步成功！', 'success');
                    // 同步完成后重新扫描
                    forceRescan();
                }, 2000);
            } else {
                appendProgress(`[Error] ${result.error || '同步失败'}`);
                setTimeout(() => {
                    hideProgressModal();
                    showNotification(result.error || 'Git 同步失败', 'error');
                }, 2000);
            }
            
        } catch (error) {
            appendProgress(`[Error] 同步异常: ${error.message}`);
            setTimeout(() => {
                hideProgressModal();
                showNotification('Git 同步异常: ' + error.message, 'error');
            }, 2000);
        }
        
    } catch (error) {
        console.error('获取设置失败:', error);
        showNotification('获取 Git 设置失败，请检查网络连接', 'error');
    }
}

// === Vulhub 路径配置 ===
async function loadVulhubPath() {
    try {
        const resp = await fetch('/api/vulhub-path');
        const data = await resp.json();
        const display = document.getElementById('vulhubPathDisplay');
        if (display && data.path) {
            display.textContent = data.path;
            display.title = data.path;
        }
    } catch (e) {
        console.error('加载 vulhub 路径失败:', e);
    }
}

function showChangePathDialog() {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position: fixed; inset: 0;
        background: rgba(0,0,0,0.4);
        display: flex; align-items: center; justify-content: center;
        z-index: 10000;
    `;

    const dialog = document.createElement('div');
    dialog.style.cssText = `
        background: #fff; padding: 24px; border-radius: 12px;
        max-width: 520px; width: 90%;
        box-shadow: 0 16px 40px rgba(0,0,0,0.2);
    `;

    dialog.innerHTML = `
        <h3 style="margin:0 0 8px 0;">📂 配置 Vulhub 路径</h3>
        <p style="color:#6b7280; font-size:13px; margin:0 0 16px 0;">
            请先克隆 vulhub 仓库到你想要的目录，然后在此输入路径（支持绝对路径和相对路径，相对路径基于 /opt/myVulhub）。
        </p>
        <div style="margin-bottom:12px;">
            <label style="display:block; margin-bottom:6px; font-weight:600;">Vulhub 目录路径:</label>
            <input id="newVulhubPath" type="text" style="width:100%; padding:10px; border:1px solid #d1d5db; border-radius:8px; font-family:monospace; font-size:14px;" placeholder="例如: /opt/vulhub 或 ../vulhub（相对路径基于 /opt/myVulhub 工作目录）" />
        </div>
        <div id="pathValidationMsg" style="font-size:12px; margin-bottom:12px; min-height:18px;"></div>
        <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button id="btnCancelPath" class="btn" style="padding:8px 16px;">取消</button>
            <button id="btnSavePath" class="btn btn-primary" style="padding:8px 16px;">保存</button>
        </div>
    `;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    const input = document.getElementById('newVulhubPath');
    const msgEl = document.getElementById('pathValidationMsg');

    // 预填当前路径
    const currentDisplay = document.getElementById('vulhubPathDisplay');
    if (currentDisplay && currentDisplay.textContent) {
        input.value = currentDisplay.textContent;
    }

    const close = () => {
        document.body.removeChild(overlay);
    };

    document.getElementById('btnCancelPath').onclick = close;
    overlay.onclick = (e) => { if (e.target === overlay) close(); };

    document.getElementById('btnSavePath').onclick = async () => {
        const newPath = input.value.trim();
        if (!newPath) {
            msgEl.textContent = '请输入路径';
            msgEl.style.color = '#ef4444';
            return;
        }

        try {
            const resp = await fetch('/api/vulhub-path', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: newPath})
            });
            const data = await resp.json();

            if (data.success) {
                const display = document.getElementById('vulhubPathDisplay');
                if (display) {
                    display.textContent = data.path;
                    display.title = data.path;
                }
                showNotification('Vulhub 路径已更新，正在重新扫描...', 'success');
                close();
                await forceRescan();
            } else {
                msgEl.textContent = data.error || '保存失败';
                msgEl.style.color = '#ef4444';
            }
        } catch (e) {
            msgEl.textContent = '请求失败: ' + e.message;
            msgEl.style.color = '#ef4444';
        }
    };

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('btnSavePath').click();
        }
    });

    setTimeout(() => input.focus(), 100);
}