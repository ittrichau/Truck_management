"""Repair expense form synchronization and receipt persistence for PHOI."""
from decimal import Decimal, InvalidOperation

from flask import request
from flask_login import current_user

from app import db
from app.models import PhoiAttachment, PhoiExpense
from app.phoi_attachments import save_phoi_attachment


def _sync_standard_expenses(phoi):
    standard_expenses = [
        ('porter_fee', 'Bồi dưỡng bốc vác'),
        ('other', 'Chi phí khác'),
    ]
    # Phí đường được trừ trực tiếp từ tài khoản chủ xe, chỉ quản lý/admin được nhập.
    if current_user.is_manager_or_admin():
        standard_expenses.insert(1, ('toll_fee', 'Phí đường'))

    for category, label in standard_expenses:
        try:
            amount = Decimal((request.form.get(f'expense_{category}', '0') or '0').strip())
        except (InvalidOperation, AttributeError):
            raise ValueError(f'{label} phải là số hợp lệ.')
        if not amount.is_finite() or amount < 0:
            raise ValueError(f'{label} không được âm.')
        expense = PhoiExpense.query.filter_by(phoi_id=phoi.id, category=category).first()
        if amount > 0:
            if expense:
                expense.amount, expense.description = amount, label
            else:
                db.session.add(PhoiExpense(phoi_id=phoi.id, category=category, description=label, amount=amount))
        elif expense:
            db.session.delete(expense)


def _sync_repair_expenses(phoi):
    existing = {expense.id: expense for expense in PhoiExpense.query.filter_by(phoi_id=phoi.id, category='repair').all()}
    if request.form.get('has_repair') != '1':
        for expense in existing.values():
            db.session.delete(expense)
        return []

    ids = request.form.getlist('repair_id[]')
    descriptions = request.form.getlist('repair_description[]')
    amounts = request.form.getlist('repair_amount[]')
    home_indices = set(request.form.getlist('repair_home_index[]'))
    locations = request.form.getlist('repair_location[]')
    driver_paid_indices = set(request.form.getlist('repair_driver_paid_index[]'))
    repairs, kept_ids = [], set()

    for index in range(max(len(ids), len(descriptions), len(amounts), len(locations))):
        expense_id = ids[index].strip() if index < len(ids) else ''
        description = descriptions[index].strip() if index < len(descriptions) else ''
        raw_amount = amounts[index].strip() if index < len(amounts) else ''
        is_home = str(index) in home_indices
        location = locations[index].strip() if index < len(locations) else ''
        driver_paid = (not is_home) and (str(index) in driver_paid_indices)
        if not any([expense_id, description, raw_amount, is_home, location]):
            continue
        if not description or not raw_amount:
            raise ValueError(f'Hạng mục sửa xe #{index + 1} phải có nội dung và số tiền.')
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation as exc:
            raise ValueError(f'Số tiền sửa xe #{index + 1} phải là số hợp lệ.') from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError(f'Số tiền sửa xe #{index + 1} phải lớn hơn 0.')
        if not is_home and not location:
            raise ValueError(f'Hạng mục sửa xe #{index + 1} phải có nơi sửa/garage.')

        if expense_id:
            try:
                expense = existing[int(expense_id)]
            except (ValueError, KeyError) as exc:
                raise ValueError('Hạng mục sửa xe không hợp lệ.') from exc
            kept_ids.add(expense.id)
            expense.description, expense.amount = description, amount
            expense.is_home_repair, expense.repair_location = is_home, None if is_home else location
            expense.driver_paid = driver_paid
        else:
            expense = PhoiExpense(
                phoi_id=phoi.id, category='repair', description=description,
                amount=amount, is_home_repair=is_home,
                repair_location=None if is_home else location,
                driver_paid=driver_paid,
            )
            db.session.add(expense)
        repairs.append((index, expense))

    if not repairs:
        raise ValueError('Hãy thêm ít nhất một hạng mục khi đã chọn sửa xe.')
    for expense_id, expense in existing.items():
        if expense_id not in kept_ids:
            db.session.delete(expense)
    db.session.flush()
    return repairs


def _save_repair_receipts(phoi, repairs, saved_keys):
    for index, expense in repairs:
        files = [file for file in request.files.getlist(f'repair_receipts_{index}') if file and file.filename]
        if len(files) > 5:
            raise ValueError(f'Hạng mục sửa xe #{index + 1} chỉ được tải tối đa 5 ảnh hóa đơn.')
        existing_receipts = expense.attachments.filter_by(attachment_type='repair_receipt').count()
        if not expense.is_home_repair and not files and existing_receipts == 0:
            raise ValueError(f'Hạng mục sửa xe #{index + 1} sửa bên ngoài phải có ít nhất một ảnh hóa đơn.')
        for file in files:
            metadata = save_phoi_attachment(file, phoi.id)
            saved_keys.append(metadata['storage_key'])
            db.session.add(PhoiAttachment(
                phoi_id=phoi.id, expense_id=expense.id,
                attachment_type='repair_receipt', uploaded_by_id=current_user.id,
                **metadata,
            ))
