"""
Pizza Order System - Payment Mock Service
Event-Driven Saga Architecture

Simulates external payment provider with configurable failure rates
"""

import os
import sys
import json
import random
import time
from typing import Dict, List, Any
from flask import request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone

# Add shared module to path
sys.path.insert(0, '/app/shared')

from base_service import BaseService, generate_id, validate_required_fields, ValidationError

class PaymentMockService(BaseService):
    """Mock payment provider service for testing"""
    
    def __init__(self):
        # Initialize BaseService with a specific service name
        super().__init__('payment-mock-service')
        
        # Configuration for mock behavior
        self.failure_rate = float(os.environ.get('FAILURE_RATE', '0.1'))
        self.delay_ms = int(os.environ.get('DELAY_MS', '100'))
        
        # Setup Flask routes
        self.setup_routes()

        self.logger.info("Payment Mock Service initialized", failure_rate=self.failure_rate, delay_ms=self.delay_ms)

    def setup_routes(self):
        """Setup API routes for the mock service."""
        
        @self.app.route('/api/v1/payments/process', methods=['POST'])
        def process_payment():
            """Simulate processing a payment."""
            # Simulate network delay
            time.sleep(self.delay_ms / 1000.0)

            # Simulate payment failure
            if random.random() < self.failure_rate:
                failure_reason = random.choice([
                    "Insufficient funds",
                    "Card declined by bank",
                    "Security validation failed",
                    "Transaction limit exceeded"
                ])
                self.logger.warning("Payment processing failed (simulated)", reason=failure_reason)
                return jsonify({
                    'success': False,
                    'transactionId': generate_id('txn_fail_'),
                    'failureReason': failure_reason,
                    'timestamp': self.get_timestamp()
                }), 400

            # Simulate successful payment
            transaction_id = generate_id('txn_succ_')
            self.logger.info("Payment processing successful (simulated)", transaction_id=transaction_id)
            return jsonify({
                'success': True,
                'transactionId': transaction_id,
                'message': 'Payment processed successfully',
                'timestamp': self.get_timestamp()
            }), 200

    def get_timestamp(self) -> str:
        """Get current timestamp in ISO 8601 format."""
        return datetime.now(timezone.utc).isoformat()

# ========================================
# SERVICE STARTUP
# ========================================
if __name__ == '__main__':
    service = PaymentMockService()
    
    # Use Gunicorn for production. For simplicity, we run the Flask dev server.
    # In a real setup, you'd have a separate entrypoint script that runs Gunicorn.
    service.app.run(host='0.0.0.0', port=5003, debug=False) 