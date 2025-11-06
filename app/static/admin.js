function showLoader() {
    document.getElementById('loader').style.display = 'flex';
}

function hideLoader() {
    document.getElementById('loader').style.display = 'none';
}
document.addEventListener('DOMContentLoaded', function() {
    const token = localStorage.getItem('admin-token');
    if (!token) {
        alert('请先登录');
        window.location.href = '/';
        return;
    }

    fetch('/admin/env', {
        headers: {
            'Authorization': 'Bearer ' + token
        }
    })
        .then(response => {
            if (response.status === 401) {
                alert('会话已过期，请重新登录');
                window.location.href = '/';
                throw new Error('Unauthorized');
            }
            if (!response.ok) {
                throw new Error('网络响应错误');
            }
            return response.json();
        })
        .then(data => {
            // --- Start of optimization ---
            // Pass the fetched data to the functions that need it
            buildSettingsForm(data);
            loadGeminiKeys(data);
            // --- End of optimization ---

        })
        .catch(error => {
            console.error('获取配置失败:', error);
            alert('加载配置信息失败，请检查网络或联系管理员。');
        });
    
    loadApiMappings();
    loadAccessKeys();
    // loadGeminiKeys(); // This call is moved into the main fetch chain
    // 获取本地存储的详情
    fetchStorageDetails('local');
    // 获取本地存储图片
    fetchMedia(1, 'local', 10);

    document.querySelectorAll('.category-header').forEach(header => {
        header.addEventListener('click', function() {
            this.nextElementSibling.classList.toggle('show');
            this.querySelector('.toggle-icon').classList.toggle('rotate');
        });
    });
});

// --- Modal Logic ---
const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modal-title');
const modalText = document.getElementById('modal-text');
const modalConfirmBtn = document.getElementById('modal-confirm-btn');
const modalCancelBtn = document.getElementById('modal-cancel-btn');
const modalCloseBtn = document.querySelector('.modal-close');
// Input containers
const modalSingleInputContainer = document.getElementById('modal-single-input-container');
const modalTextareaContainer = document.getElementById('modal-textarea-container');
const modalMappingContainer = document.getElementById('modal-mapping-container');
// Inputs
const modalInput = document.getElementById('modal-input');
const modalTextarea = document.getElementById('modal-textarea');
const modalInputPrefix = document.getElementById('modal-input-prefix');
const modalInputTarget = document.getElementById('modal-input-target');

let resolvePromise;

function showModal() {
    modal.style.display = 'block';
}

function hideModal() {
    modal.style.display = 'none';
    resolvePromise = null; // Clear the resolver when hiding
}

function handleModalClose() {
    if (resolvePromise) {
        resolvePromise(null);
    }
    hideModal();
}

modalCloseBtn.onclick = handleModalClose;
window.onclick = function(event) {
    if (event.target == modal) {
        handleModalClose();
    }
};

function showConfirm(title, text) {
    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;
        modalText.textContent = text;
        
        modalText.style.display = 'block';
        modalSingleInputContainer.style.display = 'none';
        modalTextareaContainer.style.display = 'none';
        modalMappingContainer.style.display = 'none';
        document.getElementById('modal-access-key-container').style.display = 'none';

        modalConfirmBtn.onclick = () => {
            if (resolvePromise) resolve(true);
            hideModal();
        };
        modalCancelBtn.onclick = () => {
            if (resolvePromise) resolve(false);
            hideModal();
        };
        showModal();
    });
}

function showPrompt(options) {
    const {
        title,
        text,
        defaultValue = '',
        inputType = 'text',
        confirmText = '确认',
        cancelText = '取消'
    } = options;

    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;
        modalText.textContent = text;
        modalText.style.display = text ? 'block' : 'none';

        modalSingleInputContainer.style.display = 'block';
        modalTextareaContainer.style.display = 'none';
        modalMappingContainer.style.display = 'none';
        document.getElementById('modal-access-key-container').style.display = 'none';
        
        modalInput.value = defaultValue;
        modalInput.type = inputType;
        modalInput.focus();
        modalConfirmBtn.textContent = confirmText;
        modalCancelBtn.textContent = cancelText;
        modalConfirmBtn.onclick = () => {
            if (resolvePromise) resolve(modalInput.value);
            hideModal();
        };
        modalCancelBtn.onclick = () => {
            if (resolvePromise) resolve(null);
            hideModal();
        };
        showModal();
    });
}

function showTextareaPrompt(options) {
    const {
        title,
        text,
        defaultValue = '',
        confirmText = '确认',
        cancelText = '取消'
    } = options;

    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;
        modalText.textContent = text;
        modalText.style.display = text ? 'block' : 'none';

        modalSingleInputContainer.style.display = 'none';
        modalTextareaContainer.style.display = 'block';
        modalMappingContainer.style.display = 'none';
        document.getElementById('modal-access-key-container').style.display = 'none';
        
        modalTextarea.value = defaultValue;
        modalTextarea.focus();

        modalConfirmBtn.textContent = confirmText;
        modalCancelBtn.textContent = cancelText;

        modalConfirmBtn.onclick = () => {
            if (resolvePromise) resolve(modalTextarea.value);
            hideModal();
        };
        modalCancelBtn.onclick = () => {
            if (resolvePromise) resolve(null);
            hideModal();
        };
        showModal();
    });
}

const token = localStorage.getItem('admin-token');

function loadApiMappings() {
    fetch('/admin/api_mappings', {
        headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(response => response.json())
    .then(data => {
        const tbody = document.querySelector('#api-mappings-table tbody');
        tbody.innerHTML = '';
        Object.keys(data).forEach((prefix, index) => {
            const row = `
                <tr>
                    <td>${index + 1}</td>
                    <td>${prefix}</td>
                    <td>${data[prefix]}</td>
                    <td>
                        <button type="button" class="action-btn edit-btn" onclick="editApiMapping('${prefix}', '${data[prefix]}')">✏️</button>
                        <button type="button" class="action-btn delete-btn" onclick="deleteApiMapping('${prefix}')">🗑️</button>
                    </td>
                </tr>
            `;
            tbody.innerHTML += row;
        });
    });
}

function showMappingPrompt(title, prefix = '', target = '') {
    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;
        modalText.style.display = 'none';
        modalSingleInputContainer.style.display = 'none';
        modalMappingContainer.style.display = 'block';

        modalInputPrefix.value = prefix;
        modalInputTarget.value = target;
        modalInputPrefix.focus();

        modalConfirmBtn.onclick = () => {
            const prefixVal = modalInputPrefix.value.trim();
            const targetVal = modalInputTarget.value.trim();
            if (!prefixVal || !targetVal) {
                alert('请求前缀和目标地址不能为空。');
                return; // Keep modal open
            }
            if (resolvePromise) resolve({ prefix: prefixVal, target_url: targetVal });
            hideModal();
        };

        modalCancelBtn.onclick = () => {
            if (resolvePromise) resolve(null);
            hideModal();
        };
        showModal();
    });
}

