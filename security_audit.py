"""Security headers and an administrator-facing audit for Phase 16."""

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'X-Permitted-Cross-Domain-Policies': 'none',
    'Content-Security-Policy': (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' data: https://cdn.jsdelivr.net; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    ),
}

STATUS_ORDER = {'fail': 0, 'warn': 1, 'pass': 2}


def headers_for(https=False):
    headers = dict(SECURITY_HEADERS)
    if https:
        headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return headers


def apply_headers(response, https=False):
    for name, value in headers_for(https).items():
        response.headers.setdefault(name, value)
    return response


def _check(key, title, status, detail, remediation=''):
    return {
        'key': key,
        'title': title,
        'status': status,
        'detail': detail,
        'remediation': remediation,
    }


def audit(context):
    context = context or {}
    checks = []

    admin_count = int(context.get('admin_count') or 0)
    admins_with_2fa = int(context.get('admins_with_2fa') or 0)
    if admin_count == 0:
        checks.append(_check(
            'admin_2fa', 'Administrator two-factor authentication', 'warn',
            'No administrator account exists yet.',
            'Complete first-run setup and enrol an authenticator app.',
        ))
    elif admins_with_2fa < admin_count:
        checks.append(_check(
            'admin_2fa', 'Administrator two-factor authentication', 'fail',
            f'{admins_with_2fa} of {admin_count} administrator account(s) have 2FA.',
            'Sign in as each administrator and complete authenticator setup.',
        ))
    else:
        checks.append(_check(
            'admin_2fa', 'Administrator two-factor authentication', 'pass',
            f'All {admin_count} administrator account(s) use 2FA.',
        ))

    https = bool(context.get('https'))
    checks.append(_check(
        'https', 'Encrypted HTTPS connection', 'pass' if https else 'warn',
        'HTTPS is enabled.' if https else 'HTTPS is not enabled.',
        '' if https else 'Re-run the installer and choose HTTPS with the local certificate.',
    ))

    remote_access = bool(context.get('remote_access'))
    if remote_access and not https:
        checks.append(_check(
            'remote_access', 'Remote access safety', 'fail',
            'Remote access is enabled without HTTPS.',
            'Disable remote access or enable HTTPS before allowing remote sign-in.',
        ))
    else:
        checks.append(_check(
            'remote_access', 'Remote access safety', 'pass',
            'Remote access is within a safe configuration.' if remote_access
            else 'Remote access is disabled.',
        ))

    csrf_enabled = bool(context.get('csrf_enabled'))
    checks.append(_check(
        'csrf', 'Cross-site request forgery protection', 'pass' if csrf_enabled else 'fail',
        'CSRF protection is enabled.' if csrf_enabled else 'CSRF protection is disabled.',
        '' if csrf_enabled else 'Enable Flask-WTF CSRF protection for every form.',
    ))

    cookie_secure = bool(context.get('session_cookie_secure'))
    cookie_http_only = bool(context.get('session_cookie_httponly'))
    cookie_same_site = (context.get('session_cookie_samesite') or '').lower() in ('lax', 'strict')
    cookie_status = 'pass'
    cookie_detail = 'Session cookies use HttpOnly and SameSite protection.'
    if not cookie_http_only or not cookie_same_site:
        cookie_status = 'fail'
        cookie_detail = 'Session cookies are missing HttpOnly or SameSite protection.'
    elif https and not cookie_secure:
        cookie_status = 'warn'
        cookie_detail = 'HTTPS is enabled but session cookies are not marked Secure.'
    checks.append(_check(
        'session_cookie', 'Session cookie hardening', cookie_status, cookie_detail,
        'Set SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE and Secure when using HTTPS.',
    ))

    secret_length = int(context.get('secret_key_length') or 0)
    checks.append(_check(
        'secret_key', 'Session signing secret', 'pass' if secret_length >= 32 else 'fail',
        f'Secret key length is {secret_length} characters.',
        '' if secret_length >= 32 else 'Replace the session secret with a random 32+ character key.',
    ))

    backup_count = int(context.get('backup_count') or 0)
    checks.append(_check(
        'backups', 'Database backups', 'pass' if backup_count > 0 else 'warn',
        f'{backup_count} database backup(s) are stored.',
        '' if backup_count > 0 else 'Create a backup or snapshot before making changes.',
    ))

    snapshot_count = int(context.get('snapshot_count') or 0)
    checks.append(_check(
        'snapshots', 'Rollback snapshots', 'pass' if snapshot_count > 0 else 'warn',
        f'{snapshot_count} snapshot(s) are stored.',
        '' if snapshot_count > 0 else 'Create a snapshot from the Snapshots page.',
    ))

    failed_logins = int(context.get('recent_failed_logins') or 0)
    checks.append(_check(
        'failed_logins', 'Recent failed sign-ins',
        'warn' if failed_logins >= 5 else 'pass',
        f'{failed_logins} failed sign-in attempt(s) in the last 24 hours.',
        '' if failed_logins < 5 else 'Review the login audit log and change weak passwords.',
    ))

    data_dir_mode = context.get('data_dir_mode')
    if data_dir_mode is None:
        checks.append(_check(
            'data_dir', 'Data folder permissions', 'warn',
            'Data folder permissions could not be read.',
            'Check that the data folder exists and is owned by the service account.',
        ))
    elif not (data_dir_mode & 0o200):
        checks.append(_check(
            'data_dir', 'Data folder permissions', 'fail',
            'The data folder is not writable by the service.',
            'Fix ownership and permissions on the data folder.',
        ))
    elif data_dir_mode & 0o002:
        checks.append(_check(
            'data_dir', 'Data folder permissions', 'fail',
            'The data folder is world-writable.',
            'Remove world-write permission (chmod o-w) from the data folder.',
        ))
    else:
        checks.append(_check(
            'data_dir', 'Data folder permissions', 'pass',
            'The data folder has safe permissions.',
        ))

    debug = bool(context.get('debug'))
    checks.append(_check(
        'debug', 'Debug mode', 'fail' if debug else 'pass',
        'Debug mode is enabled.' if debug else 'Debug mode is disabled.',
        '' if not debug else 'Run the production service with debug disabled.',
    ))

    update_status = (context.get('update_status') or 'unknown').lower()
    checks.append(_check(
        'updates', 'Application updates',
        'warn' if update_status in ('error', 'unknown') else 'pass',
        f'Last update status: {update_status.replace("_", " ")}.',
        '' if update_status not in ('error', 'unknown')
        else 'Check for updates from the Snapshots & Updates page.',
    ))

    return checks


