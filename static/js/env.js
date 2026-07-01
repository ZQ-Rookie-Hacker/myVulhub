/**
 * env.js — 环境列表渲染、分页、启停、详情、镜像操作
 */

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

            const meta = document.createElement('div');
            meta.className = 'env-meta';

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

            if (env && env.has_exploit) {
                const exp = document.createElement('span');
                exp.className = 'tag tag-exploit';
                exp.textContent = '💣 漏洞利用脚本';
                meta.appendChild(exp);
            }

            if (env && env.has_docker_images) {
                const dockerTag = document.createElement('span');
                dockerTag.className = 'tag tag-docker';
                dockerTag.textContent = '🐳 已有镜像';
                meta.appendChild(dockerTag);
            }

            const pathTag = document.createElement('span');
            pathTag.className = 'tag';
            pathTag.textContent = `📁 ${env?.name || ''}`;
            meta.appendChild(pathTag);

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

            if (env && env.has_exploit) {
                const btnExploit = document.createElement('button');
                btnExploit.className = 'btn';
                btnExploit.textContent = '💣 漏洞利用脚本';
                btnExploit.onclick = () => showExploit(env.name);
                actions.appendChild(btnExploit);
            }

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
    html += `<button class="btn-page ${currentPage === 1 ? 'disabled' : ''}"
              onclick="changePage(${Math.max(1, currentPage - 1)})"
              ${currentPage === 1 ? 'disabled' : ''}>← 上一页</button>`;

    const maxVisiblePages = 7;
    let startPage = Math.max(1, currentPage - 3);
    let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(1, endPage - maxVisiblePages + 1);
    }

    if (startPage > 1) {
        html += `<button class="btn-page" onclick="changePage(1)">1</button>`;
        if (startPage > 2) html += '<span class="page-ellipsis">...</span>';
    }
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="btn-page ${i === currentPage ? 'active' : ''}" onclick="changePage(${i})">${i}</button>`;
    }
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += '<span class="page-ellipsis">...</span>';
        html += `<button class="btn-page" onclick="changePage(${totalPages})">${totalPages}</button>`;
    }

    html += `<button class="btn-page ${currentPage === totalPages ? 'disabled' : ''}"
              onclick="changePage(${Math.min(totalPages, currentPage + 1)})"
              ${currentPage === totalPages ? 'disabled' : ''}>下一页 →</button>`;

    html += `<div class="page-jump">
        跳至 <input type="number" id="pageJumpInput" min="1" max="${totalPages}" value="${currentPage}"
                    onkeypress="if(event.key==='Enter') jumpToPage()">
        <button class="btn-page" onclick="jumpToPage()">Go</button></div>`;

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

// === 启停 ===
async function startEnv(name) {
    try {
        showLoading(true);
        const ci = await fetch(`/api/check-images?name=${encodeURIComponent(name)}`).then(r => r.json());
        showLoading(false);

        if (!ci.success) throw new Error(ci.error || "check-images 失败");
        const missing = ci.missing || [];

        let useProxyForPull = false;
        if (missing.length > 0) {
            const shouldPull = await showImagePullDialog('需要下载镜像',
                `${missing.join("\n- ")}`, missing);
            if (!shouldPull.pull) {
                showNotification('用户取消了镜像拉取操作', 'info');
                return;
            }
            useProxyForPull = shouldPull.useProxy;
            showProgressModal();
            appendProgress(`[Info] 开始下载镜像：\n- ${missing.join("\n- ")}`);
            appendProgress(`[Info] 使用${useProxyForPull ? 'proxychains4代理' : '直接连接'}拉取镜像...`);
            await pullWithProgress(name, useProxyForPull);
        }

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
                let message = '端口已被占用';
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

        const wait = await fetch(`/api/wait-ready?name=${encodeURIComponent(name)}&timeout=20`).then(r => r.json());
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

function openEnv(port) {
    const currentHost = window.location.hostname;
    const currentProtocol = window.location.protocol;
    window.open(`${currentProtocol}//${currentHost}:${port}`, '_blank');
}

