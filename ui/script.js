/**
 * Pizza Order System - Frontend JavaScript
 * Event-Driven Saga Architecture Demo
 */

// ========================================
// Global State Management
// ========================================

const AppState = {
    menu: [],
    cart: [],
    currentOrder: null,
    isLoading: false,
    eventLog: []
};

// API Configuration
const API_BASE = '/api/v1';
const API_ENDPOINTS = {
    menu: `${API_BASE}/menu`,
    orders: `${API_BASE}/orders`,
    notifications: `${API_BASE}/notifications`,
    base: API_BASE
};

// ========================================
// Utility Functions
// ========================================

/**
 * Format price from cents to rubles
 */
function formatPrice(cents) {
    return (cents / 100).toFixed(2).replace('.', ',') + ' ₽';
}

/**
 * Generate unique ID
 */
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

/**
 * Format timestamp
 */
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

/**
 * Add event to log with optional service information
 */
function addEventLog(type, message, service = null) {
    const timestamp = formatTimestamp();
    AppState.eventLog.unshift({ 
        timestamp, 
        type, 
        message, 
        service: service || detectServiceFromMessage(type, message)
    });
    
    // Keep only last 50 events
    if (AppState.eventLog.length > 50) {
        AppState.eventLog = AppState.eventLog.slice(0, 50);
    }
    
    updateEventLogDisplay();
}

/**
 * Detect service from event type and message
 */
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

/**
 * Update event log display with service information
 */
function updateEventLogDisplay() {
    const eventLog = document.getElementById('eventLog');
    eventLog.innerHTML = AppState.eventLog.map(event => {
        const serviceClass = `service-${event.service.replace('-', '_')}`;
        return `
        <div class="log-entry animate-slide-in">
            <span class="timestamp">${event.timestamp}</span>
            <span class="service ${serviceClass}">[${event.service}]</span>
            <span class="event-type">${event.type}</span>
            <span class="message">${event.message}</span>
        </div>
    `}).join('');
}

/**
 * Add event log from API response (when services send structured logs)
 */
function addEventLogFromAPI(logData) {
    const timestamp = logData.timestamp || formatTimestamp();
    const service = logData.service || 'unknown';
    const type = logData.event_type || logData.type || 'INFO';
    const message = logData.message || logData.msg || 'No message';
    
    AppState.eventLog.unshift({ 
        timestamp, 
        service, 
        type, 
        message 
    });
    
    // Keep only last 50 events
    if (AppState.eventLog.length > 50) {
        AppState.eventLog = AppState.eventLog.slice(0, 50);
    }
    
    updateEventLogDisplay();
}

// ========================================
// API Functions
// ========================================

/**
 * Make API request with error handling
 */
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
        
        addEventLog('API', 'Загружаем меню пиццерии...');
        
        const data = await apiRequest(API_ENDPOINTS.menu);
        AppState.menu = data.pizzas || [];
        
        // Hide loading and show menu
        menuLoading.style.display = 'none';
        menuGrid.style.display = 'grid';
        
        renderMenu();
        addEventLog('SUCCESS', `Меню загружено: ${AppState.menu.length} позиций`);
        
    } catch (error) {
        // Show error state
        menuLoading.style.display = 'none';
        menuError.style.display = 'block';
        
        addEventLog('ERROR', `Ошибка загрузки меню: ${error.message}`);
        showToast('Ошибка загрузки меню', '❌');
    }
}

/**
 * Create order via Order Service
 */
