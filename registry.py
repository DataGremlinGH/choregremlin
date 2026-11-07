"""Single source for currencies, admin settings fields and admin navigation entries.

Currencies: code, symbol, name (and default on the default currency).
Settings: key, type (text, color, radio, toggle), default, label, and choices for radio.
Nav: key (matches the page's active name), endpoint, icon, label, row (1 or 2),
admin_only, and mobile (shown in the phone bottom tab bar).
"""

CURRENCIES = [
    {'code': 'GBP', 'symbol': '£', 'name': 'British pound', 'default': True},
    {'code': 'EUR', 'symbol': '€', 'name': 'Euro'},
    {'code': 'USD', 'symbol': '$', 'name': 'US dollar'},
    {'code': 'CAD', 'symbol': '$', 'name': 'Canadian dollar'},
    {'code': 'AUD', 'symbol': '$', 'name': 'Australian dollar'},
    {'code': 'NZD', 'symbol': '$', 'name': 'New Zealand dollar'},
    {'code': 'ZAR', 'symbol': 'R', 'name': 'South African rand'},
    {'code': 'INR', 'symbol': '₹', 'name': 'Indian rupee'},
    {'code': 'SGD', 'symbol': '$', 'name': 'Singapore dollar'},
    {'code': 'NGN', 'symbol': '₦', 'name': 'Nigerian naira'},
]

SETTINGS = [
    {'key': 'app_name', 'type': 'text', 'default': 'Chore Gremlin', 'label': 'Hub Name',
     'help': 'Shown on the kiosk and browser tab.'},
    {'key': 'theme_color', 'type': 'color', 'default': '#10b981', 'label': 'Theme Colour',
     'help': 'Emerald by default. Used for accents throughout the app.'},
    {'key': 'brightness_mode', 'type': 'radio', 'default': 'dark', 'label': 'Brightness',
     'help': 'Dark is pitch black, Medium is a softer dark grey, Light is a bright daytime look.',
     'choices': [
         {'value': 'dark', 'label': 'Dark', 'icon': 'bi-moon-stars'},
         {'value': 'medium', 'label': 'Medium', 'icon': 'bi-circle-half'},
         {'value': 'light', 'label': 'Light', 'icon': 'bi-sun'},
     ]},
    {'key': 'auto_update_enabled', 'type': 'toggle', 'default': '1', 'label': 'Enable Auto-Update',
     'icon': 'bi-arrow-repeat',
     'help': 'When enabled, the app checks for updates every hour and installs them automatically. Requires deployment via git on the Pi.'},
]

NAV_ITEMS = [
    {'key': 'dashboard', 'endpoint': 'dashboard', 'icon': 'bi-speedometer2', 'label': 'Dashboard', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'family', 'endpoint': 'family_dashboard', 'icon': 'bi-house-heart-fill', 'label': 'Family', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'kids', 'endpoint': 'manage_kids', 'icon': 'bi-people-fill', 'label': 'Kids', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'chores', 'endpoint': 'manage_chores', 'icon': 'bi-list-check', 'label': 'Chores', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'drop', 'endpoint': 'manage_drop_chores', 'icon': 'bi-droplet-fill', 'label': 'Drop', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'payments', 'endpoint': 'manage_payments', 'icon': 'bi-cash-coin', 'label': 'Pay', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'approvals', 'endpoint': 'approvals', 'icon': 'bi-clipboard-check-fill', 'label': 'Approve', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'notices', 'endpoint': 'manage_notices', 'icon': 'bi-megaphone-fill', 'label': 'Notices', 'row': 2, 'admin_only': False, 'mobile': False},
    {'key': 'events', 'endpoint': 'manage_events', 'icon': 'bi-calendar-event-fill', 'label': 'Events', 'row': 2, 'admin_only': False, 'mobile': False},
    {'key': 'logs', 'endpoint': 'view_logs', 'icon': 'bi-clock-history', 'label': 'History', 'row': 2, 'admin_only': False, 'mobile': False},
    {'key': 'parents', 'endpoint': 'manage_parents', 'icon': 'bi-shield-lock', 'label': 'Users', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'currency', 'endpoint': 'currency_page', 'icon': 'bi-coin', 'label': 'Currency', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'storage', 'endpoint': 'storage_page', 'icon': 'bi-device-hdd', 'label': 'Storage', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'network', 'endpoint': 'network_settings', 'icon': 'bi-wifi', 'label': 'Network', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'security', 'endpoint': 'security_page', 'icon': 'bi-shield-fill', 'label': 'Security', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'backup', 'endpoint': 'backup_page', 'icon': 'bi-shield-fill-check', 'label': 'Backup', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'system', 'endpoint': 'system_info', 'icon': 'bi-cpu', 'label': 'System', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'settings', 'endpoint': 'settings', 'icon': 'bi-gear', 'label': 'Settings', 'row': 2, 'admin_only': True, 'mobile': False},
]
