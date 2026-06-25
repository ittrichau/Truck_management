from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Customer

bp = Blueprint('customers', __name__)

@bp.route('/customers')
@login_required
def index():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))
    
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    return render_template('customers/index.html', customers=customers)

@bp.route('/customers/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))
    
    if request.method == 'POST':
        customer = Customer(
            name=request.form.get('name', '').strip(),
            cargo_type=request.form.get('cargo_type', '').strip(),
            default_origin=request.form.get('default_origin', '').strip(),
            default_destination=request.form.get('default_destination', '').strip(),
            contact_phone=request.form.get('contact_phone', '').strip(),
            notes=request.form.get('notes', '').strip(),
            created_by_id=current_user.id
        )
        db.session.add(customer)
        db.session.commit()
        flash(f'Đã thêm hàng: {customer.name}.', 'success')
        return redirect(url_for('customers.index'))
    
    return render_template('customers/create.html')

@bp.route('/customers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))
    
    customer = Customer.query.get_or_404(id)
    
    if request.method == 'POST':
        customer.name = request.form.get('name', '').strip()
        customer.cargo_type = request.form.get('cargo_type', '').strip()
        customer.default_origin = request.form.get('default_origin', '').strip()
        customer.default_destination = request.form.get('default_destination', '').strip()
        customer.contact_phone = request.form.get('contact_phone', '').strip()
        customer.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash(f'Đã cập nhật hàng: {customer.name}.', 'success')
        return redirect(url_for('customers.index'))
    
    return render_template('customers/edit.html', customer=customer)

@bp.route('/customers/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))
    
    customer = Customer.query.get_or_404(id)
    customer.is_active = False
    db.session.commit()
    flash(f'Đã xóa hàng: {customer.name}.', 'success')
    return redirect(url_for('customers.index'))

# API endpoint for AJAX/dynamic selection
@bp.route('/api/customers')
@login_required
def api_customers():
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()
    data = []
    for c in customers:
        data.append({
            'id': c.id,
            'name': c.name,
            'cargo_type': c.cargo_type,
            'default_origin': c.default_origin,
            'default_destination': c.default_destination
        })
    return jsonify(data)

@bp.route('/api/customers/<int:id>')
@login_required
def api_customer_detail(id):
    customer = Customer.query.get_or_404(id)
    return jsonify({
        'id': customer.id,
        'name': customer.name,
        'cargo_type': customer.cargo_type,
        'default_origin': customer.default_origin,
        'default_destination': customer.default_destination
    })