def summary(checks):
    counts = {'pass': 0, 'warn': 0, 'fail': 0}
    for check in checks:
        counts[check['status']] = counts.get(check['status'], 0) + 1
    total = len(checks) or 1
    worst = min(
        (check['status'] for check in checks),
        key=lambda status: STATUS_ORDER.get(status, 3),
        default='pass',
    )
    return {
        'total': len(checks),
        'pass': counts['pass'],
        'warn': counts['warn'],
        'fail': counts['fail'],
        'score': round(counts['pass'] / total * 100),
        'worst': worst,
    }


VULNERABILITY_CLASSES = (
    {
        'key': 'sql_injection',
        'name': 'SQL Injection',
        'summary': 'Untrusted input must never change the structure of a database query.',
        'defense': 'SQLite parameter binding for values; dynamic column names are allow-listed.',
    },
    {
        'key': 'csrf',
        'name': 'CSRF',
        'summary': 'State-changing requests must carry a valid cross-site request forgery token.',
        'defense': 'Flask-WTF CSRF protection is global; only the local RFID scanner is exempt.',
    },
    {
        'key': 'xss',
        'name': 'XSS',
        'summary': 'Stored or reflected input must not become executable markup.',
        'defense': 'Jinja autoescaping, safe token-icon construction and validated stored colours.',
    },
    {
        'key': 'broken_authentication',
        'name': 'Broken Authentication',
        'summary': 'Every privileged route must require a live, correctly scoped account.',
        'defense': 'Central route-access map, database-backed roles, administrator 2FA and login lockout.',
    },
    {
        'key': 'session_hijacking',
        'name': 'Session Hijacking',
        'summary': 'Session cookies and signing secrets must resist theft and tampering.',
        'defense': 'HttpOnly/SameSite cookies, Secure cookies under HTTPS and a strong signing secret.',
    },
    {
        'key': 'security_misconfiguration',
        'name': 'Security Misconfiguration',
        'summary': 'Production settings, headers and data permissions must stay safe.',
        'defense': 'Security headers, debug disabled, restricted data folder and update monitoring.',
    },
)

