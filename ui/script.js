const AppState = {
    menu: [],
    cart: [],
    currentOrder: null,
    isLoading: false,
    eventLog: [],
    // Для дедупликации между опросами
    seenLogKeys: new Set(),
    seenLogOrder: [],
    // Ключи уже отрисованных записей, чтобы не перерисовывать весь список
    renderedLogKeys: new Set()
};
const API_BASE = '/api/v1';
const API_ENDPOINTS = {
    menu: `${API_BASE}/menu`,
    orders: `${API_BASE}/orders`,
    notifications: `${API_BASE}/notifications`,
    base: API_BASE
};
let testSettings = {
    failRate: 0,
    manualOrderAlwaysSuccess: true 
};

function openSettingsDialog() {
    document.getElementById('settingsModal').style.display = 'flex';
    document.getElementById('failRateSliderModal').value = testSettings.failRate;
    document.getElementById('failRateValueModal').textContent = testSettings.failRate + '%';
    document.getElementById('manualOrderSwitch').checked = testSettings.manualOrderAlwaysSuccess;
    document.getElementById('manualOrderSwitchLabel').textContent = testSettings.manualOrderAlwaysSuccess ? 'Да' : 'Нет';
}
function closeSettingsDialog() {
    document.getElementById('settingsModal').style.display = 'none';
}
function updateFailRateLabelModal() {
    const slider = document.getElementById('failRateSliderModal');
    const value = document.getElementById('failRateValueModal');
    value.textContent = slider.value + '%';
}
document.addEventListener('DOMContentLoaded', function() {
    const manualSwitch = document.getElementById('manualOrderSwitch');
    if (manualSwitch) {
        manualSwitch.addEventListener('change', function() {
            document.getElementById('manualOrderSwitchLabel').textContent = manualSwitch.checked ? 'Да' : 'Нет';
        });
    }
});
function saveSettings() {
    testSettings.failRate = parseInt(document.getElementById('failRateSliderModal').value, 10) || 0;
    testSettings.manualOrderAlwaysSuccess = document.getElementById('manualOrderSwitch').checked;
    closeSettingsDialog();
    showToast('Настройки тестирования сохранены', '⚙️');
}
function formatPrice(cents) {
    return (cents / 100).toFixed(2).replace('.', ',') + ' ₽';
}
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}
function formatTimestamp(date = new Date()) {
    return date.toLocaleString('ru-RU', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

// ===================== Дедупликация логов =====================
function makeLogKey(service, type, message, correlationId = '', extra = '') {
    return `${service}|${type}|${message}|${correlationId}|${extra}`;
}
function rememberLogKey(key) {
    AppState.seenLogKeys.add(key);
    AppState.seenLogOrder.push(key);
    // Ограничиваем размер памяти по ключам, чтобы не расти бесконечно
    const MAX_KEYS = 1000;
    if (AppState.seenLogOrder.length > MAX_KEYS) {
        const oldest = AppState.seenLogOrder.shift();
        AppState.seenLogKeys.delete(oldest);
    }
}

/**
 * Show toast notification
 */
function showToast(message, icon = '✅', duration = 3000) {
    const toast = document.getElementById('toast');
    const toastIcon = toast.querySelector('.toast-icon');
    const toastMessage = toast.querySelector('.toast-message');
    
    toastIcon.textContent = icon;
    toastMessage.textContent = message;
    
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}
function addEventLog(type, message, service = null) {
    const timestamp = formatTimestamp();
    const finalService = service || detectServiceFromMessage(type, message);
    const key = makeLogKey(finalService, type, message);
    if (AppState.seenLogKeys.has(key)) {
        return false; // пропускаем дубль
    }
    
    // Фильтруем только LOG события для отображения на HTML странице
    const shouldDisplay = type === 'LOG';
    
    AppState.eventLog.unshift({ 
        timestamp, 
        type, 
        message, 
        service: finalService,
        display: shouldDisplay
    });
    rememberLogKey(key);
    if (AppState.eventLog.length > 50) {
        AppState.eventLog = AppState.eventLog.slice(0, 50);
    }
    if (shouldDisplay) {
        updateEventLogDisplay();
    }
    return true;
}
function detectServiceFromMessage(type, message) {
    if (type === 'API' && message.includes('меню')) return 'frontend-service';
    if (type === 'ORDER') return 'order-service';
    if (type === 'PAYMENT') return 'payment-service';
    if (type === 'NOTIFICATION') return 'notification-service';
    if (type === 'POLL') return 'order-service';
    if (type === 'HEALTH') return 'system';
    if (type === 'SYSTEM') return 'frontend-ui';
    return 'frontend-ui';
}
function updateEventLogDisplay() {
    const eventLogNodes = document.querySelectorAll('#eventLog');
    if (!eventLogNodes || eventLogNodes.length === 0) return;

    // Добавляем только новые события наверх списка, не перерисовывая весь список
    for (const event of AppState.eventLog) {
        if (event.display === false) continue;
        const renderKey = makeLogKey(event.service, event.type, event.message, '', event.timestamp || '');
        if (AppState.renderedLogKeys.has(renderKey)) continue;

        const serviceClass = `service-${event.service.replace('-', '_')}`;
        const html = `
        <div class="log-entry animate-slide-in">
            <span class="timestamp">${event.timestamp}</span>
            <span class="service ${serviceClass}">[${event.service}]</span>
            <span class="event-type">${event.type}</span>
            <span class="message">${event.message}</span>
        </div>
        `;

        eventLogNodes.forEach(node => {
            node.insertAdjacentHTML('afterbegin', html);
        });
        AppState.renderedLogKeys.add(renderKey);
    }
}
function addEventLogFromAPI(logData) {
    const timestamp = logData.timestamp; // используем серверный timestamp, если он есть
    const service = logData.service || 'unknown';
    const type = logData.event_type || logData.type || 'LOG';
    let message = logData.message || logData.msg || 'No message';
    const correlationId = logData.correlationId || logData.correlation_id;
    const key = makeLogKey(service, type, message, correlationId, timestamp || '');
    
    if (AppState.seenLogKeys.has(key)) {
        return false; // пропускаем дубль
    }
    if (correlationId) {
        message = `[corr=${correlationId}] ${message}`;
    }
    
    // Фильтруем только LOG события для отображения на HTML странице
    const shouldDisplay = type === 'LOG';
    
    AppState.eventLog.unshift({ 
        timestamp: timestamp || formatTimestamp(), 
        service, 
        type, 
        message,
        display: shouldDisplay
    });
    rememberLogKey(key);
    if (AppState.eventLog.length > 50) {
        AppState.eventLog = AppState.eventLog.slice(0, 50);
    }
    
    if (shouldDisplay) {
        updateEventLogDisplay();
    }
    return true;
}
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Request failed:', error);
        addEventLog('ERROR', `API запрос неудачен: ${error.message}`);
        throw error;
    }
}