async function addApiMapping() {
    const result = await showMappingPrompt("添加新映射");
    if (!result) return;

    showLoader();
    fetch('/admin/api_mappings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({ prefix: result.prefix, target_url: result.target_url })
    })
    .then(handleApiResponse)
    .then(loadApiMappings)
    .finally(hideLoader);
}

async function editApiMapping(oldPrefix, oldUrl) {
    const result = await showMappingPrompt("编辑映射", oldPrefix, oldUrl);
    if (!result) return;

    showLoader();
    fetch('/admin/api_mappings', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({
            old_prefix: oldPrefix,
            new_prefix: result.prefix,
            target_url: result.target_url
        })
    })
    .then(handleApiResponse)
    .then(loadApiMappings)
    .finally(hideLoader);
}

async function deleteApiMapping(prefix) {
    const confirmed = await showConfirm("确认删除", `确定要删除映射 ${prefix} 吗?`);
    if (!confirmed) return;
    
    // 从第二个字符开始，以移除开头的'/'
    const encodedPrefix = encodeURIComponent(prefix.substring(1));

    showLoader();
    fetch(`/admin/api_mappings/${encodedPrefix}`, {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(handleApiResponse)
    .then(loadApiMappings)
    .finally(hideLoader);
}

function handleApiResponse(response) {
    return response.json().then(result => {
        if (!response.ok) {
            alert(`错误: ${result.detail || '未知错误'}`);
            throw new Error(result.detail);
        }
        alert(result.message || '操作成功');
        return result;
    });
}

async function saveGroupSettings(groupContentElement) {
    const password = await showPrompt({title: "确认更改", text: "请输入管理员密码以保存更改:", defaultValue: '', inputType: 'password'});
    if (password === null) {
        return;
    }

    const inputs = groupContentElement.querySelectorAll('input, select');
    const data = {};
    inputs.forEach(input => {
        if (input.type === 'radio') {
            if (input.checked) {
                data[input.name] = input.value;
            }
        } else {
            data[input.name] = input.value;
        }
    });
    data.password = password;

    const token = localStorage.getItem('admin-token');
    showLoader();
    try {
        const response = await fetch('/admin/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        alert(result.message || "发生未知错误");
        if (response.ok) {
            window.location.reload();
        }
    } catch (error) {
        console.error('更新失败:', error);
        alert('更新失败，请查看浏览器控制台获取更多信息。');
    } finally {
        hideLoader();
    }
}

let currentGeminiKeys = [];
let originalGeminiKeys = []; // 存储原始数据，用于比较是否有修改
let allAccessKeys = {};
let originalAccessKeys = {}; // 存储原始数据，用于比较是否有修改
let accessKeyFilterState = 0; // 0: 全部, 1: 有效, 2: 无效

// 数据修改状态
let geminiKeysModified = false;
let invalidKeys = [];

// The function now accepts the environment data as an argument
function loadGeminiKeys(data) {
    try {
        const categoryName = 'API与访问控制';
        const keysString = data[categoryName] && data[categoryName].GEMINI_API_KEYS ? data[categoryName].GEMINI_API_KEYS.value : '';
        currentGeminiKeys = keysString ? keysString.split(',').map(k => k.trim()).filter(k => k) : [];
        originalGeminiKeys = [...currentGeminiKeys]; // 创建副本用于比较
        geminiKeysModified = false;
        renderGeminiKeys();
        updateGeminiKeysStatus();
    } catch (error) {
        console.error('解析Gemini API密钥失败:', error);
    }
}

// This new function encapsulates the form building logic
function buildSettingsForm(data) {
    const form = document.getElementById('settings-form');
    const buttonGroup = form.querySelector('.button-group');

    // This logic is extracted from the original fetch promise
    for (const category in data) {
        const categoryCard = document.createElement('div');
        categoryCard.className = 'category-card';

        const categoryHeader = document.createElement('div');
        categoryHeader.className = 'category-header';
        categoryHeader.innerHTML = `<span>${category}</span><span class="toggle-icon">▶</span>`;
        
        const categoryContent = document.createElement('div');
        categoryContent.className = 'category-content';

        const settings = data[category];
        for (const key in settings) {
            const setting = settings[key];
            const formGroup = document.createElement('div');
            formGroup.className = 'form-group';

            const label = document.createElement('label');
            label.htmlFor = key;
            label.textContent = setting.label;

            formGroup.appendChild(label);

            if (setting.description && !(setting.type === 'radio' && setting.options)) {
                const description = document.createElement('p');
                description.className = 'setting-description';
                description.textContent = setting.description;
                formGroup.appendChild(description);
            }

            if (setting.type === 'radio' && setting.options) {
                const radioGroup = document.createElement('div');
                radioGroup.className = 'radio-group';
                setting.options.forEach(option => {
                    const radioLabel = document.createElement('label');
                    radioLabel.className = 'radio-label';

                    const radioInput = document.createElement('input');
                    radioInput.type = 'radio';
                    radioInput.name = key;
                    radioInput.value = option.value;
                    if (setting.value === option.value) {
                        radioInput.checked = true;
                    }

                    radioLabel.appendChild(radioInput);
                    radioLabel.appendChild(document.createTextNode(option.value));
                    
                    if(option.description) {
                        const descSpan = document.createElement('span');
                        descSpan.className = 'setting-description';
                        descSpan.textContent = `(${option.description})`;
                        radioLabel.appendChild(descSpan);
                    }

                    radioGroup.appendChild(radioLabel);
                });
                formGroup.appendChild(radioGroup);
            } else {
                const input = document.createElement('input');
                input.type = setting.type || 'text';
                input.id = key;
                input.name = key;
                input.value = setting.value;
                formGroup.appendChild(input);
            }
            
            categoryContent.appendChild(formGroup);
        }

        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'save-group-btn-container';

        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.textContent = '保存设置';
        saveButton.className = 'save-group-btn';
        saveButton.addEventListener('click', () => {
            saveGroupSettings(categoryContent);
        });
        
        buttonContainer.appendChild(saveButton);
        categoryContent.appendChild(buttonContainer);

        categoryCard.appendChild(categoryHeader);
        categoryCard.appendChild(categoryContent);
        form.insertBefore(categoryCard, buttonGroup);

        categoryHeader.addEventListener('click', () => {
            categoryContent.classList.toggle('show');
            const icon = categoryHeader.querySelector('.toggle-icon');
            icon.classList.toggle('rotate');
        });
    }
}

function renderGeminiKeys() {
    const tbody = document.querySelector('#gemini-keys-table tbody');
    tbody.innerHTML = '';
    currentGeminiKeys.forEach((key, index) => {
        const safeKeyId = key.replace(/[^a-zA-Z0-9]/g, '');
        const row = `
            <tr>
                <td>${index + 1}</td>
                <td id="key-cell-${safeKeyId}" class="truncate-text" title="点击复制: ${key}" onclick="copyTextToClipboard(this, '${key}')">${key}<br><span id="key-status-${safeKeyId}" class="key-status-text"></span></td>
                <td>
                    <button type="button" class="action-btn check-btn" onclick="checkKeyAvailability('${key}')">🔍</button>
                    <button type="button" class="action-btn check-btn" onclick="checkSingleKeyRealValidity('${key}')">🧪</button>
                    <button type="button" class="action-btn edit-btn" onclick="editGeminiKey('${key}')">✏️</button>
                    <button type="button" class="action-btn delete-btn" onclick="deleteGeminiKey('${key}')">🗑️</button>
                </td>
            </tr>
        `;
        tbody.innerHTML += row;
    });

    // 更新总数量显示
    const keysCountElement = document.getElementById('gemini-keys-count');
    if (keysCountElement) {
        keysCountElement.textContent = currentGeminiKeys.length;
    }

    // 同时同步更新"API与访问控制"中的输入框
    const geminiKeysInput = document.getElementById('GEMINI_API_KEYS');
    if (geminiKeysInput) {
        geminiKeysInput.value = currentGeminiKeys.join(',');
    }
}

// 更新Gemini密钥状态显示
function updateGeminiKeysStatus() {
    const statusElement = document.getElementById('gemini-keys-status');
    const saveButton = document.getElementById('save-gemini-keys-btn');
    
    if (statusElement && saveButton) {
        if (geminiKeysModified) {
            statusElement.textContent = '已修改';
            statusElement.className = 'keys-status modified';
            saveButton.style.display = 'inline-block';
        } else {
            statusElement.textContent = '';
            statusElement.className = 'keys-status';
            saveButton.style.display = 'none';
        }
    }
}

// 检查Gemini密钥是否有修改
function checkGeminiKeysModified() {
    const currentKeysSorted = [...currentGeminiKeys].sort();
    const originalKeysSorted = [...originalGeminiKeys].sort();
    geminiKeysModified = JSON.stringify(currentKeysSorted) !== JSON.stringify(originalKeysSorted);
    updateGeminiKeysStatus();
}

// 显示添加单个Gemini密钥的模态框
async function showAddGeminiKeyModal() {
    const newKey = await showPrompt({title: "添加新密钥", text: "请输入新的 Gemini API 密钥:"});
    if (newKey && newKey.trim()) {
        if (currentGeminiKeys.includes(newKey.trim())) {
            alert('该密钥已存在。');
            return;
        }
        currentGeminiKeys.push(newKey.trim());
        checkGeminiKeysModified();
        renderGeminiKeys();
    }
}

// 显示批量添加Gemini密钥的模态框
async function showBulkAddGeminiKeysModal() {
    const switchContainer = document.getElementById('bulk-delete-switch-container');
    const switchInput = document.getElementById('bulk-delete-mode-switch');
    
    switchContainer.style.display = 'flex';

    // Listener to update modal text based on the switch
    const updateConfirmButtonText = () => {
        modalConfirmBtn.textContent = switchInput.checked ? '确认删除' : '确认添加';
    };
    switchInput.addEventListener('change', updateConfirmButtonText);
    
    switchInput.checked = false;
    // Set initial button text
    updateConfirmButtonText();

    const keysText = await showTextareaPrompt({
        title: "批量操作密钥",
        text: "",
        confirmText: "确认",
    });

    // Cleanup
    switchContainer.style.display = 'none';
    switchInput.removeEventListener('change', updateConfirmButtonText);
    // Reset button text to default
    modalConfirmBtn.textContent = '确认';

    if (keysText) {
        const keys = keysText.split('\n')
            .map(k => k.trim())
            .filter(k => k); // Filter out empty lines

        if (keys.length === 0) {
            alert('没有输入有效的密钥。');
            return;
        }

        const isDeleteMode = switchInput.checked;

        if (isDeleteMode) {
            // Bulk Delete Logic
            let deletedCount = 0;
            let notFoundCount = 0;
            
            keys.forEach(keyToDelete => {
                const index = currentGeminiKeys.indexOf(keyToDelete);
                if (index > -1) {
                    currentGeminiKeys.splice(index, 1);
                    deletedCount++;
                } else {
                    notFoundCount++;
                }
            });

            if (deletedCount > 0) {
                checkGeminiKeysModified();
                renderGeminiKeys();
                alert(`成功删除 ${deletedCount} 个密钥。${notFoundCount > 0 ? `有 ${notFoundCount} 个密钥未找到。` : ''}`);
            } else {
                alert('没有找到任何要删除的密钥。');
            }
        } else {
            // Bulk Add Logic (existing logic)
            const duplicateKeys = keys.filter(k => currentGeminiKeys.includes(k));
            if (duplicateKeys.length > 0) {
                const confirmResult = await showConfirm(
                    "发现重复密钥",
                    `以下密钥已存在：\n${duplicateKeys.join('\n')}\n\n是否跳过重复的密钥并添加其余密钥？`
                );
                if (!confirmResult) return;
            }

            const uniqueNewKeys = keys.filter(k => !currentGeminiKeys.includes(k));
            currentGeminiKeys.push(...uniqueNewKeys);

            checkGeminiKeysModified();
            renderGeminiKeys();

            alert(`成功添加 ${uniqueNewKeys.length} 个新密钥${duplicateKeys.length > 0 ? `，跳过 ${duplicateKeys.length} 个重复密钥` : ''}。`);
        }
    }
}

// 保存Gemini密钥到服务器
async function saveGeminiKeysToServer() {
    if (!geminiKeysModified) {
        alert('没有需要保存的更改。');
        return;
    }
    
    const password = await showPrompt({title: "确认保存", text: "为确认更改，请输入管理员密码:", defaultValue: '', inputType: 'password'});
    if (password === null) {
        return;
    }

    const keysString = currentGeminiKeys.join(',');
    const data = {
        'GEMINI_API_KEYS': keysString,
        'password': password
    };

    showLoader();
    try {
        const response = await fetch('/admin/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        
        if (response.ok) {
            originalGeminiKeys = [...currentGeminiKeys];
            geminiKeysModified = false;
            updateGeminiKeysStatus();
            alert('保存成功！');
        } else {
            alert('保存失败：' + (result.detail || '未知错误'));
        }
    } catch (error) {
        console.error('更新失败:', error);
        alert('更新失败，请查看浏览器控制台获取更多信息。');
    } finally {
        hideLoader();
    }
}

async function addGeminiKey() {
    // 保留原函数以兼容现有代码，但重定向到新函数
    await showAddGeminiKeyModal();
}

async function editGeminiKey(oldKey) {
    const newKey = await showPrompt({title: "编辑密钥", text: "请编辑 Gemini API 密钥:", defaultValue: oldKey});
    if (newKey && newKey.trim() && newKey.trim() !== oldKey) {
        const index = currentGeminiKeys.indexOf(oldKey);
        if (index !== -1) {
            if (currentGeminiKeys.includes(newKey.trim())) {
                alert('该密钥已存在。');
                return;
            }
            currentGeminiKeys[index] = newKey.trim();
            checkGeminiKeysModified();
            renderGeminiKeys();
        }
    }
}

async function deleteGeminiKey(keyToDelete) {
    const confirmed = await showConfirm("确认删除", `确定要删除密钥 "${keyToDelete}" 吗?`);
    if (confirmed) {
        currentGeminiKeys = currentGeminiKeys.filter(key => key !== keyToDelete);
        checkGeminiKeysModified();
        renderGeminiKeys();
    }
}

async function saveGeminiKeys() {
    const password = await showPrompt({title: "确认操作", text: "为确认更改，请输入管理员密码:", defaultValue: '', inputType: 'password'});
    if (password === null) {
        // 用户取消输入密码，不需要任何操作，因为更改尚未应用
        return;
    }

    const keysString = currentGeminiKeys.join(',');
    const data = {
        'GEMINI_API_KEYS': keysString,
        'password': password
    };

    showLoader();
    try {
        const response = await fetch('/admin/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        alert(result.message || "发生未知错误");
        if (response.ok) {
            renderGeminiKeys();
        } else {
            alert('保存失败，将重新加载密钥列表。');
        }
    } catch (error) {
        console.error('更新失败:', error);
        alert('更新失败，请查看浏览器控制台获取更多信息。');
    } finally {
        hideLoader();
    }
}

async function checkKeyAvailability(key) {
    const safeKeyId = key.replace(/[^a-zA-Z0-9]/g, '');
    const statusSpan = document.getElementById(`key-status-${safeKeyId}`);
    const keyCell = document.getElementById(`key-cell-${safeKeyId}`);

    // 重置样式
    statusSpan.textContent = '正在检查...';
    statusSpan.style.color = '#4a90e2';
    if (keyCell) {
        keyCell.style.color = 'inherit';
        keyCell.style.fontWeight = 'normal';
    }

    try {
        const response = await fetch('/admin/check_gemini_key', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({ key: key })
        });
        const result = await response.json();
        
        const applyStyle = (color) => {
            statusSpan.style.color = color;
            if (keyCell) {
                keyCell.style.color = color;
                keyCell.style.fontWeight = 'bold';
            }
        };

        if (response.ok) {
            if (result.valid) {
                statusSpan.textContent = `检查结果: ${result.message}`;
                applyStyle('green');
            } else {
                statusSpan.textContent = `检查结果: ${result.message}`;
                applyStyle('red');
                if (!invalidKeys.includes(key)) {
                    invalidKeys.push(key);
                }
                updateDeleteInvalidKeysButtonVisibility();
            }
        } else {
            statusSpan.textContent = `检查失败: ${result.detail || '未知错误'}`;
            applyStyle('red');
            if (!invalidKeys.includes(key)) {
                invalidKeys.push(key);
            }
            updateDeleteInvalidKeysButtonVisibility();
        }
    } catch (error) {
        console.error('检查密钥时出错:', error);
        statusSpan.textContent = '检查时发生网络错误。';
        applyStyle('red');
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function checkAllKeysAvailability() {
    invalidKeys = [];
    updateDeleteInvalidKeysButtonVisibility();
    const keysToCheck = [...currentGeminiKeys]; // 创建一个副本以进行迭代
    for (const key of keysToCheck) {
        await checkKeyAvailability(key);
        await sleep(200); // 每0.2秒检查一个，以避免请求过快
    }
}

async function checkAllKeysRealValidity() {
    const checkTargetContainer = document.getElementById('modal-check-target-container');
    checkTargetContainer.style.display = 'block'; // Manually show the container

    modalConfirmBtn.textContent = '确认';
    const model = await showPrompt({title: "请输入模型名称", text: "请输入要用于测试的模型的名称:", defaultValue: "gemini-2.0-flash"});
    
    checkTargetContainer.style.display = 'none'; // Manually hide it after

    if (!model) {
        return;
    }
    
    const checkTarget = document.getElementById('modal-check-target').value;

    invalidKeys = []; // 开始检查前清空列表
    updateDeleteInvalidKeysButtonVisibility();

    let keysToCheck;
    if (checkTarget === 'new') {
        // Filter for keys that are in currentGeminiKeys but not in originalGeminiKeys
        keysToCheck = currentGeminiKeys.filter(k => !originalGeminiKeys.includes(k));
        if (keysToCheck.length === 0) {
            alert('没有新增的密钥可供检查。');
            return;
        }
    } else {
        // "all" keys
        keysToCheck = [...currentGeminiKeys];
    }

    for (const key of keysToCheck) {
        await checkKeyRealValidity(key, model);
        await sleep(200);
    }
}

async function checkKeyRealValidity(key, model) {
    const safeKeyId = key.replace(/[^a-zA-Z0-9]/g, '');
    const statusSpan = document.getElementById(`key-status-${safeKeyId}`);
    const keyCell = document.getElementById(`key-cell-${safeKeyId}`);

    statusSpan.textContent = '正在检查...';
    statusSpan.style.color = '#4a90e2';
    if (keyCell) {
        keyCell.style.color = 'inherit';
        keyCell.style.fontWeight = 'normal';
    }

    try {
        const response = await fetch('/admin/check_gemini_key_real', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({ key: key, model: model })
        });
        const result = await response.json();
        
        const applyStyle = (color) => {
            statusSpan.style.color = color;
            if (keyCell) {
                keyCell.style.color = color;
                keyCell.style.fontWeight = 'bold';
            }
        };

        if (response.ok) {
            if (result.valid) {
                statusSpan.textContent = `检查结果: ${result.message}`;
                applyStyle('green');
            } else {
                statusSpan.textContent = `检查结果: ${result.message}`;
                applyStyle('red');
                if (!invalidKeys.includes(key)) {
                    invalidKeys.push(key);
                }
                updateDeleteInvalidKeysButtonVisibility();
            }
        } else {
            statusSpan.textContent = `检查失败: ${result.detail || '未知错误'}`;
            applyStyle('red');
            if (!invalidKeys.includes(key)) {
                invalidKeys.push(key);
            }
            updateDeleteInvalidKeysButtonVisibility();
        }
    } catch (error) {
        console.error('检查密钥时出错:', error);
        statusSpan.textContent = '检查时发生网络错误。';
        applyStyle('red');
    }
}

async function checkSingleKeyRealValidity(key) {
    const model = await showPrompt({title: "请输入模型名称", text: "请输入要用于测试的模型的名称:", defaultValue: "gemini-2.0-flash"});
    if (!model) {
        return;
    }
    await checkKeyRealValidity(key, model);
}
 
async function showDeleteInvalidKeysModal() {
    if (invalidKeys.length === 0) {
        alert('没有检测到无效的密钥。');
        return;
    }

    const keysToDeleteText = invalidKeys.join('\n');
    const result = await showTextareaPrompt({
        title: "确认删除无效密钥",
        text: "以下是在检查中被标记为无效的密钥。请确认是否要将它们从列表中删除。",
        defaultValue: keysToDeleteText,
        confirmText: "确认删除",
        cancelText: "取消"
    });

    if (result) {
        const keysToDelete = result.split('\n').map(k => k.trim()).filter(k => k);
        bulkDeleteGeminiKeys(keysToDelete);
    }
}

function bulkDeleteGeminiKeys(keysToDelete) {
    if (!Array.isArray(keysToDelete) || keysToDelete.length === 0) {
        alert('没有要删除的密钥。');
        return;
    }

    let deletedCount = 0;
    currentGeminiKeys = currentGeminiKeys.filter(key => {
        if (keysToDelete.includes(key)) {
            deletedCount++;
            return false;
        }
        return true;
    });

    if (deletedCount > 0) {
        checkGeminiKeysModified();
        renderGeminiKeys();
        // After deletion, update the invalidKeys array and button visibility
        invalidKeys = invalidKeys.filter(k => !keysToDelete.includes(k));
        updateDeleteInvalidKeysButtonVisibility();
        alert(`成功删除了 ${deletedCount} 个无效密钥。请记得点击“保存更改”以应用。`);
    } else {
        alert('没有找到与输入匹配的密钥。');
    }
}

function updateDeleteInvalidKeysButtonVisibility() {
    const deleteButton = document.getElementById('delete-invalid-keys-btn');
    if (deleteButton) {
        deleteButton.style.display = invalidKeys.length > 0 ? 'inline-block' : 'none';
    }
}

function logout() {
    localStorage.removeItem('admin-token');
    window.location.href = '/';
}
// --- Media Gallery Logic ---
const mediaGridContainer = document.getElementById('media-grid-container');
const paginationContainer = document.getElementById('pagination-container');
const storageTypeSelector = document.getElementById('storage-type-selector');
const galleryLoader = document.getElementById('media-loader');
const selectAllBtn = document.getElementById('select-all-media-btn');
const deleteSelectedBtn = document.getElementById('delete-selected-media-btn');

let currentPage = 1;
let currentPageSize = 10;
let currentStorageType = 'local';
let isSelectAll = false;

async function fetchMedia(page = 1, storageType = 'local', pageSize = 10) {
    currentPage = page;
    currentStorageType = storageType;
    currentPageSize = pageSize;
    galleryLoader.style.display = 'block';
    mediaGridContainer.innerHTML = '';
    paginationContainer.innerHTML = '';

    const token = localStorage.getItem('admin-token');
    try {
        const response = await fetch(`/admin/media?storage_type=${storageType}&page=${page}&page_size=${pageSize}`, {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!response.ok) {
            throw new Error('获取文件失败: ' + response.statusText);
        }
        const data = await response.json();
        renderMediaGrid(data.media_files);
        renderPagination(data.total, data.page, data.page_size);
    } catch (error) {
        console.error('Error fetching media:', error);
        mediaGridContainer.innerHTML = '<p>加载文件失败，请稍后重试。</p>';
    } finally {
        galleryLoader.style.display = 'none';
    }
}

function renderMediaGrid(media_files) {
    mediaGridContainer.innerHTML = ''; // Clear previous items
    if (media_files.length === 0) {
        mediaGridContainer.innerHTML = '<p>这里还没有文件。</p>';
        return;
    }
    media_files.forEach(media => {
        const card = document.createElement('div');
        card.className = 'media-card';

        const fileExtension = media.filename.split('.').pop().toLowerCase();
        let mediaElementHtml;

        if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'].includes(fileExtension)) {
            mediaElementHtml = `<img src="${media.url}" alt="${media.filename}" loading="lazy" data-media-type="image">`;
        } else if (['mp4', 'webm', 'ogg', 'mov'].includes(fileExtension)) {
            mediaElementHtml = `<video muted loop playsinline loading="lazy" data-media-type="video">
                                    <source src="${media.url}" type="video/${fileExtension === 'mov' ? 'quicktime' : fileExtension}">
                                    您的浏览器不支持 video 标签。
                                </video>`;
        } else {
            mediaElementHtml = `<div class="file-placeholder" data-media-type="file">
                                    📄
                                </div>`;
        }

        card.innerHTML = `
            <input type="checkbox" class="media-checkbox" data-filename="${media.filename}">
            ${mediaElementHtml}
            <div class="media-actions">
                <button type="button" class="action-btn" title="复制链接" onclick="copyToClipboard(this, '${media.url}')">📋</button>
            </div>
            <div class="media-card-footer">
                <p title="${media.filename}">${media.filename}</p>
                <p style="font-size: 0.9em; color: #666;">${new Date(media.created_at).toLocaleString()}</p>
            </div>
        `;
        mediaGridContainer.appendChild(card);
    });
}

function renderPagination(total, page, pageSize) {
    const totalPages = Math.ceil(total / pageSize);
    paginationContainer.innerHTML = ''; // Clear previous controls

    if (totalPages <= 1 && total <= 10) { // Hide if only one page and few items
        return;
    }

    // Page size selector
    const selectorContainer = document.createElement('div');
    selectorContainer.className = 'page-size-selector';
    selectorContainer.innerHTML = `
        <label for="page-size">每页显示:</label>
        <select id="page-size" name="page-size">
            <option value="10">10</option>
            <option value="20">20</option>
            <option value="50">50</option>
            <option value="100">100</option>
        </select>
    `;
    const selectElement = selectorContainer.querySelector('select');
    selectElement.value = currentPageSize;
    selectElement.addEventListener('change', (event) => {
        const newSize = parseInt(event.target.value, 10);
        fetchMedia(1, currentStorageType, newSize);
    });
    
    // Pagination buttons
    const prevBtn = document.createElement('button');
    prevBtn.textContent = '上一页';
    prevBtn.disabled = page === 1;
    prevBtn.onclick = () => fetchMedia(page - 1, currentStorageType, currentPageSize);

    const pageInfo = document.createElement('span');
    pageInfo.textContent = `第 ${page} / ${totalPages} 页 (共 ${total} 项)`;
    
    const nextBtn = document.createElement('button');
    nextBtn.textContent = '下一页';
    nextBtn.disabled = page === totalPages;
    nextBtn.onclick = () => fetchMedia(page + 1, currentStorageType, currentPageSize);

    // Append elements
    paginationContainer.appendChild(prevBtn);
    paginationContainer.appendChild(pageInfo);
    paginationContainer.appendChild(nextBtn);
    paginationContainer.appendChild(selectorContainer);
}

function copyToClipboard(btn, textToCopy) {
    if (!textToCopy) {
        alert("没有内容可复制。");
        return;
    }

    const originalText = btn.innerHTML;
    
    const showSuccess = () => {
        btn.innerHTML = '已复制';
        btn.disabled = true;
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 2000);
    };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(textToCopy).then(showSuccess).catch(err => {
            console.error('自动复制失败: ', err);
            fallbackCopyToClipboard(btn, textToCopy, showSuccess);
        });
    } else {
        fallbackCopyToClipboard(btn, textToCopy, showSuccess);
    }
}

function fallbackCopyToClipboard(btn, text, successCallback) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    textArea.style.left = '-9999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            successCallback();
        } else {
            alert('自动复制失败，请手动选择文本并复制。');
        }
    } catch (err) {
        console.error('Fallback 复制失败: ', err);
        alert('自动复制失败，请手动选择文本并复制。\n错误信息: ' + err);
    }
    document.body.removeChild(textArea);
}