// === 详情 & Exploit ===
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
            <h2>${escapeHtml(env.name)}</h2>
            <div class="env-meta" style="margin:1rem 0;">
                <span class="tag">分类: ${escapeHtml(env.category)}</span>
                <span class="tag">CVE: ${escapeHtml(env.cve)}</span>
                ${env.exploit_files && env.exploit_files.length > 0 ?
                    `<span class="tag tag-exploit">漏洞利用脚本: ${escapeHtml(env.exploit_files.join(', '))}</span>` : ''}
            </div>`;

        if (env.images && env.images.length > 0) {
            content += '<h3>截图</h3>';
            env.images.forEach(img => {
                content += `<img src="${img.data}" class="screenshot" alt="${escapeHtml(img.name)}" loading="lazy">`;
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

        let content = `<h2>漏洞利用脚本 - ${escapeHtml(name)}</h2>
        <div style="background:#fef3c7;color:#78350f;padding:12px;border-radius:8px;margin:10px 0;">
            ⚠️ <strong>警告</strong>：仅供学术研究与授权测试使用，使用者需自负法律责任
        </div>`;

        exploits.forEach(exploit => {
            content += `
                <div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin:12px 0;">
                    <h3 style="margin-top:0;">${escapeHtml(exploit.filename)}</h3>
                    <div style="margin:8px 0;">
                        <span class="tag">大小: ${exploit.size} 字节</span>
                        <span class="tag">行数: ${exploit.lines}</span>
                        <span class="tag">路径: ${escapeHtml(exploit.path)}</span>
                    </div>
                    ${exploit.usage ? `<div style="background:#f3f4f6;padding:8px;border-radius:6px;margin:8px 0;">
                        <strong>使用说明：</strong> ${escapeHtml(exploit.usage)}</div>` : ''}
                    <h4>代码：</h4>
                    <pre class="code-block" style="max-height:400px;overflow:auto;">${escapeHtml(exploit.content)}</pre>
                </div>`;
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

function closeModal() {
    const m = document.getElementById('detailModal');
    if (m) m.style.display = 'none';
}

window.onclick = function(event) {
    const modal = document.getElementById('detailModal');
    if (event.target === modal) modal.style.display = 'none';
};

// === 镜像管理 ===
async function removeImages(name) {
    if (!confirm(`确定要删除环境 "${name}" 的所有镜像吗？\n\n⚠️ 此操作不可逆！\n镜像删除后将需要重新下载。`)) return;

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

// === SSE 镜像拉取 ===
function pullWithProgress(name, useProxy = false) {
    const proxyParam = useProxy ? '&proxy=true' : '';
    return new Promise((resolve, reject) => {
        const es = new EventSource(`/api/pull-stream?name=${encodeURIComponent(name)}${proxyParam}`);
        let settled = false;
        es.addEventListener('log', (ev) => appendProgress(ev.data));
        es.addEventListener('done', (ev) => {
            if (settled) return;
            settled = true;
            es.close();
            if (ev.data === 'error') {
                appendProgress('[Error] 镜像下载失败，请检查网络或代理配置');
                reject(new Error('pull 失败'));
            } else {
                appendProgress('[OK] 镜像下载完成');
                resolve();
            }
        });
        es.onerror = () => {
            if (settled) return;
            settled = true;
            es.close();
            appendProgress('[Error] 下载中断');
            reject(new Error('pull 失败'));
        };
    });
}

// === 镜像拉取对话框（使用 CSS 类替代内联样式） ===
function showImagePullDialog(title, message, missingImages) {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'overlay-backdrop pull-dialog';

        const dialog = document.createElement('div');
        dialog.className = 'dialog-card pull-dialog';

        // 标题
        const titleEl = document.createElement('h3');
        titleEl.className = 'pull-title';
        titleEl.innerHTML = '🐳 ' + title;

        // 消息
        const messageEl = document.createElement('p');
        messageEl.style.cssText = 'white-space:pre-line;margin-bottom:16px;color:#334155;line-height:1.5;';
        messageEl.textContent = message;

        dialog.appendChild(titleEl);
        dialog.appendChild(messageEl);

        // 缺失镜像列表
        if (missingImages && missingImages.length > 0) {
            const imageList = document.createElement('div');
            imageList.className = 'image-list-box';

            const listTitle = document.createElement('h4');
            listTitle.innerHTML = '📦 缺失的镜像:';
            imageList.appendChild(listTitle);

            const ul = document.createElement('ul');
            missingImages.forEach(img => {
                const li = document.createElement('li');
                li.textContent = img;
                ul.appendChild(li);
            });
            imageList.appendChild(ul);
            dialog.appendChild(imageList);
        }

        // 代理选项
        const proxyContainer = document.createElement('div');
        proxyContainer.className = 'proxy-option';

        const proxyCheckbox = document.createElement('input');
        proxyCheckbox.type = 'checkbox';
        proxyCheckbox.id = 'useProxyCheckbox';

        const customCb = document.createElement('span');
        customCb.className = 'custom-checkbox';
        customCb.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            proxyCheckbox.checked = !proxyCheckbox.checked;
            proxyCheckbox.dispatchEvent(new Event('change'));
        });

        const proxyLabel = document.createElement('label');
        proxyLabel.textContent = 'proxychains4';
        proxyLabel.className = 'check-label';

        proxyContainer.appendChild(proxyCheckbox);
        proxyContainer.appendChild(customCb);
        proxyContainer.appendChild(proxyLabel);
        dialog.appendChild(proxyContainer);

        // 提示
        const hint = document.createElement('small');
        hint.className = 'hint-box';
        hint.textContent = '💡 提示：如果网络受限无法拉取镜像，请勾选此项并确保已配置好proxychains4';
        dialog.appendChild(hint);

        // 按钮
        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'dialog-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn';
        cancelBtn.textContent = '❌ 取消';
        cancelBtn.onclick = () => cleanup(false, false);

        const confirmBtn = document.createElement('button');
        confirmBtn.className = 'btn btn-success';
        confirmBtn.textContent = '✅ 确定';
        confirmBtn.onclick = () => cleanup(true, proxyCheckbox.checked);

        buttonContainer.appendChild(cancelBtn);
        buttonContainer.appendChild(confirmBtn);
        dialog.appendChild(buttonContainer);

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        function cleanup(pull, useProxy) {
            if (overlay.parentNode) overlay.remove();
            resolve({ pull, useProxy });
        }

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) cleanup(false, false);
        });

        setTimeout(() => confirmBtn.focus(), 100);
    });
}
