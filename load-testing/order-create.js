import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// =================================================================================
// Test Configuration
// =================================================================================

export const options = {
  // Target RPS (requests per second)
  scenarios: {
    constant_request_rate: {
      executor: 'constant-arrival-rate',
      rate: 1000, // 1000 requests per second
      timeUnit: '1s',
      duration: '30s', // Test duration
      preAllocatedVUs: 100, // Initial number of virtual users
      maxVUs: 500, // Maximum number of virtual users
    },
  },
  // Thresholds for success/failure - removing this as we want to allow higher failure rates
  thresholds: {
    'http_req_failed': [], // Remove threshold to allow configured failure rate
    'http_req_duration': ['p(95)<500'], // 95% of requests should be below 500ms
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