/**
 * Load menu from Frontend Service
 */
async function loadMenu() {
    const menuLoading = document.getElementById('menuLoading');
    const menuGrid = document.getElementById('menuGrid');
    const menuError = document.getElementById('menuError');
    
    try {
        // Show loading state
        menuLoading.style.display = 'block';
        menuGrid.style.display = 'none';
        menuError.style.display = 'none';
        
        addEventLog('API', 'Начинаем загрузку меню с сервера...');
        
        const data = await apiRequest(API_ENDPOINTS.menu);
        addEventLog('API', 'Получен ответ от сервера меню');
        
        AppState.menu = data.pizzas || [];
        
        // Логируем детали загруженного меню
        if (AppState.menu.length > 0) {
            AppState.menu.forEach(pizza => {
                addEventLog('API', `Позиция: ${pizza.name} - ${formatPrice(pizza.price)}`);
            });
        }
        
        // Hide loading and show menu
        menuLoading.style.display = 'none';
        menuGrid.style.display = 'grid';
        
        renderMenu();
        addEventLog('SUCCESS', `Меню загружено: ${AppState.menu.length} позиций`);
        addEventLog('SUCCESS', 'Меню отображено на странице');
        
    } catch (error) {
        // Show error state
        menuLoading.style.display = 'none';
        menuError.style.display = 'block';
        
        addEventLog('ERROR', `Ошибка загрузки меню: ${error.message}`);
        addEventLog('ERROR', 'Не удалось загрузить меню с сервера');
        showToast('Ошибка загрузки меню', '❌');
    }
}

/**
 * Create order via Order Service
 */
