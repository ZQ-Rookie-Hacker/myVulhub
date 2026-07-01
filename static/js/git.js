/**
 * git.js — Git 同步、配置、Vulhub 路径管理
 */

// ====== Vulhub 路径配置 ======
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
    overlay.className = 'overlay-backdrop path-dialog';

    const dialog = document.createElement('div');
    dialog.className = 'dialog-card';
    dialog.innerHTML = `
        <h3>📂 配置 Vulhub 路径</h3>
        <p style="color:#6b7280;font-size:13px;margin:0 0 16px 0;">
            请先克隆 vulhub 仓库到你想要的目录，然后在此输入路径。
        </p>
        <div style="margin-bottom:12px;">
            <label class="form-label">Vulhub 目录路径:</label>
            <input id="newVulhubPath" class="form-input" placeholder="例如: /opt/vulhub 或 ../vulhub" />
        </div>
        <div id="pathValidationMsg" style="font-size:12px;margin-bottom:12px;min-height:18px;"></div>
        <div class="dialog-actions">
            <button id="btnCancelPath" class="btn">取消</button>
            <button id="btnSavePath" class="btn btn-primary">保存</button>
        </div>`;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    const input = document.getElementById('newVulhubPath');
    const msgEl = document.getElementById('pathValidationMsg');

    const currentDisplay = document.getElementById('vulhubPathDisplay');
    if (currentDisplay && currentDisplay.textContent) {
        input.value = currentDisplay.textContent;
    }

    function closeOverlay() {
        if (overlay.parentNode) overlay.remove();
    }

    document.getElementById('btnCancelPath').onclick = closeOverlay;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeOverlay(); });

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
                closeOverlay();
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
        if (e.key === 'Enter') document.getElementById('btnSavePath').click();
    });

    setTimeout(() => input.focus(), 100);
}

