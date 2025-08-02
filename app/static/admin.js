document.addEventListener('DOMContentLoaded', function() {
    const token = sessionStorage.getItem('admin-token');
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
const modalMappingContainer = document.getElementById('modal-mapping-container');
// Inputs
const modalInput = document.getElementById('modal-input');
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
        modalMappingContainer.style.display = 'none';

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

function showPrompt(title, text, defaultValue = '', inputType = 'text') {
    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;
        modalText.textContent = text;
        modalText.style.display = text ? 'block' : 'none';

        modalSingleInputContainer.style.display = 'block';
        modalMappingContainer.style.display = 'none';
        
        modalInput.value = defaultValue;
        modalInput.type = inputType;
        modalInput.focus();

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

const token = sessionStorage.getItem('admin-token');

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

    fetch('/admin/api_mappings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({ prefix: result.prefix, target_url: result.target_url })
    })
    .then(handleApiResponse)
    .then(loadApiMappings);
}

async function editApiMapping(oldPrefix, oldUrl) {
    const result = await showMappingPrompt("编辑映射", oldPrefix, oldUrl);
    if (!result) return;

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
    .then(loadApiMappings);
}

async function deleteApiMapping(prefix) {
    const confirmed = await showConfirm("确认删除", `确定要删除映射 ${prefix} 吗?`);
    if (!confirmed) return;
    
    // 从第二个字符开始，以移除开头的'/'
    const encodedPrefix = encodeURIComponent(prefix.substring(1));

    fetch(`/admin/api_mappings/${encodedPrefix}`, {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(handleApiResponse)
    .then(loadApiMappings);
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
    const password = await showPrompt("确认更改", "请输入管理员密码以保存更改:", '', 'password');
    if (password === null) {
        alert('操作已取消。');
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

    const token = sessionStorage.getItem('admin-token');
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
    }
}

let currentGeminiKeys = [];

// The function now accepts the environment data as an argument
function loadGeminiKeys(data) {
    try {
        const categoryName = 'API与访问控制';
        const keysString = data[categoryName] && data[categoryName].GEMINI_API_KEYS ? data[categoryName].GEMINI_API_KEYS.value : '';
        currentGeminiKeys = keysString ? keysString.split(',').map(k => k.trim()).filter(k => k) : [];
        renderGeminiKeys();
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
                <td id="key-cell-${safeKeyId}">${key}<br><span id="key-status-${safeKeyId}" class="key-status-text"></span></td>
                <td>
                    <button type="button" class="action-btn edit-btn" onclick="editGeminiKey('${key}')">✏️</button>
                    <button type="button" class="action-btn delete-btn" onclick="deleteGeminiKey('${key}')">🗑️</button>
                    <button type="button" class="action-btn check-btn" onclick="checkKeyAvailability('${key}')">🔍</button>
                </td>
            </tr>
        `;
        tbody.innerHTML += row;
    });

    // 同时同步更新“API与访问控制”中的输入框
    const geminiKeysInput = document.getElementById('GEMINI_API_KEYS');
    if (geminiKeysInput) {
        geminiKeysInput.value = currentGeminiKeys.join(',');
    }
}

async function addGeminiKey() {
    const newKey = await showPrompt("添加新密钥", "请输入新的 Gemini API 密钥:");
    if (newKey && newKey.trim()) {
        if (currentGeminiKeys.includes(newKey.trim())) {
            alert('该密钥已存在。');
            return;
        }
        currentGeminiKeys.push(newKey.trim());
        await saveGeminiKeys();
    }
}

async function editGeminiKey(oldKey) {
    const newKey = await showPrompt("编辑密钥", "请编辑 Gemini API 密钥:", oldKey);
    if (newKey && newKey.trim() && newKey.trim() !== oldKey) {
        const index = currentGeminiKeys.indexOf(oldKey);
        if (index !== -1) {
            if (currentGeminiKeys.includes(newKey.trim())) {
                alert('该密钥已存在。');
                return;
            }
            currentGeminiKeys[index] = newKey.trim();
            await saveGeminiKeys();
        }
    }
}

async function deleteGeminiKey(keyToDelete) {
    const confirmed = await showConfirm("确认删除", `确定要删除密钥 "${keyToDelete}" 吗?`);
    if (confirmed) {
        currentGeminiKeys = currentGeminiKeys.filter(key => key !== keyToDelete);
        await saveGeminiKeys();
    }
}

async function saveGeminiKeys() {
    const password = await showPrompt("确认操作", "为确认更改，请输入管理员密码:", '', 'password');
    if (password === null) {
        // 用户取消输入密码，不需要任何操作，因为更改尚未应用
        alert('操作已取消。');
        return;
    }

    const keysString = currentGeminiKeys.join(',');
    const data = {
        'GEMINI_API_KEYS': keysString,
        'password': password
    };

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
            }
        } else {
            statusSpan.textContent = `检查失败: ${result.detail || '未知错误'}`;
            applyStyle('red');
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
    const keysToCheck = [...currentGeminiKeys]; // 创建一个副本以进行迭代
    for (const key of keysToCheck) {
        await checkKeyAvailability(key);
        await sleep(200); // 每0.2秒检查一个，以避免请求过快
    }
}

function logout() {
    sessionStorage.removeItem('admin-token');
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

    const token = sessionStorage.getItem('admin-token');
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
        const token = sessionStorage.getItem('admin-token');
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
    const token = sessionStorage.getItem('admin-token');
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
        const tbody = document.querySelector('#access-keys-table tbody');
        tbody.innerHTML = '';
        Object.keys(data).forEach((key_id, index) => {
           const key = data[key_id];
            const expires = key.expires_at ? new Date(key.expires_at * 1000).toLocaleString() : '永不';
            const usage = key.usage_limit !== null ? `${key.usage_count} / ${key.usage_limit}` : '无限制';
            const statusClass = key.is_active ? 'status-active' : 'status-inactive';
            const statusText = key.is_active ? '有效' : '无效';
            const row = `
                <tr>
                    <td>${index + 1}</td>
                    <td>${key.name || ''}</td>
                    <td class="truncate-text" title="${key.key}">${key.key}</td>
                    <td>${usage}</td>
                    <td>${expires}</td>
                    <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                    <td>
                        <button type="button" class="action-btn edit-btn" onclick="editAccessKey('${key.key}')" title="编辑">✏️</button>
                        <button type="button" class="action-btn delete-btn" onclick="deleteAccessKey('${key.key}')" title="删除">🗑️</button>
                    </td>
                </tr>
            `;
            tbody.innerHTML += row;
        });
    });
}

function showAccessKeyPrompt(title, keyData = {}) {
    return new Promise(resolve => {
        resolvePromise = resolve;
        modalTitle.textContent = title;

        // Hide other containers
        modalText.style.display = 'none';
        modalSingleInputContainer.style.display = 'none';
        modalMappingContainer.style.display = 'none';
        
        // Show the access key container
        const accessKeyContainer = document.getElementById('modal-access-key-container');
        accessKeyContainer.style.display = 'block';

        // Get input elements
        const nameInput = document.getElementById('modal-input-name');
        const usageLimitInput = document.getElementById('modal-input-usage-limit');
        const expiresAtInput = document.getElementById('modal-input-expires-at');
        const isActiveContainer = document.getElementById('modal-is-active-container');
        const isActiveInput = document.getElementById('modal-input-is-active');

        // Populate with existing data if available (for editing)
        nameInput.value = keyData.name || '';
        usageLimitInput.value = keyData.usage_limit || '';
        expiresAtInput.value = keyData.expires_at ? new Date(keyData.expires_at * 1000).toISOString().slice(0, 19).replace('T', ' ') : '';
        
        if (keyData.hasOwnProperty('is_active')) {
            isActiveContainer.style.display = 'block';
            isActiveInput.checked = keyData.is_active;
        } else {
            isActiveContainer.style.display = 'none';
        }

        nameInput.focus();

        modalConfirmBtn.onclick = () => {
            const name = nameInput.value.trim();
            const usage_limit = usageLimitInput.value.trim();
            const expires_at = expiresAtInput.value.trim();

            if (resolvePromise) {
                resolve({
                    name: name,
                    usage_limit: usage_limit ? parseInt(usage_limit, 10) : null,
                    expires_at: expires_at ? new Date(expires_at).getTime() / 1000 : null,
                    is_active: keyData.hasOwnProperty('is_active') ? isActiveInput.checked : true
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

    const key = 'sk-' + Math.random().toString(36).substr(2);
    const data = {
        key: key,
        name: result.name,
        usage_limit: result.usage_limit,
        expires_at: result.expires_at,
        is_active: true,
        usage_count: 0
    };

    fetch('/admin/keys', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify(data)
    })
    .then(handleApiResponse)
    .then(loadAccessKeys);
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

    const data = {
        key: key,
        name: result.name,
        usage_limit: result.usage_limit,
        expires_at: result.expires_at,
        is_active: result.is_active,
        usage_count: key_data.usage_count
    };

    fetch(`/admin/keys/${key}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify(data)
    })
    .then(handleApiResponse)
    .then(loadAccessKeys);
}

async function deleteAccessKey(key) {
    const confirmed = await showConfirm("确认删除", `确定要删除密钥 ${key} 吗?`);
    if (!confirmed) return;

    fetch(`/admin/keys/${key}`, {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token }
    })
    .then(handleApiResponse)
    .then(loadAccessKeys);
}
