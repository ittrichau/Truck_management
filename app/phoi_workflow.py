"""Business rules for the phơi lifecycle."""
from app.models import Phoi


def can_manage_phoi(user, phoi):
    """Managers/admins may assist; a driver may manage only their own phơi."""
    return user.is_manager_or_admin() or (user.is_driver() and phoi.driver_id == user.id)


def submission_error(phoi):
    """Return the first unmet completion requirement, or None when ready."""
    if phoi.return_trips.count() == 0:
        return 'Phơi chưa có chuyến về. Vui lòng thêm ít nhất một chuyến về trước khi chốt.'
    if phoi.fuel_logs.count() == 0:
        return 'Phơi chưa được gắn lần đổ xăng nào. Vui lòng ghi nhận đổ xăng trước khi chốt.'
    return None


def update_truck_status(truck):
    """A truck is available only when it has no active phơi."""
    if not truck:
        return
    active_phoi_exists = Phoi.query.filter(
        Phoi.truck_id == truck.id,
        Phoi.status.in_(['draft', 'submitted'])
    ).count() > 0
    truck.status = 'in_trip' if active_phoi_exists else 'available'
