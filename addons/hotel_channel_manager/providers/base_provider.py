# -*- coding: utf-8 -*-
import logging
from abc import ABC, abstractmethod

_logger = logging.getLogger(__name__)

# Provider registry: provider_code -> class
_PROVIDER_REGISTRY = {}


def register_provider(code):
    """Decorator to register a channel provider class."""
    def decorator(cls):
        _PROVIDER_REGISTRY[code] = cls
        return cls
    return decorator


def get_provider(code, config):
    """Instantiate and return the provider for the given code."""
    cls = _PROVIDER_REGISTRY.get(code)
    if not cls:
        raise ValueError(f'No provider registered for code: {code}')
    return cls(config)


class AbstractChannelProvider(ABC):
    """Base class for all OTA channel provider adapters."""

    def __init__(self, config):
        """
        :param config: channel.manager.config recordset (single record)
        """
        self.config = config
        self.api_url = config.api_url or ''
        self.api_key = config.api_key or ''
        self.api_secret = config.api_secret or ''
        self.property_id = config.property_id or ''

    @abstractmethod
    def test_connection(self):
        """Test API connectivity.

        :returns: tuple (success: bool, message: str)
        """

    @abstractmethod
    def push_availability(self, data):
        """Push room availability to channel.

        :param data: dict {channel_room_type_id: {date_str: count}}
        :returns: response dict or None
        """

    @abstractmethod
    def push_rates(self, data):
        """Push rates to channel.

        :param data: dict {channel_rate_plan_id: {channel_room_type_id: {date_str: amount}}}
        :returns: response dict or None
        """

    @abstractmethod
    def push_restrictions(self, data):
        """Push restrictions to channel.

        :param data: dict {channel_rate_plan_id: {date_str: {min_stay, stop_sell}}}
        :returns: response dict or None
        """

    @abstractmethod
    def push_cancellation(self, channel_booking_id):
        """Push cancellation notification to channel.

        :param channel_booking_id: str
        :returns: response dict or None
        """

    @abstractmethod
    def parse_booking_webhook(self, payload):
        """Parse inbound booking webhook payload into standardized dict.

        :param payload: dict (parsed JSON/XML)
        :returns: dict with keys:
            channel_booking_id, guest_name, guest_email, guest_phone,
            checkin_date, checkout_date, channel_room_type_id,
            adults, children, total_amount, notes
        """

    @abstractmethod
    def parse_cancellation_webhook(self, payload):
        """Parse inbound cancellation webhook payload.

        :param payload: dict (parsed JSON/XML)
        :returns: dict with keys: channel_booking_id
        """
