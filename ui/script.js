const AppState = {
    menu: [],
    cart: [],
    currentOrder: null,
    isLoading: false,
    eventLog: [],
    seenLogKeys: new Set(),
    seenLogOrder: [],
    renderedLogKeys: new Set(),
    orderPollingInterval: null,
    orderPollCount: 0
};
// Адрес доставки по умолчанию для формы
const DEFAULT_DELIVERY_ADDRESS = 'Светлая ул, д 50';
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

// Надёжный парсер временной метки в миллисекунды
function parseTimestampToMillis(ts) {
    if (!ts) return Date.now();
    const parsed = Date.parse(ts);
    if (!Number.isNaN(parsed)) return parsed;
    // Поддержка формата "DD.MM.YYYY, HH:MM:SS"
    const m = ts.match(/^(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}):(\d{2}):(\d{2})$/);
    if (m) {
        const [_, d, mo, y, h, mi, s] = m;
        const dt = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s));
        return dt.getTime();
    }
    return Date.now();
}

// Порядок стадий процесса для стабильной сортировки при равном времени
const STAGE_ORDER = {
    // 1. Начало обработки заказа (order-service)
    'order_processing_started': 10,
    'order_saved_to_db': 15,
    'order_polling_started': 20,
    
    // 2. Обработка платежа (payment-service)
    'payment_event_consumed': 30,
    'sent_to_gateway': 40,
    'payment_confirmed': 50,
    'payment_event_sent_kafka': 60,
    
    // 3. Завершение заказа (order-service)
    'order_payment_event_consumed': 65,
    'order_status_paid': 80,
    'ui_notification_sent': 90
};

// Порядок статусов заказа: используем для предотвращения «отката» статуса назад
const STATUS_ORDER = {
    'UNKNOWN': 0,
    'PENDING': 10,
    'PROCESSING': 20,
    'PAID': 30,
    'FAILED': 40,
    'COMPLETED': 50
};

function detectStageFromMessage(service, message) {
    const msg = (message || '').toLowerCase();
    const svc = (service || '').toLowerCase();
    
    // Order Service стадии
    if (msg.includes('принял заказ в обработку')) return 'order_processing_started';
    if (msg.includes('сохранил в базу') || msg.includes('saved to database')) return 'order_saved_to_db';
    if (msg.includes('стал полить') || msg.includes('polling started')) return 'order_polling_started';

    // ВАЖНО: сначала распознаём, что order-service вычитал событие о платеже,
    // даже если этот лог пришёл со стороны payment-service (ошибочно размеченный service)
    if (
        msg.includes('вычитал сообщение из топика о платеже') ||
        (
            msg.includes('order-service') &&
            (msg.includes('вычитал сообщение') || msg.includes('прочитал сообщение') || msg.includes('получил сообщение')) &&
            (msg.includes('платеж') || msg.includes('payment'))
        )
    ) {
        return 'order_payment_event_consumed';
    }

    // Payment Service стадии
    if (svc.includes('payment-service') && msg.includes('вычитал сообщение из топика')) return 'payment_event_consumed';
    if (msg.includes('отправил на оплату') || msg.includes('запускаем асинхронную обработку')) return 'sent_to_gateway';
    if (msg.includes('принял сообщение об успешной оплате') || msg.includes('обработка платежа успешно завершена')) return 'payment_confirmed';
    if (
        msg.includes('отослал в кафку') ||
        msg.includes('отправил в кафку') ||
        (msg.includes('kafka') && (msg.includes('отправ') || msg.includes('sent')))
    ) return 'payment_event_sent_kafka';
    
    // Order Service завершающие стадии
    if (msg.includes('перевёл заказ в статус paid') || msg.includes('status": "paid')) return 'order_status_paid';
    if (msg.includes('отдал информацию в ui') || msg.includes('ui notification')) return 'ui_notification_sent';
    
    // Fallback для общих случаев
    if (msg.includes('вычитал сообщение') && svc.includes('payment-service')) return 'payment_event_consumed';
    
    return '';
}

function getStageRank(service, stage, message) {
    const st = stage || detectStageFromMessage(service, message);
    if (st && STAGE_ORDER[st] !== undefined) return STAGE_ORDER[st];
    // SYSTEM и прочие — самый низкий приоритет (первее при сортировке по возрастанию времени)
    if ((service || '').toLowerCase().includes('system')) return 0;
    return 5; // дефолтная ранжировка для неизвестных стадий
}

