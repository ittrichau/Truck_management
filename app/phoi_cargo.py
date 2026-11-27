"""Shared-cargo validation. Customer #1 retains the existing trip fields and URLs."""
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app import db
from app.models import Phoi, PhoiCargoItem, collection_amount


def revenue_from_values(method, fixed_revenue, weight, price_per_ton):
    if method not in ('fixed', 'per_ton'):
        raise ValueError('Cách tính tiền không hợp lệ.')
    if method == 'fixed':
        return collection_amount(str(fixed_revenue or '0').strip() or '0'), None, None
    raw_weight = str(weight or '').strip().replace(',', '.')
    try:
        tons = Decimal(raw_weight) if raw_weight else None
        if tons is not None:
            if not tons.is_finite():
                raise InvalidOperation
            # Preserve the existing shorthand: 18500 kg -> 18.500 tons.
            if Decimal('1000') <= tons <= Decimal('99999'):
                tons /= Decimal('1000')
            if tons < Decimal('0.001') or tons > Decimal('99.999') or tons != tons.quantize(Decimal('0.001')):
                raise ValueError('Số tấn phải từ 0.001 đến 99.999 và có tối đa 3 số lẻ.')
    except InvalidOperation:
        raise ValueError('Số tấn không hợp lệ.') from None
    price_text = str(price_per_ton or '').strip()
    price = collection_amount(price_text) if price_text else None
    revenue = (tons * price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if tons is not None and price is not None else Decimal('0')
    collection_amount(str(revenue))
    return revenue, tons, price


def sync_cargo_items(trip, raw_items, actor):
    """Keep child identities and enforce ownership; omitted legacy fields preserve children."""
    if raw_items is None:
        return
    try:
        items = json.loads(raw_items)
    except (TypeError, ValueError):
        raise ValueError('Danh sách hàng ghép không hợp lệ. Vui lòng tải lại biểu mẫu.') from None
    if not isinstance(items, list) or len(items) > 2:
        raise ValueError('Mỗi chuyến chỉ được ghép tối đa 3 khách hàng.')
    existing = {str(row.id): row for row in trip.additional_cargo()}
    retained = set()
    for index, values in enumerate(items, start=2):
        if not isinstance(values, dict):
            raise ValueError('Dòng hàng ghép không hợp lệ.')
        identity = str(values.get('id') or '')
        if identity and (identity not in existing or identity in retained):
            raise ValueError('Dòng hàng ghép không thuộc chuyến này hoặc bị gửi trùng.')
        row = existing.get(identity)
        from app.access import permitted_customer_id
        customer_id = permitted_customer_id(values.get('customer_id'), row.customer_id if row else None)
        if not customer_id:
            raise ValueError('Vui lòng chọn khách hàng cho từng dòng hàng ghép.')
        description = str(values.get('cargo_description') or '').strip()
        if not description or len(description) > 300:
            raise ValueError('Vui lòng nhập mô tả hàng ghép, tối đa 300 ký tự.')
        if row is None:
            phoi = trip if isinstance(trip, Phoi) else trip.phoi
            row = PhoiCargoItem(phoi_id=phoi.id, return_trip_id=None if trip is phoi else trip.id,
                               manager_revenue_collected=Decimal('0'))
            db.session.add(row)
        retained.add(identity)
        row.item_order = index
        row.customer_id = customer_id
        row.cargo_description = description
        row.payment_method = values.get('payment_method', 'fixed')
        row.revenue_full, row.cargo_weight_tons, row.price_per_ton = revenue_from_values(
            row.payment_method, values.get('revenue_full'), values.get('cargo_weight_tons'), values.get('price_per_ton'))
        row.revenue_collected = collection_amount(str(values.get('revenue_collected') or '0').strip() or '0')
        if actor.is_manager_or_admin() and 'manager_revenue_collected' in values:
            row.manager_revenue_collected = collection_amount(str(values['manager_revenue_collected'] or '0').strip() or '0')
    for identity, row in existing.items():
        if identity not in retained:
            db.session.delete(row)


def cargo_structure_error(phoi):
    for trip in [phoi, *phoi.return_trips.all()]:
        rows = trip.cargo_rows()
        if len(rows) > 3:
            return 'Mỗi chuyến chỉ được ghép tối đa 3 khách hàng.'
        if len(rows) == 1:
            continue  # Preserve unassigned historical single-customer trips.
        seen = set()
        for row in rows:
            if not row.customer_id:
                return 'Chuyến có hàng ghép phải chọn khách hàng cho tất cả các dòng.'
            if row.customer_id in seen:
                return 'Không được chọn trùng khách hàng trong cùng một chuyến.'
            seen.add(row.customer_id)
            if not (row.cargo_description or '').strip():
                return 'Vui lòng nhập một mô tả hàng cho mỗi khách trong chuyến ghép.'
            try:
                for field in ('revenue_full', 'revenue_collected', 'manager_revenue_collected'):
                    collection_amount(str(getattr(row, field) or 0))
            except ValueError:
                return 'Cước và tiền đã thu của hàng ghép phải là số không âm trong giới hạn cho phép.'
            pending_price = row.payment_method == 'per_ton' and (row.cargo_weight_tons is None or row.price_per_ton is None)
            if not pending_price and (row.revenue_collected or 0) + (row.manager_revenue_collected or 0) > (row.revenue_full or 0):
                return 'Tổng tiền tài xế và quản lý đã thu của mỗi khách không được vượt quá cước của khách đó.'
    return None