async function createOrder() {
    if (AppState.cart.length === 0) {
        addEventLog('ERROR', 'Попытка создания заказа с пустой корзиной');
        showToast('Корзина пуста', '🛒');
        return;
    }
    const deliveryAddress = document.getElementById('deliveryAddress').value;
    const paymentMethod = document.getElementById('paymentMethod').value;
    if (!deliveryAddress) {
        addEventLog('ERROR', 'Попытка создания заказа без адреса доставки');
        showToast('Укажите адрес доставки', '📍');
        return;
    }
    const orderButton = document.getElementById('orderButton');
    const originalText = orderButton.textContent;
    
    // Детальное логирование начала процесса заказа
    const cartSummary = AppState.cart.map(item => `${item.pizza.name} x${item.quantity}`).join(', ');
    const totalAmount = AppState.cart.reduce((sum, item) => sum + (item.pizza.price * item.quantity), 0);
    
    addEventLog('ORDER', `Начало создания заказа: ${cartSummary}`);
    addEventLog('ORDER', `Адрес доставки: ${deliveryAddress}`);
    addEventLog('ORDER', `Способ оплаты: ${paymentMethod}`);
    addEventLog('ORDER', `Общая сумма: ${formatPrice(totalAmount)}`);
    
    try {
        orderButton.disabled = true;
        orderButton.textContent = '⏳ Обрабатываем заказ...';
        let forceFail = !testSettings.manualOrderAlwaysSuccess;
        addEventLog('ORDER', `Настройки тестирования: forceFail=${forceFail}`);
        
        const orderData = {
            items: AppState.cart.map(item => ({
                pizzaId: item.pizza.id,
                quantity: item.quantity
            })),
            deliveryAddress,
            paymentMethod,
            forceFail
        };
        addEventLog('ORDER', 'Отправка запроса на создание заказа...');
        const response = await apiRequest(API_ENDPOINTS.orders, {
            method: 'POST',
            body: JSON.stringify(orderData)
        });
        addEventLog('SUCCESS', `Заказ создан: ${response.orderId}`);
        showToast('Заказ успешно создан!', '🎉');
        
        addEventLog('ORDER', 'Получение деталей созданного заказа...');
        const fullOrderResponse = await getOrderStatus(response.orderId);
        if (!fullOrderResponse || !fullOrderResponse.order) {
            throw new Error('Не удалось получить детали созданного заказа.');
        }
        const orderObject = fullOrderResponse.order;
        addEventLog('SUCCESS', `Детали заказа получены, статус: ${orderObject.status}`);
        
        AppState.currentOrder = orderObject;
        AppState.cart = [];
        document.getElementById('deliveryAddress').value = '';
        updateCartDisplay();
        addEventLog('ORDER', 'Корзина очищена, форма сброшена');
        
        showOrderStatus(orderObject);
        startOrderStatusPolling(orderObject.id);
    } catch (error) {
        addEventLog('ERROR', `Ошибка создания заказа: ${error.message}`);
        addEventLog('ERROR', `Детали ошибки: ${error.stack || 'Стек недоступен'}`);
        showToast('Ошибка создания заказа', '❌');
    } finally {
        orderButton.disabled = false;
        orderButton.textContent = originalText;
        addEventLog('ORDER', 'Процесс создания заказа завершен');
    }
}
async function getOrderStatus(orderId) {
    try {
        const response = await apiRequest(`${API_ENDPOINTS.orders}/${orderId}`);
        return response;
    } catch (error) {
        console.error('Failed to get order status:', error);
        return null;
    }
}

function startOrderStatusPolling(orderId) {
    addEventLog('POLL', `Начинаем опрос статуса заказа #${orderId}`);
    addEventLog('POLL', `Интервал опроса: каждые 5 секунд`);
    console.log(`Starting status polling for order: ${orderId}`);

    let pollingInterval;
    let pollCount = 0;

    const poll = async () => {
        pollCount++;
        addEventLog('POLL', `Опрос статуса #${pollCount} для заказа #${orderId}`);
        console.log(`Polling status for order: ${orderId}`);
        
        try {
            const orderResponse = await getOrderStatus(orderId);
            
            console.log('Order response received:', orderResponse);
            
            if (orderResponse && orderResponse.order) {
                console.log('Order data:', orderResponse.order);
                addEventLog('POLL', `Получен статус: ${orderResponse.order.status}`);
                updateOrderStatus(orderResponse.order);
                
                // Stop polling if status is final
                if (['COMPLETED', 'PAID', 'FAILED', 'CANCELLED'].includes(orderResponse.order.status)) {
                    clearInterval(pollingInterval);
                    addEventLog('POLL', `Завершаем опрос статуса: ${orderResponse.order.status} (финальный статус)`);
                    addEventLog('POLL', `Всего выполнено опросов: ${pollCount}`);
                    console.log(`Polling stopped for order ${orderId}, final status: ${orderResponse.order.status}`);
                }
            } else {
                console.error('Invalid order response:', orderResponse);
                addEventLog('ERROR', `Не удалось получить статус заказа #${orderId} (опрос #${pollCount})`);
            }
        } catch (error) {
            addEventLog('ERROR', `Ошибка при опросе статуса заказа #${orderId}: ${error.message}`);
            console.error('Polling error:', error);
        }
    };

    // Initial check after a short delay
    addEventLog('POLL', 'Первый опрос через 1 секунду...');
    setTimeout(poll, 1000);

    // Set interval for subsequent checks
    pollingInterval = setInterval(poll, 5000);
    
    console.log(`Polling interval set for order ${orderId}, checking every 5 seconds`);
}