// ====== Git 同步 ======
function showGitSyncModal() {
    // 清理旧的 modal（单例模式）
    const existing = document.getElementById('gitSyncModal');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'gitSyncModal';
    overlay.className = 'overlay-backdrop git-sync';

    const dialog = document.createElement('div');
    dialog.className = 'dialog-card git-sync';
    dialog.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <h3 style="margin:0;">🔄 Git 同步</h3>
            <button id="settingsBtn" class="btn-icon" title="Git 设置">⚙️</button>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">同步方式:</label>
            <select id="syncMethod" class="form-select">
                <option value="https">HTTPS</option>
                <option value="ssh">SSH</option>
                <option value="gh">GitHub CLI</option>
            </select>
        </div>

        <div class="settings-info">
            <div style="display:flex;align-items:center;margin-bottom:8px;">
                <span style="background:#007bff;color:#fff;padding:4px 8px;border-radius:4px;font-size:.8em;font-weight:600;margin-right:8px;">📋</span>
                <span style="font-weight:600;color:#495057;">当前设置</span>
            </div>
            <div class="settings-row">
                <span class="settings-label">远程仓库:</span>
                <span id="currentSettings" class="settings-value" style="background:rgba(0,123,255,.1);color:#0056b3;">https://github.com/vulhub/vulhub.git</span>
            </div>
            <div id="proxySettings" class="settings-row" style="display:none;">
                <span class="settings-label">代理设置:</span>
                <span class="settings-value" style="background:rgba(108,117,125,.1);color:#6c757d;">未启用</span>
            </div>
            <div class="settings-hint">点击右上角 ⚙️ 图标可修改设置</div>
        </div>

        <div class="dialog-actions">
            <button id="btnCloseSync" class="btn">取消</button>
            <button id="btnStartSync" class="btn btn-primary">开始同步</button>
        </div>`;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    document.getElementById('settingsBtn').onclick = showGitSettingsModal;
    document.getElementById('btnCloseSync').onclick = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    document.getElementById('btnStartSync').onclick = startGitSync;

    document.getElementById('syncMethod').addEventListener('change', loadCurrentSettings);
    loadCurrentSettings();
}

async function loadCurrentSettings() {
    const method = document.getElementById('syncMethod').value;
    const currentSettings = document.getElementById('currentSettings');
    const proxySettings = document.getElementById('proxySettings');

    try {
        const response = await fetch('/api/git-config');
        const config = await response.json();
        let remoteUrl = config.remote_url || 'https://github.com/vulhub/vulhub.git';
        let useProxy = config.use_proxy || false;

        const colors = {
            ssh: { bg: 'rgba(220,53,69,.1)', color: '#dc3545', defaultUrl: 'git@github.com:vulhub/vulhub.git' },
            https: { bg: 'rgba(0,123,255,.1)', color: '#0056b3', defaultUrl: 'https://github.com/vulhub/vulhub.git' },
            gh: { bg: 'rgba(40,167,69,.1)', color: '#28a745', defaultUrl: 'vulhub/vulhub' }
        };

        if ((method === 'ssh' && !remoteUrl.startsWith('git@')) ||
            (method === 'https' && !remoteUrl.startsWith('https://'))) {
            remoteUrl = colors[method]?.defaultUrl || remoteUrl;
        }

        currentSettings.textContent = remoteUrl;
        currentSettings.style.background = colors[method]?.bg || '';
        currentSettings.style.color = colors[method]?.color || '';

        if (method === 'https') {
            proxySettings.style.display = 'flex';
            const proxySpan = proxySettings.querySelector('span:last-child');
            if (proxySpan) {
                if (useProxy) {
                    proxySpan.textContent = '已启用 (proxychains4)';
                    proxySpan.style.background = 'rgba(40,167,69,.1)';
                    proxySpan.style.color = '#28a745';
                } else {
                    proxySpan.textContent = '未启用';
                    proxySpan.style.background = 'rgba(108,117,125,.1)';
                    proxySpan.style.color = '#6c757d';
                }
            }
        } else {
            proxySettings.style.display = 'none';
        }
    } catch (error) {
        console.error('加载设置失败:', error);
        const defaults = { ssh: 'git@github.com:vulhub/vulhub.git', https: 'https://github.com/vulhub/vulhub.git', gh: 'vulhub/vulhub' };
        currentSettings.textContent = defaults[method] || defaults.https;
        if (method === 'https') {
            proxySettings.style.display = 'flex';
            const proxySpan = proxySettings.querySelector('span:last-child');
            if (proxySpan) proxySpan.textContent = '未启用';
        } else {
            proxySettings.style.display = 'none';
        }
    }
}

// ====== Git 设置弹窗 ======
function showGitSettingsModal() {
    const existing = document.getElementById('gitSettingsOverlay');
    if (existing) existing.remove();

    const syncMethodEl = document.getElementById('syncMethod');
    const currentMethod = syncMethodEl ? syncMethodEl.value : 'https';
    const defaultUrl = currentMethod === 'ssh'
        ? 'git@github.com:vulhub/vulhub.git'
        : 'https://github.com/vulhub/vulhub.git';
    const placeholder = currentMethod === 'ssh'
        ? '例如: git@github.com:vulhub/vulhub.git'
        : '例如: https://github.com/vulhub/vulhub.git';

    const overlay = document.createElement('div');
    overlay.id = 'gitSettingsOverlay';
    overlay.className = 'overlay-backdrop';
    overlay.style.zIndex = '10001';

    const dialog = document.createElement('div');
    dialog.className = 'dialog-card';
    dialog.innerHTML = `
        <h3>⚙️ Git 设置</h3>
        <div style="margin-bottom:16px;">
            <label class="form-label">远程仓库 URL:</label>
            <input type="text" id="remoteUrlInput" class="form-input" placeholder="${placeholder}" value="${defaultUrl}">
        </div>
        ${currentMethod === 'https' ? `
        <div style="margin-bottom:16px;">
            <label class="form-label">使用代理:</label>
            <label style="display:flex;align-items:center;gap:8px;">
                <input type="checkbox" id="useProxyCheckbox">
                <span>通过 proxychains4 使用代理</span>
            </label>
        </div>` : ''}
        <div class="dialog-actions">
            <button id="btnCancelSettings" class="btn">取消</button>
            <button id="btnSaveSettings" class="btn btn-primary">保存设置</button>
        </div>`;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    function closeOverlay() { if (overlay.parentNode) overlay.remove(); }

    document.getElementById('btnCancelSettings').onclick = closeOverlay;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeOverlay(); });
    document.getElementById('btnSaveSettings').onclick = saveGitSettings;

    loadCurrentGitSettings(currentMethod);
}

async function loadCurrentGitSettings(method) {
    try {
        const response = await fetch('/api/git-config');
        const config = await response.json();
        const remoteUrlInput = document.getElementById('remoteUrlInput');
        const useProxyCheckbox = document.getElementById('useProxyCheckbox');
        if (remoteUrlInput && config.remote_url) remoteUrlInput.value = config.remote_url;
        if (useProxyCheckbox && config.use_proxy !== undefined) useProxyCheckbox.checked = config.use_proxy;
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
            body: JSON.stringify({ remote_url: remoteUrl, use_proxy: useProxy, protocol: currentMethod })
        });
        const result = await response.json();
        if (result.success) {
            showNotification('设置保存成功', 'success');
            const settingsOverlay = document.getElementById('gitSettingsOverlay');
            if (settingsOverlay) settingsOverlay.remove();
            loadCurrentSettings();
        } else {
            showNotification('设置保存失败: ' + result.error, 'error');
        }
    } catch (error) {
        showNotification('保存设置异常: ' + error.message, 'error');
    }
}

async function startGitSync() {
    const method = document.getElementById('syncMethod').value;

    try {
        const response = await fetch('/api/git-config');
        const config = await response.json();
        let remoteUrl = config.remote_url;
        const useProxy = config.use_proxy || false;

        if (!remoteUrl) {
            const defaults = { ssh: 'git@github.com:vulhub/vulhub.git', https: 'https://github.com/vulhub/vulhub.git', gh: 'vulhub/vulhub' };
            remoteUrl = defaults[method] || 'https://github.com/vulhub/vulhub.git';
        }

        let effectiveMethod = (method === 'https' && useProxy) ? 'https_proxy' : method;

        const syncModal = document.getElementById('gitSyncModal');
        if (syncModal) syncModal.remove();

        showProgressModal();
        appendProgress(`[Info] 开始 Git 同步...`);
        appendProgress(`[Info] 同步方式: ${effectiveMethod}`);
        appendProgress(`[Info] 远程仓库: ${remoteUrl}`);
        if (useProxy && method === 'https') appendProgress('[Info] 代理设置: 已启用 (proxychains4)');

        const syncResp = await fetch('/api/git-sync', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({method: effectiveMethod, remote_url: remoteUrl})
        });
        const result = await syncResp.json();

        if (result.success) {
            appendProgress(`[Success] ${result.message || '同步成功'}`);
            if (result.output) appendProgress(result.output);

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
                    if (result.changes.changed_cves && result.changes.changed_cves.length > 0) {
                        appendProgress('[Info] 🔥 变更的CVE环境:');
                        result.changes.changed_cves.forEach(cve => {
                            const emoji = cve.type === '新增' ? '🆕' : (cve.type === '删除' ? '🗑️' : '📝');
                            appendProgress(`[Info]   ${emoji} ${cve.cve} (${cve.type}) - ${cve.path}`);
                        });
                    }
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
}
