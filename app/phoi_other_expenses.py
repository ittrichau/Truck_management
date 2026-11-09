"""Validate and synchronize driver-paid other expenses without changing totals."""
from decimal import Decimal, InvalidOperation

from flask import request

from app import db
from app.models import PhoiExpense


def sync_other_expense(phoi, trip, enabled, raw_amount, description):
    label = f'Chi phí khác chuyến về #{trip.trip_order}' if trip else 'Chi phí khác chuyến đi'
    if enabled not in ('0', '1'):
        raise ValueError(f'{label}: lựa chọn có chi phí không hợp lệ.')
    existing = (
        PhoiExpense.query.filter_by(
            phoi_id=phoi.id, category='other',
            return_trip_id=trip.id if trip else None,
        ).all() if trip is None or trip.id is not None else []
    )
    if enabled == '0':
        for expense in existing:
            db.session.delete(expense)
        return
    description = (description or '').strip()
    if not description:
        raise ValueError(f'{label}: vui lòng nhập nội dung chi phí.')
    if len(description) > 200:
        raise ValueError(f'{label}: nội dung không được quá 200 ký tự.')
    try:
        amount = Decimal((raw_amount or '').strip())
    except InvalidOperation as exc:
        raise ValueError(f'{label}: vui lòng nhập số tiền hợp lệ.') from exc
    if not amount.is_finite() or amount <= 0 or amount > Decimal('9999999999'):
        raise ValueError(f'{label}: số tiền phải lớn hơn 0 và không quá 9.999.999.999 VNĐ.')
    if amount != amount.to_integral_value():
        raise ValueError(f'{label}: số tiền phải là số nguyên VNĐ.')
    # Never silently combine or discard legacy rows through a one-amount form.
    if len(existing) > 1:
        raise ValueError(f'{label}: có nhiều khoản cũ, cần đối soát trước khi chỉnh sửa.')
    expense = existing[0] if existing else PhoiExpense(phoi_id=phoi.id, category='other')
    expense.amount, expense.description = amount, description
    expense.return_trip = trip
    db.session.add(expense)


def sync_outbound_other_expense(phoi):
    if not any(name in request.form for name in ('has_other', 'expense_other', 'expense_other_description')):
        # Older clients that do not submit this section must not erase saved costs.
        return
    enabled = request.form.get('has_other')
    if enabled is None:
        # Old positive-amount payloads still require a meaningful description.
        enabled = '0' if request.form.get('expense_other', '').strip() in ('', '0') else '1'
    sync_other_expense(
        phoi, None, enabled, request.form.get('expense_other', ''),
        request.form.get('expense_other_description', ''),
    )
