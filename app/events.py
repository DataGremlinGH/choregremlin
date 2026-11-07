from .settings import CURRENCIES
import logging

logging.basicConfig(level=logging.INFO)

class EventPublisher:
    def publish(self, event_type, payload):
        logging.info(f"Publishing event: {event_type}, Payload: {payload}")
        currency = payload.get('currency')
        if currency and currency not in CURRENCIES:
            logging.warning(f"Invalid currency: {currency}")
            return

        # Simulate sending event to an event bus
        print(f"Event sent to event bus: {event_type}, Payload: {payload}")

publisher = EventPublisher()