COMPLIANCE_STATUS_ORDER = {'vulnerable': 0, 'monitored': 1, 'protected': 2}


def _compliance_row(spec, status, detail, live, remediation=''):
    return {
        'key': spec['key'],
        'name': spec['name'],
        'summary': spec['summary'],
        'defense': spec['defense'],
        'status': status,
        'status_label': status.title(),
        'detail': detail,
        'live': bool(live),
        'live_label': 'Verified' if live else 'Not verified',
        'remediation': remediation,
    }


def _compliance_status(issues, warnings, live):
    if issues:
        return 'vulnerable'
    if warnings or not live:
        return 'monitored'
    return 'protected'


def compliance_registry(context=None):
    """Return the vulnerability-class compliance registry with live verification."""
    context = context or {}
    checks = {check['key']: check for check in audit(context)}
    specs = {item['key']: item for item in VULNERABILITY_CLASSES}
    rows = []

    sql_live = bool(context.get('sql_parameter_probe', True))
    sql_issues = [] if sql_live else ['The live SQL parameter-binding probe failed.']
    rows.append(_compliance_row(
        specs['sql_injection'],
        _compliance_status(sql_issues, [], sql_live),
        'Live parameter-binding probe passed.' if sql_live
        else 'Live parameter-binding probe did not return the literal payload.',
        sql_live,
        '' if sql_live else 'Review database helpers and reject string-built SQL immediately.',
    ))

    csrf_enabled = bool(context.get('csrf_enabled', True))
    exempt = context.get('csrf_exempt_endpoints', ('kiosk_rfid_scan',))
    try:
        exempt = set(exempt or ())
    except TypeError:
        exempt = {'unexpected-csrf-exemption'}
    unexpected_exemptions = sorted(exempt - {'kiosk_rfid_scan'})
    csrf_issues = []
    if not csrf_enabled:
        csrf_issues.append('CSRF protection is disabled.')
    if unexpected_exemptions:
        csrf_issues.append(
            'Unexpected CSRF exemptions: ' + ', '.join(unexpected_exemptions) + '.'
        )
    csrf_live = csrf_enabled and not unexpected_exemptions
    rows.append(_compliance_row(
        specs['csrf'],
        _compliance_status(csrf_issues, [], csrf_live),
        'CSRF is enforced on all state-changing routes; only the local RFID scanner is exempt.'
        if csrf_live else ' '.join(csrf_issues),
        csrf_live,
        '' if csrf_live else 'Enable CSRF protection and remove unexpected route exemptions.',
    ))

    autoescape = bool(context.get('jinja_autoescape', True))
    escape_probe = bool(context.get('xss_escape_probe', True))
    xss_live = autoescape and escape_probe
    xss_issues = []
    if not autoescape:
        xss_issues.append('Jinja autoescaping is disabled.')
    if not escape_probe:
        xss_issues.append('The live template escaping probe failed.')
    rows.append(_compliance_row(
        specs['xss'],
        _compliance_status(xss_issues, [], xss_live),
        'Live template escaping probe passed and stored colour/icon values are sanitised.'
        if xss_live else ' '.join(xss_issues),
        xss_live,
        '' if xss_live else 'Restore autoescaping and sanitise every value rendered as markup or CSS.',
    ))

    admin_count = int(context.get('admin_count') or 0)
    admins_with_2fa = int(context.get('admins_with_2fa') or 0)
    route_rules_complete = bool(context.get('route_rules_complete', True))
    login_lockout = bool(context.get('login_lockout_enabled', True))
    auth_issues = []
    auth_warnings = []
    if admin_count and admins_with_2fa < admin_count:
        auth_issues.append(
            f'{admins_with_2fa} of {admin_count} administrator account(s) have 2FA.'
        )
    if not route_rules_complete:
        auth_issues.append('One or more routes have no explicit access rule.')
    if not login_lockout:
        auth_issues.append('Login lockout protection is not configured.')
    if admin_count == 0:
        auth_warnings.append('No administrator account exists yet.')
    if context.get('remote_access') and not context.get('https'):
        auth_warnings.append('Remote access is enabled without HTTPS.')
    auth_live = route_rules_complete and login_lockout and (
        admin_count == 0 or admins_with_2fa >= admin_count
    )
    rows.append(_compliance_row(
        specs['broken_authentication'],
        _compliance_status(auth_issues, auth_warnings, auth_live),
        '; '.join(auth_issues + auth_warnings)
        if auth_issues or auth_warnings else
        'All privileged routes are covered and every administrator uses 2FA.',
        auth_live,
        '' if not auth_issues else 'Close access-control gaps, enrol admin 2FA and keep lockout enabled.',
    ))

    cookie_http_only = bool(context.get('session_cookie_httponly'))
    cookie_same_site = (context.get('session_cookie_samesite') or '').lower() in ('lax', 'strict')
    cookie_secure = bool(context.get('session_cookie_secure'))
    secret_length = int(context.get('secret_key_length') or 0)
    https = bool(context.get('https'))
    session_issues = []
    session_warnings = []
    if not cookie_http_only or not cookie_same_site:
        session_issues.append('Session cookies are missing HttpOnly or SameSite protection.')
    if secret_length < 32:
        session_issues.append(f'The session signing secret is only {secret_length} characters.')
    if not https:
        session_warnings.append('HTTPS is disabled, so sessions are not encrypted in transit.')
    elif not cookie_secure:
        session_warnings.append('HTTPS is enabled but the session cookie is not marked Secure.')
    session_live = not session_issues and (not https or cookie_secure)
    rows.append(_compliance_row(
        specs['session_hijacking'],
        _compliance_status(session_issues, session_warnings, session_live),
        '; '.join(session_issues + session_warnings)
        if session_issues or session_warnings else
        'Session cookies and the signing secret pass live configuration checks.',
        session_live,
        '' if not session_issues else 'Harden cookie flags and replace the session signing secret.',
    ))

    headers_configured = bool(context.get('security_headers', True))
    debug = bool(context.get('debug'))
    data_status = checks['data_dir']['status']
    remote_without_https = bool(context.get('remote_access')) and not https
    config_issues = []
    config_warnings = []
    if not headers_configured:
        config_issues.append('Required security headers are missing.')
    if debug:
        config_issues.append('Debug mode is enabled.')
    if data_status == 'fail':
        config_issues.append(checks['data_dir']['detail'])
    if remote_without_https:
        config_issues.append('Remote access is enabled without HTTPS.')
    if not https:
        config_warnings.append('HTTPS is disabled.')
    if checks['updates']['status'] == 'warn':
        config_warnings.append(checks['updates']['detail'])
    config_live = headers_configured and not debug and data_status != 'fail' and not remote_without_https
    rows.append(_compliance_row(
        specs['security_misconfiguration'],
        _compliance_status(config_issues, config_warnings, config_live),
        '; '.join(config_issues + config_warnings)
        if config_issues or config_warnings else
        'Security headers, debug state, data permissions and remote-access settings are safe.',
        config_live,
        '' if not config_issues else 'Correct production configuration before exposing the hub.',
    ))

    return rows


def compliance_summary(rows):
    rows = list(rows or [])
    counts = {'protected': 0, 'monitored': 0, 'vulnerable': 0}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    total = len(rows) or 1
    worst = min(
        (row['status'] for row in rows),
        key=lambda status: COMPLIANCE_STATUS_ORDER.get(status, 3),
        default='protected',
    )
    return {
        'total': len(rows),
        'protected': counts['protected'],
        'monitored': counts['monitored'],
        'vulnerable': counts['vulnerable'],
        'worst': worst,
        'score': round(counts['protected'] / total * 100),
    }