function copyTextToClipboard(element, textToCopy) {
    if (!textToCopy) {
        return;
    }

    const originalText = element.innerHTML;
    const originalClassName = element.className;

    const showSuccess = () => {
        element.innerHTML = '已复制!';
        element.classList.add('copied-feedback');
        setTimeout(() => {
            element.innerHTML = originalText;
            element.className = originalClassName;
        }, 1500);
    };

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(textToCopy).then(showSuccess).catch(err => {
            console.error('自动复制失败: ', err);
            element.innerHTML = '复制失败';
            element.classList.add('copied-feedback');
            setTimeout(() => {
                element.innerHTML = originalText;
                element.className = originalClassName;
            }, 1500);
        });
    } else {
        // Fallback for non-secure contexts or older browsers
        const textArea = document.createElement('textarea');
        textArea.value = textToCopy;
        textArea.style.position = 'fixed';
        textArea.style.top = '-9999px';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            const successful = document.execCommand('copy');
            if (successful) {
                showSuccess();
            } else {
                alert('自动复制失败，请手动选择文本并复制。');
            }
        } catch (err) {
            console.error('Fallback 复制失败: ', err);
            alert('自动复制失败，请手动选择文本并复制。\n错误信息: ' + err);
        }
        document.body.removeChild(textArea);
    }
}