// ========================================
// UI Rendering Functions
// ========================================

/**
 * Render menu items
 */
function renderMenu() {
    const menuGrid = document.getElementById('menuGrid');
    
    menuGrid.innerHTML = AppState.menu.map(pizza => `
        <div class="pizza-card animate-fade-in">
            <div class="pizza-image">🍕</div>
            <div class="pizza-info">
                <div class="pizza-name">${pizza.name}</div>
                <div class="pizza-description">${pizza.description}</div>
                <div class="pizza-ingredients">
                    ${pizza.ingredients.map(ingredient => 
                        `<span class="ingredient-tag">${ingredient}</span>`
                    ).join('')}
                </div>
                <div class="pizza-footer">
                    <div class="pizza-price">${formatPrice(pizza.price)}</div>
                    <button class="add-to-cart-btn" onclick="addToCart('${pizza.id}')">
                        🛒 В корзину
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

/**
 * Update cart display
 */
function updateCartDisplay() {
    const cartSection = document.getElementById('cartSection');
    const cartItems = document.getElementById('cartItems');
    const cartTotal = document.getElementById('cartTotal');
    
    if (AppState.cart.length === 0) {
        cartSection.style.display = 'none';
        return;
    }
    
    cartSection.style.display = 'block';
    
    cartItems.innerHTML = AppState.cart.map(item => `
        <div class="cart-item animate-fade-in">
            <div class="cart-item-info">
                <div class="cart-item-name">${item.pizza.name}</div>
                <div class="cart-item-price">${formatPrice(item.pizza.price)} × ${item.quantity}</div>
            </div>
            <div class="quantity-controls">
                <button class="quantity-btn" onclick="updateQuantity('${item.pizza.id}', -1)">−</button>
                <span class="quantity-display">${item.quantity}</span>
                <button class="quantity-btn" onclick="updateQuantity('${item.pizza.id}', 1)">+</button>
            </div>
            <button class="remove-item-btn" onclick="removeFromCart('${item.pizza.id}')">
                Удалить
            </button>
        </div>
    `).join('');
    
    const total = AppState.cart.reduce((sum, item) => sum + (item.pizza.price * item.quantity), 0);
    cartTotal.textContent = formatPrice(total);
}

/**
 * Show order status
 */
function showOrderStatus(order) {
    const orderStatusSection = document.getElementById('orderStatusSection');
    const orderStatusCard = document.getElementById('orderStatusCard');
    
    AppState.currentOrder = order;
    
    // Defensive check for status property
    const status = order.status || 'UNKNOWN';
    
    orderStatusCard.innerHTML = `
        <h3>Заказ #${order.id}</h3>
        <p>Сумма: ${formatPrice(order.total)}</p>
        <div class="status-line">
            <span>Статус:</span>
            <span id="statusValue" class="status-badge status-${status.toLowerCase()}">${getStatusText(status)}</span>
        </div>
        <small>Статус обновляется автоматически...</small>
    `;

    orderStatusSection.style.display = 'block';
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

/**
 * Update order status display
 */
function updateOrderStatus(order) {
    // Ensure we have a valid order object with an id and status
    if (!order || !order.id || !order.status) {
        console.warn('updateOrderStatus called with invalid order object:', order);
        return;
    }

    if (!AppState.currentOrder || AppState.currentOrder.id !== order.id) {
        // This update is for an old order, ignore it.
        console.log(`Ignoring status update for order ${order.id}, current order is ${AppState.currentOrder?.id}`);
        return;
    }

    const statusValue = document.getElementById('statusValue');
    // Gracefully handle if the element is not found
    if (!statusValue) {
        console.error('Could not find statusValue element to update.');
        return;
    }
    
    const currentStatus = AppState.currentOrder.status;

    console.log(`Checking status update: current=${currentStatus}, new=${order.status}`);

    if (currentStatus !== order.status) {
        addEventLog('UPDATE', `Статус заказа изменился: ${currentStatus} -> ${order.status}`);
        
        // Update status text and class
        statusValue.textContent = getStatusText(order.status);
        statusValue.className = `status-badge status-${order.status.toLowerCase()}`;
        
        // Animate change
        statusValue.classList.add('animate-pulse');
        setTimeout(() => {
            statusValue.classList.remove('animate-pulse');
        }, 1000);
        
        AppState.currentOrder = order;
        console.log(`Status updated successfully to: ${order.status}`);
    } else {
        console.log(`Status unchanged: ${order.status}`);
    }
}

/**
 * Get human-readable status text
 */
function getStatusText(status) {
    const statusMap = {
        'PENDING': 'Ожидает обработки',
        'PROCESSING': 'Обрабатывается',
        'PAID': '✅ Оплачен',
        'FAILED': '❌ Ошибка оплаты',
        'COMPLETED': '🎉 Выполнен',
        'UNKNOWN': 'Статус неизвестен'
    };
    return statusMap[status] || status;
}

// ========================================
// Cart Management Functions
// ========================================

/**
 * Add pizza to cart
 */
function addToCart(pizzaId) {
    const pizza = AppState.menu.find(p => p.id === pizzaId);
    if (!pizza) {
        addEventLog('ERROR', `Попытка добавить несуществующую пиццу (ID: ${pizzaId})`);
        return;
    }
    
    const existingItem = AppState.cart.find(item => item.pizza.id === pizzaId);
    
    if (existingItem) {
        const oldQuantity = existingItem.quantity;
        existingItem.quantity += 1;
        addEventLog('CART', `Увеличено количество: ${pizza.name} (${oldQuantity} → ${existingItem.quantity})`);
    } else {
        AppState.cart.push({
            pizza: pizza,
            quantity: 1
        });
        addEventLog('CART', `Добавлено в корзину: ${pizza.name} (${formatPrice(pizza.price)})`);
    }
    
    const cartTotal = AppState.cart.reduce((sum, item) => sum + (item.pizza.price * item.quantity), 0);
    addEventLog('CART', `Общая сумма корзины: ${formatPrice(cartTotal)}`);
    
    updateCartDisplay();
    showToast(`${pizza.name} добавлена в корзину`, '🛒');
}

/**
 * Update item quantity in cart
 */
function updateQuantity(pizzaId, change) {
    const item = AppState.cart.find(item => item.pizza.id === pizzaId);
    if (!item) {
        addEventLog('ERROR', `Попытка изменить количество несуществующего товара (ID: ${pizzaId})`);
        return;
    }
    
    const oldQuantity = item.quantity;
    item.quantity += change;
    
    if (item.quantity <= 0) {
        addEventLog('CART', `Количество ${item.pizza.name} стало ${item.quantity}, удаляем из корзины`);
        removeFromCart(pizzaId);
        return;
    }
    
    addEventLog('CART', `Изменено количество: ${item.pizza.name} (${oldQuantity} → ${item.quantity})`);
    
    const cartTotal = AppState.cart.reduce((sum, item) => sum + (item.pizza.price * item.quantity), 0);
    addEventLog('CART', `Общая сумма корзины: ${formatPrice(cartTotal)}`);
    
    updateCartDisplay();
}

/**
 * Remove item from cart
 */
function removeFromCart(pizzaId) {
    const itemIndex = AppState.cart.findIndex(item => item.pizza.id === pizzaId);
    if (itemIndex === -1) {
        addEventLog('ERROR', `Попытка удалить несуществующий товар из корзины (ID: ${pizzaId})`);
        return;
    }
    
    const item = AppState.cart[itemIndex];
    AppState.cart.splice(itemIndex, 1);
    
    addEventLog('CART', `Удалено из корзины: ${item.pizza.name} (количество: ${item.quantity})`);
    
    const cartTotal = AppState.cart.reduce((sum, item) => sum + (item.pizza.price * item.quantity), 0);
    addEventLog('CART', `Общая сумма корзины: ${formatPrice(cartTotal)}`);
    
    updateCartDisplay();
    showToast(`${item.pizza.name} удалена из корзины`, '🗑️');
}

// ========================================
// Health monitoring removed - using logs for system status
// ========================================
// ========================================
// Event Listeners and Initialization
// ========================================

/**
 * Detect if we're running in GitHub Codespaces and setup monitoring URLs
 */
function setupMonitoringUrls() {
    const hostname = window.location.hostname;
    const protocol = window.location.protocol;
    
    // Detect Codespaces environment
    const isCodespaces = hostname.includes('app.github.dev') || 
                       hostname.includes('preview.app.github.dev') ||
                       hostname.includes('.github.dev');
    
    if (isCodespaces) {
        // Extract the base codespace URL pattern
        // Support different Codespaces URL formats:
        // - username-reponame-abcd1234-80.app.github.dev
        // - username-reponame-abcd1234.github.dev
        let basePattern = hostname;
        
        // Remove current port if present and replace with placeholder
        if (basePattern.includes('-80.')) {
            basePattern = basePattern.replace(/-80\./, '-{PORT}.');
        } else if (basePattern.includes('.github.dev')) {
            // For newer format without explicit port in hostname
            basePattern = basePattern.replace('.github.dev', '-{PORT}.app.github.dev');
        }
        
        // Update monitoring links for Codespaces
        const monitoringLinks = [
            { id: 'kafka-ui-link', port: '8080' },
            { id: 'grafana-link', port: '3000' },
            { id: 'prometheus-link', port: '9090' },
            { id: 'pgadmin-link', port: '80', path: '/pgadmin/' },  // Use nginx proxy
            { id: 'cadvisor-link', port: '8083' },
            { id: 'node-exporter-link', port: '9100' },
            { id: 'use-dashboard-link', port: '3000', dashboard: 'use-metrics' },
            { id: 'red-dashboard-link', port: '3000', dashboard: 'red-metrics' },
            { id: 'ltes-dashboard-link', port: '3000', dashboard: 'ltes-metrics' },
            { id: 'cpu-dashboard-link', port: '3000', dashboard: 'cpu-by-service' }
        ];
        
        monitoringLinks.forEach(({ id, port, dashboard, path }) => {
            const link = document.getElementById(id);
            if (link) {
                let url = protocol + '//' + basePattern.replace('{PORT}', port);
                if (path) {
                    url += path;
                } else if (dashboard) {
                    url += `/d/${dashboard}`;
                }
                link.href = url;
                console.log(`🔗 ${id}: ${url}`);
            }
        });
        
        console.log('🔧 Codespaces detected - monitoring URLs updated');
        addEventLog('SYSTEM', 'Настроены URL для GitHub Codespaces');
        
    } else {
        // Local development - use localhost
        const localLinks = [
            { id: 'kafka-ui-link', url: 'http://localhost:8080' },
            { id: 'grafana-link', url: 'http://localhost:3000' },
            { id: 'prometheus-link', url: 'http://localhost:9090' },
            { id: 'pgadmin-link', url: 'http://localhost/pgadmin/' },  // Use nginx proxy
            { id: 'cadvisor-link', url: 'http://localhost:8083' },
            { id: 'node-exporter-link', url: 'http://localhost:9100' },
            { id: 'use-dashboard-link', url: 'http://localhost:3000/d/use-metrics' },
            { id: 'red-dashboard-link', url: 'http://localhost:3000/d/red-metrics' },
            { id: 'ltes-dashboard-link', url: 'http://localhost:3000/d/ltes-metrics' },
            { id: 'cpu-dashboard-link', url: 'http://localhost:3000/d/cpu-by-service' }
        ];
        
        localLinks.forEach(({ id, url }) => {
            const link = document.getElementById(id);
            if (link) {
                link.href = url;
            }
        });
        
        console.log('🏠 Local development detected - using localhost URLs');
    }
}

// ========================================
// Logs Fetching and Display
// ========================================

/**
 * Fetch logs from Frontend API and append to UI event log
 */
async function fetchServiceLogs() {
    try {
        const data = await apiRequest('/api/v1/logs');
        let count = 0; // считаем только добавленные (новые) записи
        if (Array.isArray(data)) {
            for (const entry of data) {
                if (addEventLogFromAPI(entry)) count++;
            }
        } else if (data && Array.isArray(data.logs)) {
            const service = data.service || 'unknown';
            for (const line of data.logs) {
                if (typeof line === 'string') {
                    // Для простых строк используем стабильный ключ без timestamp
                    if (addEventLogFromAPI({ 
                        message: line.trim(), 
                        service, 
                        event_type: 'LOG'
                    })) count++;
                } else {
                    if (addEventLogFromAPI({ ...line, service })) count++;
                }
            }
        } else if (data && typeof data === 'object') {
            for (const [service, lines] of Object.entries(data)) {
                if (!Array.isArray(lines)) continue;
                for (const line of lines) {
                    if (typeof line === 'string') {
                        // Для простых строк используем стабильный ключ без timestamp
                        if (addEventLogFromAPI({ 
                            message: line.trim(), 
                            service, 
                            event_type: 'LOG'
                        })) count++;
                    } else {
                        if (addEventLogFromAPI({ ...line, service })) count++;
                    }
                }
            }
        }
        // Не показываем системные сообщения о получении логов на HTML странице
        if (count > 0) {
            console.log(`Получено ${count} новых записей логов`);
        }
    } catch (error) {
        console.error('Failed to fetch logs', error);
    }
}

/**
 * Start periodic logs polling
 */
let logsPollingInterval = null;
const LOGS_POLL_INTERVAL_MS = 3000; // 3 секунды для более оперативного лога

function startLogsPolling() {
    // Гарантируем единичный интервал: очищаем предыдущий, если был
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
    }
    // Fetch immediately
    fetchServiceLogs();
    // Poll every LOGS_POLL_INTERVAL_MS
    logsPollingInterval = setInterval(fetchServiceLogs, LOGS_POLL_INTERVAL_MS);
}

function stopLogsPolling() {
    if (logsPollingInterval) {
        clearInterval(logsPollingInterval);
        logsPollingInterval = null;
    }
}

/**
 * Initialize application
 */
function initializeApp() {
    addEventLog('SYSTEM', 'Инициализация системы заказов...', 'frontend-ui');
    
    // Setup monitoring URLs based on environment
    setupMonitoringUrls();
    
    // Load menu
    loadMenu();
    
    // Единоразовая загрузка логов без периодического авто-опроса
    fetchServiceLogs();

    
    // Add initial welcome message
    setTimeout(() => {
        showToast('Добро пожаловать в систему заказов!', '👋', 4000);
    }, 1000);
    
    addEventLog('SYSTEM', 'Система готова к работе', 'frontend-ui');
}

/**
 * Handle page load
 */
document.addEventListener('DOMContentLoaded', function() {
    console.log('🍕 Pizza Order System - Event-Driven Saga');
    console.log('Frontend initialized');
    
    initializeApp();
});

/**
 * Handle page visibility change for real-time updates
 */
document.addEventListener('visibilitychange', function() {
    if (!document.hidden && AppState.currentOrder && AppState.currentOrder.id) {
        // Refresh order status when page becomes visible
        getOrderStatus(AppState.currentOrder.id).then(orderResponse => {
            if (orderResponse && orderResponse.order) {
                updateOrderStatus(orderResponse.order);
            }
        });
    }
});

/**
 * Handle window beforeunload for cleanup
 */
window.addEventListener('beforeunload', function() {
    addEventLog('SYSTEM', 'Завершение сессии');
});

// ========================================
// Development Helpers
// ========================================

/**
 * Expose debug functions for development
 */
if (window.location.hostname === 'localhost') {
    window.PizzaApp = {
        state: AppState,
        loadMenu,
        createOrder,
        addToCart,
        clearCart: () => {
            AppState.cart = [];
            updateCartDisplay();
        },
        simulateOrder: () => {
            // Add some items to cart for testing
            if (AppState.menu.length > 0) {
                addToCart(AppState.menu[0].id);
                document.getElementById('deliveryAddress').value = 'ул. Тестовая, 42';
            }
        }
    };
    
    console.log('🛠️ Development mode: PizzaApp debug object available');
    console.log('Use PizzaApp.simulateOrder() to quickly test order flow');
}

// ========================================
// Load Testing Functions
// ========================================

/**
 * Update fail rate label
 */
function updateFailRateLabel() {
    const slider = document.getElementById('failRateSlider');
    const value = document.getElementById('failRateValue');
    value.textContent = slider.value + '%';
}

/**
 * Start load testing with 1000 RPS for 1 minute
 */
async function startLoadTest() {
    const button = document.getElementById('loadTestButton');
    const buttonText = button.querySelector('.button-text');
    const originalText = buttonText.textContent;
    const failRate = testSettings.failRate;
    try {
        button.disabled = true;
        button.classList.add('running');
        buttonText.textContent = 'Запуск нагрузочного теста';
        addEventLog('LOAD_TEST', `Нагрузочное тестирование запущено: k6 started with 1000 RPS, ${failRate}% fail, duration 1m`);
        showToast('🚀 Запуск нагрузочного тестирования...', '🚀');
        
        // Добавляем failRate в параметры запроса
        const response = await apiRequest('/api/v1/load-test/start', {
            method: 'POST',
            body: JSON.stringify({
                rps: 1000,
                duration: '1m',
                test_type: 'order_creation',
                failRate: failRate
            })
        });
        
        if (response.success) {
            buttonText.textContent = 'Тестирование выполняется';
            showToast('✅ Нагрузочное тестирование запущено!', '✅');
            monitorLoadTest(response.test_id || 'k6-test');
        } else {
            throw new Error(response.error || 'Не удалось запустить тест');
        }
    } catch (error) {
        console.error('Load test failed:', error);
        addEventLog('ERROR', `Ошибка нагрузочного тестирования: ${error.message}`);
        try {
            addEventLog('LOAD_TEST', 'Попытка запуска k6 теста напрямую...');
            const fallbackResponse = await fetch('/api/v1/k6/start', { 
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ failRate: failRate }) // Добавляем failRate в fallback запрос
            });
            if (fallbackResponse.ok) {
                buttonText.textContent = 'Тестирование выполняется';
                addEventLog('LOAD_TEST', 'k6 тест запущен успешно');
                showToast('✅ k6 тестирование запущено!', '✅');
                monitorLoadTest('k6-fallback');
            } else {
                throw new Error('Fallback также не удался');
            }
        } catch (fallbackError) {
            showToast('❌ Ошибка запуска тестирования', '❌');
            button.disabled = false;
            button.classList.remove('running');
            buttonText.textContent = originalText;
        }
    }
}

/**
 * Monitor load test progress
 */
async function monitorLoadTest(testId) {
    const button = document.getElementById('loadTestButton');
    const buttonText = button.querySelector('.button-text');
    const originalText = 'Нагрузочный тест 1000 RPS';
    
    let remainingTime = 60; // 1 minute
    
    const updateTimer = () => {
        if (remainingTime > 0) {
            buttonText.textContent = `Тестирование (${remainingTime}с)`;
            remainingTime--;
            setTimeout(updateTimer, 1000);
        } else {
            // Test completed
            button.disabled = false;
            button.classList.remove('running');
            buttonText.textContent = originalText;
            
            addEventLog('LOAD_TEST', 'Нагрузочное тестирование завершено');
            showToast('🎉 Нагрузочное тестирование завершено!', '🎉');
            
            // Get test results
            getLoadTestResults(testId);
        }
    };
    
    updateTimer();
}

/**
 * Get load test results
 */
async function getLoadTestResults(testId) {
    try {
        const response = await apiRequest(`/api/v1/load-test/results/${testId}`);
        
        if (response.success && response.results) {
            const results = response.results;
            const expectedSuccessRate = 100 - testSettings.failRate;
            const actualSuccessRate = results.success_rate;
            
            addEventLog('LOAD_TEST', `Результаты теста: ${results.total_requests} запросов, ${actualSuccessRate}% успешных (ожидалось ${expectedSuccessRate}%)`);
            
            // Show detailed results in toast
            showToast(
                `📊 Результаты: ${results.total_requests} запросов, ${actualSuccessRate}% успешных`,
                '📊',
                5000
            );
        } else {
            addEventLog('LOAD_TEST', 'Результаты тестирования будут доступны в Grafana');
            showToast('📊 Смотрите результаты в Grafana дашборде', '📊', 5000);
        }
    } catch (error) {
        console.error('Failed to get test results:', error);
        addEventLog('LOAD_TEST', 'Результаты тестирования доступны в мониторинге');
        showToast('📊 Смотрите результаты в Grafana и Prometheus', '📊', 5000);
    }
}

 