async function createOrder() {
    if (AppState.cart.length === 0) {
        showToast('Корзина пуста', '🛒');
        return;
    }
    
    const deliveryAddress = document.getElementById('deliveryAddress').value;
    const paymentMethod = document.getElementById('paymentMethod').value;
    
    if (!deliveryAddress) {
        showToast('Укажите адрес доставки', '📍');
        return;
    }
    
    const orderButton = document.getElementById('orderButton');
    const originalText = orderButton.textContent;
    
    try {
        // Disable button and show loading
        orderButton.disabled = true;
        orderButton.textContent = '⏳ Обрабатываем заказ...';
        
        const orderData = {
            items: AppState.cart.map(item => ({
                pizzaId: item.pizza.id,
                quantity: item.quantity
            })),
            deliveryAddress,
            paymentMethod
        };
        
        addEventLog('ORDER', 'Создаем заказ...');
        
        const response = await apiRequest(API_ENDPOINTS.orders, {
            method: 'POST',
            body: JSON.stringify(orderData)
        });
        
        addEventLog('SUCCESS', `Заказ создан: ${response.orderId}`);
        showToast('Заказ успешно создан!', '🎉');

        // Fetch the full order details immediately to ensure data consistency
        const fullOrderResponse = await getOrderStatus(response.orderId);
        if (!fullOrderResponse || !fullOrderResponse.order) {
            throw new Error('Не удалось получить детали созданного заказа.');
        }

        // Extract the actual order object from the response
        const orderObject = fullOrderResponse.order;
        AppState.currentOrder = orderObject;
        
        // Clear cart and form
        AppState.cart = [];
        document.getElementById('deliveryAddress').value = '';
        updateCartDisplay();
        
        // Show order status with complete data
        showOrderStatus(orderObject);
        
        // Start polling for order status using the correct order ID
        startOrderStatusPolling(orderObject.id);
        
    } catch (error) {
        addEventLog('ERROR', `Ошибка создания заказа: ${error.message}`);
        showToast('Ошибка создания заказа', '❌');
    } finally {
        // Restore button
        orderButton.disabled = false;
        orderButton.textContent = originalText;
    }
}

/**
 * Get order status from Order Service
 */
async function getOrderStatus(orderId) {
    try {
        // This function now only fetches and returns the order data
        const response = await apiRequest(`${API_ENDPOINTS.orders}/${orderId}`);
        return response; // This contains {success: true, order: {...}}
    } catch (error) {
        console.error('Failed to get order status:', error);
        return null;
    }
}

/**
 * Poll for order status until it's final
 */
function startOrderStatusPolling(orderId) {
    addEventLog('POLL', `Начинаем опрос статуса заказа #${orderId}`);
    console.log(`Starting status polling for order: ${orderId}`);

    let pollingInterval;

    const poll = async () => {
        console.log(`Polling status for order: ${orderId}`);
        const orderResponse = await getOrderStatus(orderId);
        
        console.log('Order response received:', orderResponse);
        
        if (orderResponse && orderResponse.order) {
            console.log('Order data:', orderResponse.order);
            updateOrderStatus(orderResponse.order);
            // Stop polling if status is final
            if (['COMPLETED', 'PAID', 'FAILED', 'CANCELLED'].includes(orderResponse.order.status)) {
                clearInterval(pollingInterval);
                addEventLog('POLL', `Завершаем опрос статуса: ${orderResponse.order.status}`);
                console.log(`Polling stopped for order ${orderId}, final status: ${orderResponse.order.status}`);
            }
        } else {
            console.error('Invalid order response:', orderResponse);
            addEventLog('ERROR', `Не удалось получить статус заказа #${orderId}`);
        }
    };

    // Initial check after a short delay
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
    if (!pizza) return;
    
    const existingItem = AppState.cart.find(item => item.pizza.id === pizzaId);
    
    if (existingItem) {
        existingItem.quantity += 1;
    } else {
        AppState.cart.push({
            pizza: pizza,
            quantity: 1
        });
    }
    
    updateCartDisplay();
    addEventLog('CART', `Добавлено в корзину: ${pizza.name}`);
    showToast(`${pizza.name} добавлена в корзину`, '🛒');
}

/**
 * Update item quantity in cart
 */
function updateQuantity(pizzaId, change) {
    const item = AppState.cart.find(item => item.pizza.id === pizzaId);
    if (!item) return;
    
    item.quantity += change;
    
    if (item.quantity <= 0) {
        removeFromCart(pizzaId);
        return;
    }
    
    updateCartDisplay();
    addEventLog('CART', `Изменено количество: ${item.pizza.name} (${item.quantity})`);
}

