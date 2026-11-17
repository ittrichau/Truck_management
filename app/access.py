"""Explicit, fail-closed resource scopes shared by routes and business services."""
from flask import abort
from flask_login import current_user
from sqlalchemy import or_, select

from app.models import Customer, FuelLog, Phoi, PhoiReturnTrip, Truck, User


def actor_or_current(actor=None):
    return current_user if actor is None else actor


def manager_id(actor=None):
    actor = actor_or_current(actor)
    if not actor.is_authenticated or not actor.is_active:
        return None
    if actor.role == 'manager':
        return actor.id
    if actor.is_driver() and actor.manager_id:
        manager = actor.manager
        if manager and manager.role == 'manager' and manager.is_active:
            return manager.id
    return None


def truck_ids(actor=None):
    owner = manager_id(actor)
    return select(Truck.id).where(Truck.manager_id == owner) if owner else select(Truck.id).where(False)


def trucks_query(actor=None):
    actor = actor_or_current(actor)
    return Truck.query if actor.is_admin() else Truck.query.filter(Truck.id.in_(truck_ids(actor)))


def drivers_query(actor=None):
    actor = actor_or_current(actor)
    query = User.query.filter_by(role='driver')
    owner = manager_id(actor)
    return query if actor.is_admin() else query.filter(User.manager_id == owner if owner else False)


def phois_query(actor=None):
    actor = actor_or_current(actor)
    if actor.is_admin():
        return Phoi.query
    if actor.is_driver():
        return Phoi.query.filter_by(driver_id=actor.id)
    return Phoi.query.filter(Phoi.truck_id.in_(truck_ids(actor)))


def fuel_query(actor=None):
    actor = actor_or_current(actor)
    if actor.is_admin():
        return FuelLog.query
    if actor.is_driver():
        return FuelLog.query.filter_by(created_by_id=actor.id).filter(
            ~FuelLog.phois.any(Phoi.driver_id != actor.id)
        )
    # Legacy malformed cross-truck links must not expose another manager's phơi.
    return FuelLog.query.filter(FuelLog.truck_id.in_(truck_ids(actor))).filter(
        ~FuelLog.phois.any(~Phoi.truck_id.in_(truck_ids(actor))),
        ~FuelLog.unallocated_from_cancelled_phoi.has(~Phoi.truck_id.in_(truck_ids(actor))),
    )


def customers_query(actor=None, include_history=False):
    actor = actor_or_current(actor)
    if actor.is_admin():
        return Customer.query
    owner = manager_id(actor)
    assigned = Customer.managers.any(User.id == owner) if owner else False
    if include_history:
        owned_phois = phois_query(actor).with_entities(Phoi.id)
        assigned = or_(assigned,
            Customer.id.in_(select(Phoi.customer_id).where(Phoi.id.in_(owned_phois))),
            Customer.id.in_(select(PhoiReturnTrip.customer_id).where(PhoiReturnTrip.phoi_id.in_(owned_phois))))
    return Customer.query.filter(assigned)


def can_access_phoi(actor, phoi):
    return actor.is_admin() or (
        actor.is_driver() and phoi.driver_id == actor.id
    ) or (
        actor.role == 'manager' and manager_id(actor) == phoi.truck.manager_id
    )


def permitted_customer_id(value, existing_id=None):
    if not value:
        return None
    try:
        identity = int(value)
    except (ValueError, TypeError):
        raise ValueError('Khách hàng không hợp lệ.') from None
    # Historical customers can remain on their own trip after a transfer/revocation.
    if identity == existing_id:
        return identity
    if not customers_query().filter_by(id=identity, is_active=True).first():
        raise ValueError('Khách hàng không thuộc phạm vi được giao.')
    return identity


def require_driver_truck(driver, truck):
    """A default assignment may never cross ownership, including admin forms."""
    if driver.manager_id != truck.manager_id:
        abort(400, description='Tài xế và xe phải thuộc cùng một quản lý. Hãy phân quyền trước.')


def has_assignments(user):
    return bool(Truck.query.filter_by(manager_id=user.id).first()
                or User.query.filter_by(manager_id=user.id).first()
                or Customer.query.filter(Customer.managers.any(User.id == user.id)).first())


def edit_customers_query(phoi):
    """Keep a transferred trip's original selections without granting its catalog."""
    historical_ids = {phoi.customer_id} | {trip.customer_id for trip in phoi.return_trips.all()}
    historical_ids.discard(None)
    available = customers_query().filter_by(is_active=True).with_entities(Customer.id)
    return Customer.query.filter(or_(Customer.id.in_(available), Customer.id.in_(historical_ids)))
