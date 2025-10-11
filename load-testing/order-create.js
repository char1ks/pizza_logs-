import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// =================================================================================
// Test Configuration
// =================================================================================

// Allow overriding rate/duration via environment variables
const RATE = __ENV.RATE ? parseInt(__ENV.RATE, 10) : 1000;
const DURATION = __ENV.DURATION ? String(__ENV.DURATION) : '1m';

export const options = {
  scenarios: {
    constant_request_rate: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.min(Math.max(Math.floor(RATE / 10), 50), 1000),
      maxVUs: Math.min(Math.max(RATE * 2, 200), 2000),
    },
  },
  thresholds: {
    'http_req_failed': [],
    'http_req_duration': ['p(95)<500'],
  },
};

// =================================================================================
// Custom Metrics
// =================================================================================

const orderCreationTime = new Trend('order_creation_time');
const orderSuccessCount = new Counter('order_success_count');
const orderFailureCount = new Counter('order_failure_count');
const orderSuccessRate = new Rate('order_success_rate');

// =================================================================================
// Test Data
// =================================================================================

const API_BASE_URL = 'http://nginx/api/v1';

const pizzas = [
  { id: 'margherita', price: 59900 },
  { id: 'pepperoni', price: 69900 },
  { id: 'quattro-formaggi', price: 79900 },
];

// =================================================================================
// Test Logic
// =================================================================================

// Получаем процент неуспешных заказов из env или опций
const failRate = __ENV.FAIL_RATE ? parseFloat(__ENV.FAIL_RATE) : 0;
console.log(`Running test with ${failRate}% failure rate`);

export default function () {
  group('Create Pizza Order', function () {
    const selectedPizza = pizzas[Math.floor(Math.random() * pizzas.length)];
    // Определяем, будет ли заказ fail
    const shouldFail = Math.random() * 100 < failRate;
    const payload = JSON.stringify({
      items: [{ pizzaId: selectedPizza.id, quantity: 1 }],
      deliveryAddress: `Test Street, User ${__VU}`,
      paymentMethod: 'credit_card',
      userId: `user-${__VU}`,
      forceFail: shouldFail
    });
    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
    };
    const res = http.post(`${API_BASE_URL}/orders`, payload, params);
    const success = check(res, {
      'is status 202': (r) => r.status === 202,
      'response body contains orderId': (r) => r.json('orderId') !== '',
    });
    if (success) {
      orderSuccessCount.add(1);
      orderSuccessRate.add(1);
    } else {
      orderFailureCount.add(1);
      orderSuccessRate.add(0);
    }
    orderCreationTime.add(res.timings.duration);
  });
  sleep(1);
}