// ===================== Дедупликация логов =====================
function makeLogKey(service, type, message, correlationId = '', extra = '') {
    // Используем line_no из бэкенда для уникальности, если он есть
    return `${service}:${type}:${message.trim()}:${correlationId}:${extra}`;
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
        line_no: null,
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

// Извлекаем имя сервиса прямо из текста сообщения, если оно явно упомянуто
function detectServiceFromLogText(message) {
    if (!message || typeof message !== 'string') return null;
    const m = message.toLowerCase();
    if (m.includes('order-service')) return 'order-service';
    if (m.includes('payment-service')) return 'payment-service';
    if (m.includes('notification-service')) return 'notification-service';
    if (m.includes('frontend-service')) return 'frontend-service';
    return null;
}
function updateEventLogDisplay() {
    const eventLogNodes = document.querySelectorAll('#eventLog');
    if (!eventLogNodes || eventLogNodes.length === 0) return;

    // Подготавливаем список новых событий для рендера и сортируем их заранее,
    // чтобы порядок вывода не зависел от порядка прихода сообщений.
    // Сортировка:
    // 1) по возрастанию времени (старые сверху)
    // 2) при равном времени — по возрастанию стадии процесса (ранние шаги выше)
    // 3) затем по возрастанию line_no (если есть)
    const eventsToRender = AppState.eventLog
        .filter(ev => ev.display !== false)
        .filter(ev => {
            const renderKey = makeLogKey(ev.service, ev.type, ev.message, '', (ev.line_no ?? '') || (ev.timestamp || ''));
            return !AppState.renderedLogKeys.has(renderKey);
        })
        .sort((a, b) => {
            const timeA = parseTimestampToMillis(a.timestamp);
            const timeB = parseTimestampToMillis(b.timestamp);
            if (timeA !== timeB) return timeA - timeB;
            const stageA = getStageRank(a.service, a.stage, a.message);
            const stageB = getStageRank(b.service, b.stage, b.message);
            if (stageA !== stageB) return stageA - stageB;
            const lineA = (a.line_no !== undefined && a.line_no !== null && a.line_no !== '') ? Number(a.line_no) : Number.MAX_SAFE_INTEGER;
            const lineB = (b.line_no !== undefined && b.line_no !== null && b.line_no !== '') ? Number(b.line_no) : Number.MAX_SAFE_INTEGER;
            return lineA - lineB;
        });

    for (const event of eventsToRender) {
        if (event.display === false) continue;
        const renderKey = makeLogKey(event.service, event.type, event.message, '', (event.line_no ?? '') || (event.timestamp || ''));
        if (AppState.renderedLogKeys.has(renderKey)) continue;

        const serviceClass = `service-${event.service.replace(/-/g, '_')}`;
        const el = document.createElement('div');
        el.className = 'log-entry animate-slide-in';
        const timeMs = parseTimestampToMillis(event.timestamp);
        const lineNo = (event.line_no !== undefined && event.line_no !== null && event.line_no !== '') ? Number(event.line_no) : Number.MAX_SAFE_INTEGER;
        const stageRank = getStageRank(event.service, event.stage, event.message);
        el.dataset.time = String(timeMs);
        el.dataset.line = String(lineNo);
        el.dataset.stageRank = String(stageRank);
        el.innerHTML = `
            <span class="timestamp">${event.timestamp}</span>
            <span class="service ${serviceClass}">[${event.service}]</span>
            <span class="event-type">${event.type}</span>
            <span class="message">${event.message}</span>
        `;

        // Вставка по возрастанию времени; при равенстве — по более «ранней» стадии, затем по меньшему line_no
        eventLogNodes.forEach(node => {
            const children = Array.from(node.querySelectorAll('.log-entry'));
            let inserted = false;
            for (let i = 0; i < children.length; i++) {
                const ch = children[i];
                const chTime = Number(ch.dataset.time || 0) || parseTimestampToMillis(ch.querySelector('.timestamp')?.textContent || '');
                const chLine = ch.dataset.line ? Number(ch.dataset.line) : Number.MAX_SAFE_INTEGER;
                const chStage = ch.dataset.stageRank ? Number(ch.dataset.stageRank) : getStageRank(
                    (ch.querySelector('.service')?.textContent || '').replace(/[\[\]]/g, '').trim(),
                    '',
                    ch.querySelector('.message')?.textContent || ''
                );
                if (chTime > timeMs || (chTime === timeMs && chStage > stageRank) || (chTime === timeMs && chStage === stageRank && chLine > lineNo)) {
                    node.insertBefore(el, ch);
                    inserted = true;
                    break;
                }
            }
            if (!inserted) node.appendChild(el);
        });
        AppState.renderedLogKeys.add(renderKey);
    }
}
function addEventLogFromAPI(logData) {
    const timestamp = logData.timestamp; // используем серверный timestamp, если он есть
    let service = logData.service || 'unknown';
    const type = logData.event_type || logData.type || 'LOG';
    let message = logData.event || logData.message || logData.msg || 'No message';
    const correlationId = logData.correlationId || logData.correlation_id;
    const orderId = logData.order_id || logData.orderId || (AppState.currentOrder && AppState.currentOrder.id);
    const lineNo = logData.line_no || ''; // используем line_no из бэкенда для дедупликации
    // Если в тексте явно указан сервис, используем его вместо источника файла
    const mentionedService = detectServiceFromLogText(message);
    if (mentionedService) {
        service = mentionedService;
    }
    // Переопределяем стадию на основе текста сообщения, т.к. сервер может ошибочно проставить stage
    const derivedStage = detectStageFromMessage(service, message);
    
    // Формируем более устойчивый ключ: сначала correlationId, иначе orderId; extra — line_no или timestamp
    const corrKey = correlationId || orderId || '';
    const extraKey = lineNo || timestamp || '';
    const key = makeLogKey(service, type, message, corrKey, extraKey);
    
    if (AppState.seenLogKeys.has(key)) {
        return false; // пропускаем дубль
    }
    if (correlationId) {
        message = `${message}`;
    } else if (orderId) {
        message = `${message}`;
    }
    
    // Фильтруем только LOG события для отображения на HTML странице
    const shouldDisplay = type === 'LOG';
    
    AppState.eventLog.unshift({ 
        timestamp: timestamp || formatTimestamp(), 
        service, 
        type, 
        message,
        line_no: lineNo,
        stage: derivedStage,
        display: shouldDisplay
    });
    // Реакция UI на ключевые события: меняем статус заказа
    // Обрабатываем события любых типов, а не только LOG, чтобы статус обновлялся корректно
    if (AppState.currentOrder && (!orderId || orderId === AppState.currentOrder.id)) {
        // Отправка на оплату — переходим в PROCESSING
        if (service === 'payment-service' && (derivedStage === 'sent_to_gateway' || message.includes('отправил на оплату'))) {
            updateOrderStatus({ id: AppState.currentOrder.id, status: 'PROCESSING' });
        }
        // Успешная оплата — заказ становится PAID
        if (service === 'order-service' && (derivedStage === 'order_status_paid' || message.toLowerCase().includes('перевёл заказ в статус paid'))) {
            updateOrderStatus({ id: AppState.currentOrder.id, status: 'PAID' });
        }
        // Ошибка оплаты — заказ FAILED
        if ((service === 'order-service' || service === 'payment-service') && (derivedStage === 'payment_failed' || message.toLowerCase().includes('ошибка оплаты'))) {
            updateOrderStatus({ id: AppState.currentOrder.id, status: 'FAILED' });
        }
    }
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
    // Allow callers to suppress some HTTP errors (e.g., 404 during eventual consistency)
    const {
        ignoreStatuses = [], // Array of status codes that should not be treated as errors
        headers: customHeaders = {},
        ...fetchOptions
    } = options;

    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...customHeaders
            },
            ...fetchOptions
        });

        // If the status is acceptable, simply return parsed JSON (or null on 204 / ignored status without body)
        if (response.ok) {
            // For 204-No Content responses just return null
            if (response.status === 204) return null;
            try {
                return await response.json();
            } catch (jsonErr) {
                return null;
            }
        }

        // If we explicitly want to ignore this status (e.g., 404 during eventual consistency), just return null
        if (ignoreStatuses.includes(response.status)) {
            return null;
        }
        // Some endpoints may legitimately return an empty body on success (e.g., 404 bypass)
        return null;
    } catch (error) {
        // Only log to global event log if we are NOT suppressing this status
        const statusMatch = /HTTP\s+(\d{3})/.exec(error.message);
        const statusCode = statusMatch ? parseInt(statusMatch[1], 10) : null;
        if (!statusCode || !ignoreStatuses.includes(statusCode)) {
            console.error('API Request failed:', error);
            addEventLog('ERROR', `API запрос неудачен: ${error.message}`);
        }
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
        let orderObject;
        if (fullOrderResponse && fullOrderResponse.order) {
            orderObject = fullOrderResponse.order;
            addEventLog('SUCCESS', `Детали заказа получены, статус: ${orderObject.status}`);
        } else {
            // Грейсфул-обработка ситуации, когда заказ ещё не доступен для чтения
            addEventLog('WARN', 'Детали заказа пока недоступны (404). Продолжаем с поллингом...');
            orderObject = {
                id: response.orderId,
                status: 'PENDING',
                total: totalAmount,
                delivery_address: deliveryAddress,
                payment_method: paymentMethod
            };
        }
        
        AppState.currentOrder = orderObject;
        AppState.cart = [];
        // После повторного нажатия восстанавливаем дефолтный адрес
        document.getElementById('deliveryAddress').value = DEFAULT_DELIVERY_ADDRESS;
        updateCartDisplay();
        addEventLog('ORDER', 'Корзина очищена, форма сброшена');
        
        showOrderStatus(orderObject);
        // Перед новым опросом корректно останавливаем предыдущий, если он был
        stopOrderStatusPolling('старт нового заказа');
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
        // We ignore 404 here because order might not be committed yet when we poll immediately after creation
        const response = await apiRequest(`${API_ENDPOINTS.orders}/${orderId}`, { ignoreStatuses: [404] });
        return response;
    } catch (error) {
        // Any other error (non-404) will still be handled here
        console.error('Failed to get order status:', error);
        return null;
    }
}