/**
 * Remove item from cart
 */
function removeFromCart(pizzaId) {
    const itemIndex = AppState.cart.findIndex(item => item.pizza.id === pizzaId);
    if (itemIndex === -1) return;
    
    const item = AppState.cart[itemIndex];
    AppState.cart.splice(itemIndex, 1);
    
    updateCartDisplay();
    addEventLog('CART', `Удалено из корзины: ${item.pizza.name}`);
    showToast(`${item.pizza.name} удалена из корзины`, '🗑️');
}

// ========================================
// System Health Monitoring
// ========================================

/**
 * Check system health
 */
async function checkSystemHealth() {
    const statusIndicator = document.getElementById('systemStatus');
    const statusDot = statusIndicator.querySelector('.status-dot');
    const statusText = statusIndicator.querySelector('.status-text');
    
    try {
        // Check frontend service health
        await apiRequest('/api/v1/health/frontend');
        
        // Update status to healthy
        statusDot.style.background = 'var(--success)';
        statusText.textContent = 'Система работает';
        
    } catch (error) {
        // Update status to unhealthy
        statusDot.style.background = 'var(--error)';
        statusText.textContent = 'Проблемы с системой';
        
        addEventLog('HEALTH', 'Обнаружены проблемы с системой');
    }
}

/**
 * Start health monitoring
 */
function startHealthMonitoring() {
    // Check immediately
    checkSystemHealth();
    
    // Check every 30 seconds
    setInterval(checkSystemHealth, 30000);
}

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
            { id: 'ltes-dashboard-link', port: '3000', dashboard: 'ltes-metrics' }
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
            { id: 'ltes-dashboard-link', url: 'http://localhost:3000/d/ltes-metrics' }
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

/**
 * Initialize application
 */
function initializeApp() {
    addEventLog('SYSTEM', 'Инициализация системы заказов...', 'frontend-ui');
    
    // Setup monitoring URLs based on environment
    setupMonitoringUrls();
    
    // Load menu
    loadMenu();
    
    // Start health monitoring
    startHealthMonitoring();
    
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
 * Start load testing with 1000 RPS for 1 minute
 */
async function startLoadTest() {
    const button = document.getElementById('loadTestButton');
    const buttonText = button.querySelector('.button-text');
    const originalText = buttonText.textContent;
    
    try {
        // Disable button and show running state
        button.disabled = true;
        button.classList.add('running');
        buttonText.textContent = 'Запуск нагрузочного теста';
        
        addEventLog('LOAD_TEST', 'Запуск нагрузочного тестирования 1000 RPS на 1 минуту...');
        showToast('🚀 Запуск нагрузочного тестирования...', '🚀');
        
        // Start k6 load test via Docker
        const response = await apiRequest('/api/v1/load-test/start', {
            method: 'POST',
            body: JSON.stringify({
                rps: 1000,
                duration: '1m',
                test_type: 'order_creation'
            })
        });
        
        if (response.success) {
            buttonText.textContent = 'Тестирование выполняется';
            addEventLog('LOAD_TEST', `Нагрузочное тестирование запущено: ${response.message}`);
            showToast('✅ Нагрузочное тестирование запущено!', '✅');
            
            // Monitor test progress
            monitorLoadTest(response.test_id || 'k6-test');
        } else {
            throw new Error(response.error || 'Не удалось запустить тест');
        }
        
    } catch (error) {
        console.error('Load test failed:', error);
        addEventLog('ERROR', `Ошибка нагрузочного тестирования: ${error.message}`);
        
        // Fallback: start k6 test directly
        try {
            addEventLog('LOAD_TEST', 'Попытка запуска k6 теста напрямую...');
            const fallbackResponse = await fetch('/api/v1/k6/start', { method: 'POST' });
            
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
            
            // Reset button state
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
            addEventLog('LOAD_TEST', `Результаты теста: ${results.total_requests} запросов, ${results.success_rate}% успешных`);
            
            // Show detailed results in toast
            showToast(
                `📊 Результаты: ${results.total_requests} запросов, ${results.success_rate}% успешных`,
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

 