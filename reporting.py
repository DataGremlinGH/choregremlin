"""Financial reporting and ledger export helpers for Phase 13."""

import csv
import io
from datetime import date, datetime

REPORT_KINDS = ('ledger', 'summary', 'savings', 'bills', 'marketplace')

REPORT_LABELS = {
    'ledger': 'Full ledger',
    'summary': 'Financial summary',
    'savings': 'Savings transactions',
    'bills': 'Bill payments',
    'marketplace': 'Marketplace orders',
}

PAYMENT_TYPE_LABELS = {
    'earning': 'Chore earnings',
    'payout': 'Payouts',
    'loan': 'Loan credit',
    'loan_repayment': 'Loan repayments',
    'savings_deposit': 'Savings deposits',
    'savings_withdrawal': 'Savings withdrawals',
    'vault_deposit': 'Goal deposits',
    'vault_withdrawal': 'Goal withdrawals',
    'vault_close_refund': 'Goal refunds',
    'bill_payment': 'Bill payments',
    'marketplace_purchase': 'Shop purchases',
    'marketplace_refund': 'Shop refunds',
    'milestone_reward': 'Milestone rewards',
}

INCOME_TYPES = {'earning', 'loan', 'milestone_reward', 'marketplace_refund'}
EXPENSE_TYPES = {
    'bill_payment', 'loan_repayment', 'marketplace_purchase',
}
SAVINGS_IN_TYPES = {'savings_deposit', 'vault_deposit'}
SAVINGS_OUT_TYPES = {'savings_withdrawal', 'vault_withdrawal', 'vault_close_refund'}


def parse_date(value, label='Date'):
    text = (value or '').strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f'{label} must be a valid date (YYYY-MM-DD).') from exc


def normalize_range(start=None, end=None):
    start_date = parse_date(start, 'Start date')
    end_date = parse_date(end, 'End date')
    if start_date and end_date and start_date > end_date:
        raise ValueError('Start date cannot be after the end date.')
    return (
        start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None,
    )


def normalize_kind(value):
    kind = (value or 'ledger').strip().lower()
    if kind not in REPORT_KINDS:
        raise ValueError('Choose a valid report type.')
    return kind


def in_range(value, start=None, end=None):
    if not value:
        return start is None and end is None
    text = str(value)[:10]
    if start and text < start:
        return False
    if end and text > end:
        return False
    return True


def money(value):
    try:
        return f'{float(value or 0):.2f}'
    except (TypeError, ValueError):
        return '0.00'


def type_label(ptype):
    return PAYMENT_TYPE_LABELS.get(ptype, str(ptype or '').replace('_', ' ').title())


def csv_bytes(headers, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode('utf-8')


def ledger_csv(rows):
    return csv_bytes(
        ['Date', 'Child', 'Type', 'Description', 'Amount', 'Running balance'],
        [
            [
                str(row.get('created_at', ''))[:19],
                row.get('user_name', ''),
                type_label(row.get('type')),
                row.get('description', ''),
                money(row.get('amount')),
                money(row.get('running_balance')),
            ]
            for row in rows
        ],
    )


def summary_csv(summary):
    rows = [
        ['Income', money(summary.get('income'))],
        ['Expenses', money(summary.get('expenses'))],
        ['Savings in', money(summary.get('savings_in'))],
        ['Savings out', money(summary.get('savings_out'))],
        ['Net movement', money(summary.get('net'))],
        ['Transactions', summary.get('transaction_count', 0)],
    ]
    rows.append([])
    rows.append(['By type', 'Amount'])
    for item in summary.get('by_type', []):
        rows.append([item['label'], money(item['total'])])
    rows.append([])
    rows.append(['By child', 'Net'])
    for item in summary.get('by_child', []):
        rows.append([item['name'], money(item['net'])])
    return csv_bytes(['Metric', 'Value'], rows)


def savings_csv(rows):
    return csv_bytes(
        ['Date', 'Child', 'Vault', 'Type', 'Description', 'Amount', 'Balance after'],
        [
            [
                str(row.get('created_at', ''))[:19],
                row.get('user_name', ''),
                row.get('vault_name', ''),
                str(row.get('type', '')).replace('_', ' ').title(),
                row.get('description', ''),
                money(row.get('amount')),
                money(row.get('balance_after')),
            ]
            for row in rows
        ],
    )


def bills_csv(rows):
    return csv_bytes(
        ['Date', 'Child', 'Bill', 'Category', 'Due date', 'Status', 'Amount', 'Paid', 'Late fee'],
        [
            [
                str(row.get('created_at', ''))[:19],
                row.get('user_name', ''),
                row.get('name', ''),
                row.get('category', ''),
                row.get('due_date', ''),
                row.get('status', ''),
                money(row.get('amount')),
                money(row.get('amount_paid')),
                money(row.get('late_fee_amount')),
            ]
            for row in rows
        ],
    )


def marketplace_csv(rows):
    return csv_bytes(
        ['Requested', 'Child', 'Item', 'Category', 'Quantity', 'Total', 'Status'],
        [
            [
                str(row.get('requested_at', ''))[:19],
                row.get('user_name', ''),
                row.get('item_name', ''),
                row.get('item_category', ''),
                row.get('quantity', 0),
                money(row.get('total_amount')),
                row.get('status', ''),
            ]
            for row in rows
        ],
    )


def build_export(kind, data):
    kind = normalize_kind(kind)
    if kind == 'ledger':
        return ledger_csv(data)
    if kind == 'summary':
        return summary_csv(data)
    if kind == 'savings':
        return savings_csv(data)
    if kind == 'bills':
        return bills_csv(data)
    if kind == 'marketplace':
        return marketplace_csv(data)
    raise ValueError('Choose a valid report type.')


def default_filename(kind, start=None, end=None, now=None):
    kind = normalize_kind(kind)
    stamp = (now or datetime.now()).strftime('%Y%m%d-%H%M%S')
    suffix = ''
    if start or end:
        suffix = f"-{start or 'start'}_{end or 'end'}"
    return f"choregremlin-{kind}-{stamp}{suffix}.csv"
