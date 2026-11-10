"""Single source for currencies, admin settings fields and admin navigation entries.

Currencies: code, symbol, name (and default on the default currency).
Settings: key, type (text, color, radio, toggle), default, label, and choices for radio.
<<<<<<< HEAD
Nav: key (matches the page's active name), endpoint, icon, label, row (1 or 2),
admin_only, and mobile (shown in the phone bottom tab bar).
=======
Nav: key (matches the page's active name), endpoint, icon, label, row (1 or 2), admin_only.
>>>>>>> v2.0
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
<<<<<<< HEAD
    {'key': 'app_name', 'type': 'text', 'default': 'Chore Gremlin', 'label': 'Hub Name',
     'help': 'Shown on the kiosk and browser tab.'},
    {'key': 'theme_color', 'type': 'color', 'default': '#10b981', 'label': 'Theme Colour',
     'help': 'Emerald by default. Used for accents throughout the app.'},
=======
    {'key': 'app_name', 'type': 'text', 'default': 'ChoreGremlin', 'label': 'Hub Name',
     'help': 'Shown on the kiosk and browser tab.'},
    {'key': 'theme_color', 'type': 'color', 'default': '#00d9ff', 'label': 'Theme Colour',
     'help': 'Used for accents throughout the app.'},
>>>>>>> v2.0
    {'key': 'brightness_mode', 'type': 'radio', 'default': 'dark', 'label': 'Brightness',
     'help': 'Dark is pitch black, Medium is a softer dark grey, Light is a bright daytime look.',
     'choices': [
         {'value': 'dark', 'label': 'Dark', 'icon': 'bi-moon-stars'},
         {'value': 'medium', 'label': 'Medium', 'icon': 'bi-circle-half'},
         {'value': 'light', 'label': 'Light', 'icon': 'bi-sun'},
     ]},
<<<<<<< HEAD
    {'key': 'menu_position', 'type': 'radio', 'default': 'left', 'label': 'Menu Position',
     'help': 'Choose where the main navigation sits on desktop screens.',
     'choices': [
         {'value': 'left', 'label': 'Left side', 'icon': 'bi-layout-sidebar'},
         {'value': 'top_left', 'label': 'Top Left', 'icon': 'bi-align-top'},
         {'value': 'center', 'label': 'Center', 'icon': 'bi-align-center'},
         {'value': 'top_right', 'label': 'Top Right', 'icon': 'bi-align-end'},
         {'value': 'right', 'label': 'Right Side', 'icon': 'bi-layout-sidebar-reverse'},
     ]},
    {'key': 'button_theme', 'type': 'radio', 'default': 'default', 'label': 'Button Theme',
     'help': 'Change the shape, finish and glow of action buttons.',
     'choices': [
         {'value': 'default', 'label': 'Default/Rounded', 'icon': 'bi-circle'},
         {'value': 'flat', 'label': 'Flat/Modern', 'icon': 'bi-square'},
         {'value': 'neumorphic', 'label': 'Neumorphic', 'icon': 'bi-layers'},
         {'value': 'cyber', 'label': 'Cyber', 'icon': 'bi-lightning-charge'},
         {'value': 'glossy', 'label': 'Glossy', 'icon': 'bi-gem'},
     ]},
=======
>>>>>>> v2.0
    {'key': 'auto_update_enabled', 'type': 'toggle', 'default': '1', 'label': 'Enable Auto-Update',
     'icon': 'bi-arrow-repeat',
     'help': 'When enabled, the app checks for updates every hour and installs them automatically. Requires deployment via git on the Pi.'},
]

NAV_ITEMS = [
<<<<<<< HEAD
    {'key': 'dashboard', 'endpoint': 'dashboard', 'icon': 'bi-speedometer2', 'label': 'Dashboard', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'family', 'endpoint': 'family_dashboard', 'icon': 'bi-house-heart-fill', 'label': 'Family', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'kids', 'endpoint': 'manage_kids', 'icon': 'bi-people-fill', 'label': 'Kids', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'chores', 'endpoint': 'manage_chores', 'icon': 'bi-list-check', 'label': 'Chores', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'drop', 'endpoint': 'manage_drop_chores', 'icon': 'bi-droplet-fill', 'label': 'Drop', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'payments', 'endpoint': 'manage_payments', 'icon': 'bi-cash-coin', 'label': 'Pay', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'bank', 'endpoint': 'bank', 'icon': 'bi-bank', 'label': 'Bank', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'bills', 'endpoint': 'bills', 'icon': 'bi-receipt', 'label': 'Bills', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'marketplace', 'endpoint': 'marketplace', 'icon': 'bi-shop', 'label': 'Shop', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'approvals', 'endpoint': 'approvals', 'icon': 'bi-clipboard-check-fill', 'label': 'Approve', 'row': 1, 'admin_only': False, 'mobile': True},
    {'key': 'rewards', 'endpoint': 'rewards', 'icon': 'bi-trophy-fill', 'label': 'Rewards', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'achievements', 'endpoint': 'achievements_page', 'icon': 'bi-award-fill', 'label': 'Achievements', 'row': 1, 'admin_only': False, 'mobile': False},
    {'key': 'reports', 'endpoint': 'reports_page', 'icon': 'bi-graph-up-arrow', 'label': 'Reports', 'row': 2, 'admin_only': False, 'mobile': False},
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
    {'key': 'snapshots', 'endpoint': 'snapshots_page', 'icon': 'bi-clock-history', 'label': 'Snapshots', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'releases', 'endpoint': 'releases_page', 'icon': 'bi-box-seam', 'label': 'Releases', 'row': 2, 'admin_only': True, 'mobile': False},
    {'key': 'settings', 'endpoint': 'settings', 'icon': 'bi-gear', 'label': 'Settings', 'row': 2, 'admin_only': True, 'mobile': False},
=======
    {'key': 'dashboard', 'endpoint': 'dashboard', 'icon': 'bi-speedometer2', 'label': 'Dashboard', 'row': 1, 'admin_only': False},
    {'key': 'family', 'endpoint': 'family_dashboard', 'icon': 'bi-house-heart-fill', 'label': 'Family', 'row': 1, 'admin_only': False},
    {'key': 'kids', 'endpoint': 'manage_kids', 'icon': 'bi-people-fill', 'label': 'Kids', 'row': 1, 'admin_only': False},
    {'key': 'chores', 'endpoint': 'manage_chores', 'icon': 'bi-list-check', 'label': 'Chores', 'row': 1, 'admin_only': False},
    {'key': 'drop', 'endpoint': 'manage_drop_chores', 'icon': 'bi-droplet-fill', 'label': 'Drop', 'row': 1, 'admin_only': False},
    {'key': 'payments', 'endpoint': 'manage_payments', 'icon': 'bi-cash-coin', 'label': 'Pay', 'row': 1, 'admin_only': False},
    {'key': 'approvals', 'endpoint': 'approvals', 'icon': 'bi-clipboard-check-fill', 'label': 'Approve', 'row': 1, 'admin_only': False},
    {'key': 'notices', 'endpoint': 'manage_notices', 'icon': 'bi-megaphone-fill', 'label': 'Notices', 'row': 2, 'admin_only': False},
    {'key': 'events', 'endpoint': 'manage_events', 'icon': 'bi-calendar-event-fill', 'label': 'Events', 'row': 2, 'admin_only': False},
    {'key': 'logs', 'endpoint': 'view_logs', 'icon': 'bi-clock-history', 'label': 'History', 'row': 2, 'admin_only': False},
    {'key': 'parents', 'endpoint': 'manage_parents', 'icon': 'bi-shield-lock', 'label': 'Users', 'row': 2, 'admin_only': True},
    {'key': 'currency', 'endpoint': 'currency_page', 'icon': 'bi-coin', 'label': 'Currency', 'row': 2, 'admin_only': True},
    {'key': 'storage', 'endpoint': 'storage_page', 'icon': 'bi-device-hdd', 'label': 'Storage', 'row': 2, 'admin_only': True},
    {'key': 'network', 'endpoint': 'network_settings', 'icon': 'bi-wifi', 'label': 'Network', 'row': 2, 'admin_only': True},
    {'key': 'security', 'endpoint': 'security_page', 'icon': 'bi-shield-fill', 'label': 'Security', 'row': 2, 'admin_only': True},
    {'key': 'backup', 'endpoint': 'backup_page', 'icon': 'bi-shield-fill-check', 'label': 'Backup', 'row': 2, 'admin_only': True},
    {'key': 'system', 'endpoint': 'system_info', 'icon': 'bi-cpu', 'label': 'System', 'row': 2, 'admin_only': True},
    {'key': 'settings', 'endpoint': 'settings', 'icon': 'bi-gear', 'label': 'Settings', 'row': 2, 'admin_only': True},
>>>>>>> v2.0
]