function stopOrderStatusPolling(reason = '') {
    if (AppState.orderPollingInterval) {
        clearInterval(AppState.orderPollingInterval);
        AppState.orderPollingInterval = null;
        if (reason) addEventLog('POLL', `Опрос статуса остановлен: ${reason}`);
    }
}

function startOrderStatusPolling(orderId) {
    addEventLog('POLL', `Начинаем опрос статуса заказа #${orderId}`);
    addEventLog('POLL', `Интервал опроса: каждые 5 секунд`);
    console.log(`Starting status polling for order: ${orderId}`);
    // Сбрасываем предыдущий интервал, если он был
    stopOrderStatusPolling('перезапуск опроса для нового заказа');
    AppState.orderPollCount = 0;

    const poll = async () => {
        AppState.orderPollCount++;
        addEventLog('POLL', `Опрос статуса #${AppState.orderPollCount} для заказа #${orderId}`);
        console.log(`Polling status for order: ${orderId}`);
        
        try {
            const orderResponse = await getOrderStatus(orderId);
            
            console.log('Order response received:', orderResponse);
            
            // Handle 404 ignored case first
            if (orderResponse === null) {
                addEventLog('POLL', `Заказ #${orderId} ещё не готов. Продолжаем ожидание...`);
                return; // Skip further processing until we get a real response
            }

            // Process valid order response
            if (orderResponse && orderResponse.order) {
                console.log('Order data:', orderResponse.order);
                addEventLog('POLL', `Получен статус: ${orderResponse.order.status}`);
                updateOrderStatus(orderResponse.order);
                
                // Stop polling if status is final
                if (['COMPLETED', 'PAID', 'FAILED', 'CANCELLED'].includes(orderResponse.order.status)) {
                    stopOrderStatusPolling(`финальный статус: ${orderResponse.order.status}`);
                    addEventLog('POLL', `Завершаем опрос статуса: ${orderResponse.order.status} (финальный статус)`);
                    addEventLog('POLL', `Всего выполнено опросов: ${AppState.orderPollCount}`);
                    console.log(`Polling stopped for order ${orderId}, final status: ${orderResponse.order.status}`);
                }
            } else {
                // Any unexpected structure will be logged for debugging
                console.error('Invalid order response:', orderResponse);
                addEventLog('ERROR', `Не удалось обработать ответ сервера для заказа #${orderId} (опрос #${AppState.orderPollCount})`);
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
    AppState.orderPollingInterval = setInterval(poll, 5000);
    
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

    // Не понижаем статус: если новый статус «младше» текущего — игнорируем
    const currentRank = STATUS_ORDER[currentStatus] ?? 0;
    const newRank = STATUS_ORDER[order.status] ?? 0;
    if (newRank < currentRank) {
        console.log(`Ignoring downgrade: ${order.status} (${newRank}) < ${currentStatus} (${currentRank})`);
        addEventLog('WARN', `Игнорируем понижение статуса: ${currentStatus} -> ${order.status}`);
        return;
    }

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
        'PROCESSING': '✅ Оплачен',
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
            { id: 'kafka-ui-link', port: '18080' },
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
            { id: 'kafka-ui-link', url: 'http://localhost:18080' },
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
    
    // Запускаем периодический опрос логов
    startLogsPolling();

    
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
            // Align with backend fields and remain backward-compatible
            const totalActual = (
                results.total_orders_created ??
                results.total_created ??
                results.total_requests
            );
            const totalExpected = (
                results.total_requests_expected ??
                results.total_expected ??
                totalActual
            );
            
            addEventLog('LOAD_TEST', `Результаты теста: ожидалось ${totalExpected} запросов, фактически ${totalActual}, ${actualSuccessRate}% успешных (ожидалось ${expectedSuccessRate}%)`);
            
            // Show detailed results in toast
            showToast(
                `📊 Результаты: ожидалось ${totalExpected}, фактически ${totalActual}, ${actualSuccessRate}% успешных`,
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

 