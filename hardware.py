"""Hardware abstraction for the Chore Gremlin kiosk.

Raspberry Pi GPIO libraries are imported lazily so importing this module is safe
on development machines, containers and other non-Pi systems.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

LOGGER = logging.getLogger(__name__)

MODE_ENV = 'CHOREGREMLIN_HARDWARE'
BUZZER_PIN_ENV = 'CHOREGREMLIN_BUZZER_PIN'
BUTTON_PINS_ENV = 'CHOREGREMLIN_BUTTON_PINS'
RASPBERRY_PI_MODEL_PATH = '/proc/device-tree/model'

BEEP_PATTERNS = {
    'success': (0.08, 0.06, 0.08),
    'start': (0.06,),
    'cancel': (0.2,),
    'error': (0.35, 0.10, 0.35),
}


def _normalize_mode(value):
    mode = str(value or 'auto').strip().lower()
    return mode if mode in {'auto', 'mock', 'rpi'} else 'auto'


def normalize_tag(tag):
    value = str(tag or '').strip()
    if not value:
        return ''
    return value.replace(' ', '').replace(':', '').replace('-', '').upper()


def _normalize_button(name):
    return str(name or '').strip().lower()


def _beep_durations(pattern):
    if isinstance(pattern, (tuple, list)):
        try:
            durations = tuple(float(item) for item in pattern)
            if durations:
                return durations
        except (TypeError, ValueError):
            pass
    return BEEP_PATTERNS.get(str(pattern or 'success').strip().lower(), BEEP_PATTERNS['success'])


def raspberry_pi_model():
    try:
        with open(RASPBERRY_PI_MODEL_PATH, 'rb') as handle:
            return handle.read().decode('utf-8', 'replace').strip('\x00').strip()
    except OSError:
        return ''


def is_raspberry_pi():
    return 'raspberry pi' in raspberry_pi_model().lower()


def _parse_button_pins(value):
    buttons = {}
    for item in str(value or '').split(','):
        item = item.strip()
        if not item:
            continue
        if '=' in item:
            name, pin = item.split('=', 1)
        else:
            name, pin = f'button{len(buttons) + 1}', item
        name = _normalize_button(name)
        try:
            buttons[name] = int(pin.strip())
        except ValueError:
            LOGGER.warning('Ignoring invalid hardware button pin: %s', item)
    return buttons


class HardwareProvider:
    name = 'base'
    is_mock = False

    def __init__(self):
        self._started = False
        self._rfid_callbacks = []
        self._button_callbacks = {}

    @property
    def started(self):
        return self._started

    def start(self):
        self._started = True
        return True

    def stop(self):
        self._started = False
        self._rfid_callbacks.clear()
        self._button_callbacks.clear()

    def available(self):
        return self._started

    def on_rfid(self, callback: Callable[[str], None]):
        if not callable(callback):
            raise TypeError('RFID callback must be callable')
        self._rfid_callbacks.append(callback)

    def on_button(self, name, callback: Callable[[str], None]):
        if not callable(callback):
            raise TypeError('Button callback must be callable')
        self._button_callbacks.setdefault(_normalize_button(name), []).append(callback)

    def _invoke(self, callback, *args):
        try:
            callback(*args)
        except Exception:
            LOGGER.exception('Hardware callback failed')

    def trigger_rfid(self, tag):
        normalized = normalize_tag(tag)
        if not normalized:
            LOGGER.warning('Ignoring empty RFID tag')
            return False
        for callback in tuple(self._rfid_callbacks):
            self._invoke(callback, normalized)
        return True

    def trigger_button(self, name):
        normalized = _normalize_button(name)
        if not normalized:
            return False
        for callback in tuple(self._button_callbacks.get(normalized, ())):
            self._invoke(callback, normalized)
        return True

    def simulate_rfid(self, tag):
        raise NotImplementedError('RFID simulation requires the mock hardware backend')

    def simulate_button(self, name):
        raise NotImplementedError('Button simulation requires the mock hardware backend')

    def beep(self, pattern='success'):
        raise NotImplementedError('This hardware provider has no buzzer')


class MockHardware(HardwareProvider):
    name = 'mock'
    is_mock = True

    def __init__(self):
        super().__init__()
        self.events = []
        self.beeps = []

    def beep(self, pattern='success'):
        self.beeps.append(pattern)
        self.events.append({'type': 'beep', 'value': pattern})
        return True

    def trigger_rfid(self, tag):
        result = super().trigger_rfid(tag)
        if result:
            self.events.append({'type': 'rfid', 'value': normalize_tag(tag)})
        return result

    def trigger_button(self, name):
        result = super().trigger_button(name)
        if result:
            self.events.append({'type': 'button', 'value': _normalize_button(name)})
        return result

    def simulate_rfid(self, tag):
        return self.trigger_rfid(tag)

    def simulate_button(self, name):
        return self.trigger_button(name)


class RaspberryPiHardware(HardwareProvider):
    name = 'rpi'
    is_mock = False

    def __init__(self):
        super().__init__()
        self._ready = False
        self._buzzer = None
        self._buttons = {}

    def available(self):
        return self._ready

    def start(self):
        if self._started:
            return self._ready
        if not is_raspberry_pi():
            LOGGER.warning('Raspberry Pi hardware requested on a non-Pi system; using mock hardware')
            return False
        try:
            from gpiozero import Button, Buzzer
        except Exception as exc:
            LOGGER.warning('gpiozero is unavailable; using mock hardware: %s', exc)
            return False
        try:
            buzzer_pin = os.environ.get(BUZZER_PIN_ENV, '').strip()
            if buzzer_pin:
                self._buzzer = Buzzer(int(buzzer_pin))
            for name, pin in _parse_button_pins(os.environ.get(BUTTON_PINS_ENV, '')).items():
                button = Button(pin, pull_up=True, bounce_time=0.1)
                button.when_pressed = lambda name=name: self.trigger_button(name)
                self._buttons[name] = button
        except Exception as exc:
            LOGGER.warning('Raspberry Pi GPIO setup failed; using mock hardware: %s', exc)
            self._close_devices()
            return False
        self._started = True
        self._ready = True
        return True

    def stop(self):
        self._close_devices()
        self._ready = False
        super().stop()

    def beep(self, pattern='success'):
        if not self._ready or self._buzzer is None:
            return False
        durations = _beep_durations(pattern)
        try:
            for index, duration in enumerate(durations):
                if index % 2 == 0:
                    self._buzzer.on()
                else:
                    self._buzzer.off()
                time.sleep(duration)
            self._buzzer.off()
            return True
        except Exception:
            LOGGER.exception('Buzzer failed')
            try:
                self._buzzer.off()
            except Exception:
                pass
            return False

    def _close_devices(self):
        for button in self._buttons.values():
            try:
                button.close()
            except Exception:
                pass
        self._buttons.clear()
        if self._buzzer is not None:
            try:
                self._buzzer.close()
            except Exception:
                pass
            self._buzzer = None


class HardwareManager:
    def __init__(self, mode=None, provider=None):
        self.mode = _normalize_mode(mode if mode is not None else os.environ.get(MODE_ENV, 'auto'))
        self.fallback = False
        self.provider = provider or self._select_provider()
        self.start()

    def _select_provider(self):
        if self.mode == 'mock':
            return MockHardware()
        if self.mode == 'rpi' or (self.mode == 'auto' and is_raspberry_pi()):
            provider = RaspberryPiHardware()
            if provider.start():
                return provider
            self.fallback = True
            return MockHardware()
        return MockHardware()

    @property
    def backend(self):
        return self.provider.name

    @property
    def is_mock(self):
        return self.provider.is_mock

    def start(self):
        return self.provider.start()

    def stop(self):
        return self.provider.stop()

    def available(self):
        return self.provider.available()

    def on_rfid(self, callback):
        return self.provider.on_rfid(callback)

    def on_button(self, name, callback):
        return self.provider.on_button(name, callback)

    def trigger_rfid(self, tag):
        return self.provider.trigger_rfid(tag)

    def trigger_button(self, name):
        return self.provider.trigger_button(name)

    def simulate_rfid(self, tag):
        if not self.provider.is_mock:
            raise RuntimeError('RFID simulation requires the mock hardware backend')
        return self.provider.simulate_rfid(tag)

    def simulate_button(self, name):
        if not self.provider.is_mock:
            raise RuntimeError('Button simulation requires the mock hardware backend')
        return self.provider.simulate_button(name)

    def beep(self, pattern='success'):
        return self.provider.beep(pattern)

    def status(self):
        return {
            'mode': self.mode,
            'backend': self.backend,
            'is_mock': self.is_mock,
            'available': self.available(),
            'fallback': self.fallback,
            'raspberry_pi': is_raspberry_pi(),
        }