storageTypeSelector.addEventListener('change', (event) => {
    fetchMedia(1, event.target.value, currentPageSize);
    fetchStorageDetails(event.target.value);
});


selectAllBtn.addEventListener('click', () => {
    isSelectAll = !isSelectAll;
    document.querySelectorAll('.media-checkbox').forEach(checkbox => {
        checkbox.checked = isSelectAll;
    });
    selectAllBtn.textContent = isSelectAll ? '取消全选' : '全选';
});

deleteSelectedBtn.addEventListener('click', async () => {
    const selectedFiles = Array.from(document.querySelectorAll('.media-checkbox:checked')).map(cb => cb.dataset.filename);
    if (selectedFiles.length === 0) {
        alert('请先选择要删除的文件');
        return;
    }

    const confirmed = await showConfirm('确认删除', `您确定要删除选中的 ${selectedFiles.length} 个文件吗？此操作不可恢复。`);
    if (confirmed) {
        const token = localStorage.getItem('admin-token');
        showLoader();
        try {
            const response = await fetch(`/admin/media?storage_type=${currentStorageType}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(selectedFiles)
            });
            const result = await response.json();
            alert(result.message);
            if (result.success || response.ok) {
                fetchMedia(currentPage, currentStorageType, currentPageSize); // Refresh the gallery
            }
        } catch (error) {
            console.error('Error deleting media:', error);
            alert('删除失败，请查看控制台获取更多信息。');
        } finally {
            hideLoader();
        }
    }
});

// Initial load
document.querySelectorAll('.category-header').forEach(header => {
    header.addEventListener('click', function() {
        if (this.nextElementSibling.id === 'media-gallery-content' && !mediaGridContainer.hasChildNodes()) {
            fetchMedia(1, 'local', 10);
        }
    });
});

// --- Media Viewer Modal Logic ---
const mediaViewerModal = document.getElementById('media-viewer-modal');
const mediaViewerContent = document.getElementById('media-viewer-content');
const mediaViewerClose = document.getElementById('media-viewer-close');
const viewerPrevBtn = document.querySelector('#media-viewer-modal .prev');
const viewerNextBtn = document.querySelector('#media-viewer-modal .next');

let currentMediaIndex = 0;
let mediaItems = []; // Will store {url, type}

function openMediaViewer(index) {
    currentMediaIndex = index;
    const item = mediaItems[currentMediaIndex];
    mediaViewerContent.innerHTML = ''; // Clear previous content

    if (item.type === 'image') {
        const img = document.createElement('img');
        img.src = item.url;
        mediaViewerContent.appendChild(img);
    } else if (item.type === 'video') {
        const video = document.createElement('video');
        video.src = item.url;
        video.controls = true;
        video.autoplay = true;
        mediaViewerContent.appendChild(video);
    }
    mediaViewerModal.style.display = "block";
}

function closeMediaViewer() {
    mediaViewerModal.style.display = "none";
    mediaViewerContent.innerHTML = ''; // Stop video playback etc.
}

function changeMedia(step) {
    currentMediaIndex += step;
    if (currentMediaIndex >= mediaItems.length) {
        currentMediaIndex = 0;
    }
    if (currentMediaIndex < 0) {
        currentMediaIndex = mediaItems.length - 1;
    }
    openMediaViewer(currentMediaIndex);
}

mediaViewerClose.onclick = closeMediaViewer;
viewerPrevBtn.onclick = () => changeMedia(-1);
viewerNextBtn.onclick = () => changeMedia(1);

mediaViewerModal.onclick = function(event) {
    if (event.target === mediaViewerModal || event.target === mediaViewerContent) {
        closeMediaViewer();
    }
}

mediaGridContainer.addEventListener('click', function(event) {
    const target = event.target;
    if (target.matches('img[data-media-type="image"], video[data-media-type="video"]')) {
        const allMediaElements = Array.from(mediaGridContainer.querySelectorAll('img[data-media-type="image"], video[data-media-type="video"]'));
        mediaItems = allMediaElements.map(el => ({
            url: el.src || el.querySelector('source').src,
            type: el.dataset.mediaType
        }));
        const clickedUrl = target.src || (target.querySelector('source') ? target.querySelector('source').src : null);
        const clickedIndex = mediaItems.findIndex(item => item.url === clickedUrl);
        if (clickedIndex !== -1) {
            openMediaViewer(clickedIndex);
        }
    }
});
function fetchStorageDetails(storageType) {
    const container = document.getElementById('storage-details-container');
    const sizeProgressContainer = document.getElementById('image-size-progress').parentElement;
    const sizeText = document.getElementById('image-size-text');

    // 只有本地和内存存储显示详情
    if (storageType === 'local' || storageType === 'memory') {
        container.style.display = 'block';
    } else {
        container.style.display = 'none';
        return;
    }
    const token = localStorage.getItem('admin-token');
    fetch(`/admin/storage_details?storage_type=${storageType}`, {
        headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(response => response.json())
    .then(data => {
        if (data) {
            // 更新图片数量进度条
            const countProgress = document.getElementById('image-count-progress');
            const countText = document.getElementById('image-count-text');
            const countPercent = data.max_images > 0 ? (data.total_images / data.max_images) * 100 : 0;
            countProgress.style.width = `${countPercent}%`;
            countProgress.textContent = `${Math.round(countPercent)}%`;
            countText.textContent = `图片数量: ${data.total_images} / ${data.max_images}`;

            // 更新存储大小进度条
            const sizeProgress = document.getElementById('image-size-progress');
            if (data.max_size_mb > 0) {
                sizeProgressContainer.style.display = 'block';
                sizeText.style.display = 'block';
                const sizePercent = (data.total_size_mb / data.max_size_mb) * 100;
                sizeProgress.style.width = `${sizePercent}%`;
                sizeProgress.textContent = `${Math.round(sizePercent)}%`;
                sizeText.textContent = `存储空间: ${data.total_size_mb}MB / ${data.max_size_mb}MB`;
            } else {
                // 如果max_size_mb为0或未定义，则隐藏大小进度条
                sizeProgressContainer.style.display = 'none';
                sizeText.textContent = `已用空间: ${data.total_size_mb}MB (无大小限制)`;
            }
        }
    })
    .catch(error => console.error('Error fetching storage details:', error));
}

document.querySelectorAll('input[name="storage-type"]').forEach(radio => {
    radio.addEventListener('change', (event) => {
        const selectedStorage = event.target.value;
        fetchMedia(1, selectedStorage, parseInt(document.getElementById('page-size').value));
        fetchStorageDetails(selectedStorage);
    });
});

function loadAccessKeys() {
    fetch('/admin/keys', {
        headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById('status-header').textContent='状态❇️';
        accessKeyFilterState = 0 //重置筛选 0: 全部, 1: 有效, 2: 无效
        allAccessKeys = data; // Store all keys for validation
        originalAccessKeys = JSON.parse(JSON.stringify(data)); // 深拷贝用于比较
        renderAccessKeys();
    });
}

// 渲染访问密钥表格
function renderAccessKeys() {
    const tbody = document.querySelector('#access-keys-table tbody');
    tbody.innerHTML = '';
    Object.keys(allAccessKeys).reverse().forEach((key_id, index) => {
       const key = allAccessKeys[key_id];
        const expires = key.expires_at ? new Date(key.expires_at * 1000).toLocaleString() : '永不';
        const usage = key.usage_limit !== null ? `${key.usage_count} / ${key.usage_limit} 次` : '无限制';
        const statusClass = key.is_active ? 'status-active' : 'status-inactive';
        const statusText = key.is_active ? '有效' : '无效';
        const resetDailyText = key.reset_daily ? '是' : '否';
        const resetDailyClass = key.reset_daily ? 'status-active' : 'status-inactive';
        const row = `
            <tr>
                <td>${index + 1}</td>
                <td>${key.name || ''}</td>
                <td class="truncate-text" title="点击复制: ${key.key}" onclick="copyTextToClipboard(this, '${key.key}')">${key.key}</td>
                <td>${usage}</td>
                <td>${expires}</td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td><span class="status-badge ${resetDailyClass}">${resetDailyText}</span></td>
                <td>
                    <button type="button" class="action-btn edit-btn" onclick="editAccessKey('${key.key}')" title="编辑">✏️</button>
                    <button type="button" class="action-btn delete-btn" onclick="deleteAccessKey('${key.key}', '${encodeURIComponent(key.name || '')}')" title="删除">🗑️</button>
                </td>
            </tr>
        `;
        tbody.innerHTML += row;
    });

    // 更新总数量显示
    const keysCountElement = document.getElementById('access-keys-count');
    if (keysCountElement) {
        keysCountElement.textContent = Object.keys(allAccessKeys).length;
    }
}


function showAccessKeyPrompt(title, keyData = {}) {
    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;

        // Hide other containers
        modalText.style.display = 'none';
        modalSingleInputContainer.style.display = 'none';
        modalMappingContainer.style.display = 'none';
        modalTextareaContainer.style.display = 'none';
        
        // Show the access key container
        const accessKeyContainer = document.getElementById('modal-access-key-container');
        accessKeyContainer.style.display = 'block';

        // Get input elements
        const nameInput = document.getElementById('modal-input-name');
        const usageLimitInput = document.getElementById('modal-input-usage-limit');
        const expiresAtInput = document.getElementById('modal-input-expires-at');
        const isActiveContainer = document.getElementById('modal-is-active-container');
        const isActiveInput = document.getElementById('modal-input-is-active');
        const resetDailyContainer = document.getElementById('modal-reset-daily-container');
        const resetDailyInput = document.getElementById('modal-input-reset-daily');

        const toggleResetDaily = () => {
            const isUnlimited = usageLimitInput.value.trim() === '';
            resetDailyInput.disabled = isUnlimited;
            if (isUnlimited) {
                resetDailyInput.checked = false;
            }
        };

        usageLimitInput.addEventListener('input', toggleResetDaily);

        // Populate with existing data if available (for editing)
        nameInput.value = keyData.name || '';
        usageLimitInput.value = keyData.usage_limit || '';
        if (keyData.expires_at) {
            const now = new Date();
            const expiresDate = new Date(keyData.expires_at * 1000);
            const hoursRemaining = (expiresDate - now) / (1000 * 60 * 60);
            // 只显示正的小时数，四舍五入到整数
            expiresAtInput.value = hoursRemaining > 0 ? Math.round(hoursRemaining) : '';
        } else {
            expiresAtInput.value = '';
        }
        
        // "每日重置" 选项在添加和编辑时都可见
        resetDailyContainer.style.display = 'block';
        resetDailyInput.checked = keyData.reset_daily || false;

        // "是否启用" 选项仅在编辑时可见
        if (keyData.hasOwnProperty('is_active')) {
            isActiveContainer.style.display = 'block';
            isActiveInput.checked = keyData.is_active;
        } else {
            isActiveContainer.style.display = 'none';
        }

        // Set initial state for the reset_daily switch
        toggleResetDaily();

        nameInput.focus();

        modalConfirmBtn.onclick = () => {
            const name = nameInput.value.trim();
            const usage_limit = usageLimitInput.value.trim();
            const hours = expiresAtInput.value.trim();

            if (resolvePromise) {
                let expires_at_timestamp = null;
                if (hours && !isNaN(hours) && parseInt(hours, 10) > 0) {
                    const now = new Date();
                    // Add hours to current time
                    const futureDate = new Date(now.getTime() + parseInt(hours, 10) * 60 * 60 * 1000);
                    expires_at_timestamp = Math.floor(futureDate.getTime() / 1000);
                }

                resolve({
                    name: name,
                    usage_limit: usage_limit ? parseInt(usage_limit, 10) : null,
                    expires_at: expires_at_timestamp,
                    is_active: keyData.hasOwnProperty('is_active') ? isActiveInput.checked : true,
                    reset_daily: resetDailyInput.checked
                });
            }
            hideModal();
        };

        modalCancelBtn.onclick = () => {
            if (resolvePromise) resolve(null);
            hideModal();
        };

        showModal();
    });
}

async function addAccessKey() {
    const result = await showAccessKeyPrompt("添加新访问密钥");
    if (!result) return;

    if (!result.name) {
        alert('密钥名称不能为空。');
        return;
    }
    const nameExists = Object.values(allAccessKeys).some(k => k.name === result.name);
    if (nameExists) {
        alert('该密钥名称已存在，请使用其他名称。');
        return;
    }

    const data = {
        name: result.name,
        usage_limit: result.usage_limit,
        expires_at: result.expires_at,
        is_active: true,
        reset_daily: result.reset_daily
    };

    showLoader();
    try {
        const response = await fetch('/admin/keys', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            // 重新加载访问密钥列表
            loadAccessKeys();
            alert('添加成功！');
        } else {
            const result = await response.json();
            alert('添加失败：' + (result.detail || '未知错误'));
        }
    } catch (error) {
        console.error('添加访问密钥失败:', error);
        alert('添加访问密钥失败: ' + error.message);
    } finally {
        hideLoader();
    }
}

async function editAccessKey(key) {
    const access_keys_response = await fetch('/admin/keys', { headers: { 'Authorization': 'Bearer ' + token } });
    const access_keys = await access_keys_response.json();
    const key_data = access_keys[key];

    if (!key_data) {
        alert('找不到要编辑的密钥。');
        return;
    }

    const result = await showAccessKeyPrompt("编辑访问密钥", key_data);
    if (!result) return;

    if (!result.name) {
        alert('密钥名称不能为空。');
        return;
    }
    const nameExists = Object.values(allAccessKeys).some(k => k.key !== key && k.name === result.name);
    if (nameExists) {
        alert('该密钥名称已存在，请使用其他名称。');
        return;
    }

    const data = {
        key: key,
        name: result.name,
        usage_limit: result.usage_limit,
        expires_at: result.expires_at,
        is_active: result.is_active,
        reset_daily: result.reset_daily,
        usage_count: key_data.usage_count
    };

    showLoader();
    try {
        const response = await fetch(`/admin/keys/${key}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            // 重新加载访问密钥列表
            loadAccessKeys();
            alert('编辑成功！');
        } else {
            const result = await response.json();
            alert('编辑失败：' + (result.detail || '未知错误'));
        }
    } catch (error) {
        console.error('编辑访问密钥失败:', error);
        alert('编辑访问密钥失败: ' + error.message);
    } finally {
        hideLoader();
    }
}

async function deleteAccessKey(key, name) {
    const displayName = name ? decodeURIComponent(name) : key;
    const confirmed = await showConfirm("确认删除", `确定要删除密钥 "${displayName}" 吗?`);
    if (!confirmed) return;

    showLoader();
    try {
        const response = await fetch(`/admin/keys/${key}`, {
            method: 'DELETE',
            headers: { 'Authorization': 'Bearer ' + token }
        });
        
        if (response.ok) {
            // 重新加载访问密钥列表
            loadAccessKeys();
            alert('删除成功！');
        } else {
            const result = await response.json();
            alert('删除失败：' + (result.detail || '未知错误'));
        }
    } catch (error) {
        console.error('删除访问密钥失败:', error);
        alert('删除访问密钥失败: ' + error.message);
    } finally {
        hideLoader();
    }
}


function filterAccessKeys() {
    accessKeyFilterState = (accessKeyFilterState + 1) % 3;
    const tbody = document.querySelector('#access-keys-table tbody');
    const rows = tbody.querySelectorAll('tr');
    const statusHeader = document.getElementById('status-header');

    let headerText = '状态';
    rows.forEach(row => {
        const statusCell = row.querySelector('td:nth-child(6) .status-badge');
        if (statusCell) {
            const isActive = statusCell.classList.contains('status-active');
            switch (accessKeyFilterState) {
                case 1: // Show active only
                    row.style.display = isActive ? '' : 'none';
                    headerText = '状态✅';
                    break;
                case 2: // Show inactive only
                    row.style.display = !isActive ? '' : 'none';
                    headerText = '状态❌';
                    break;
                default: // Show all
                    row.style.display = '';
                    headerText = '状态❇️';
                    break;
            }
        }
    });
    statusHeader.textContent = headerText;
}
