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
  // Thresholds for success/failure
  thresholds: {
    'http_req_failed': ['rate<0.01'], // less than 1% failed requests
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

export default function () {
  group('Create Pizza Order', function () {
    // Select a random pizza
    const selectedPizza = pizzas[Math.floor(Math.random() * pizzas.length)];

    // Construct order payload
    const payload = JSON.stringify({
      items: [{ pizzaId: selectedPizza.id, quantity: 1 }],
      deliveryAddress: `123 Test Street, User ${__VU}`, // Unique address per virtual user
      paymentMethod: 'credit_card',
      userId: `user-${__VU}`,
    });

    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
    };

    // Send POST request to create an order
    const res = http.post(`${API_BASE_URL}/orders`, payload, params);

    // Check response and record metrics
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

  // Small sleep to avoid overwhelming the system between iterations within a VU
  sleep(1);
} 