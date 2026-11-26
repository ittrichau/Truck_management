"""Read-only schedule projection: previews, filters, spacing and calendar bars."""
from collections import defaultdict
from datetime import timedelta

from app.trip_planning import actual_from_phoi, parse_day, unique_candidate


def live_data(session, plan):
    if plan.phoi:
        return actual_from_phoi(plan.phoi), plan.phoi
    candidate = unique_candidate(session, plan) if not plan.is_cancelled else None
    return (actual_from_phoi(candidate), candidate) if candidate else (None, None)


def overlaps(data, start, end):
    departed = parse_day(data.get('departure_date'), 'Ngày đi')
    returned = parse_day(data.get('return_date'), 'Ngày về')
    return departed and departed <= end and (returned is None or returned >= start)


def matches(data, filters):
    for field in ('truck_id', 'driver_id'):
        if filters[field] and data.get(field) != filters[field]:
            return False
    if filters['customer_id'] and filters['customer_id'] not in (
        [data.get('customer_id')] + [row.get('customer_id') for row in data.get('return_trips', [])]
    ):
        return False
    return not filters['q'] or filters['q'].casefold() in ' '.join(str(value) for value in data.values()).casefold()


class ScheduleView:
    def __init__(self, session):
        self.session = session
        self.cache = {}

    def data(self, plan):
        if plan.id not in self.cache:
            self.cache[plan.id] = live_data(self.session, plan)
        return self.cache[plan.id]

    def rows(self, plans, all_plans, start, end, filters):
        rows = []
        for plan in plans:
            planned = plan.planned_data(self.session)
            actual, phoi = self.data(plan)
            status, label = plan.status(self.session, actual, bool(phoi and phoi.status == 'draft'))
            if filters['status'] and status != filters['status']:
                continue
            if not matches(planned, filters) and not (actual and matches(actual, filters)):
                continue
            if not overlaps(planned, start, end) and not (actual and overlaps(actual, start, end)):
                continue
            rows.append(dict(plan=plan, planned=planned, actual=actual, phoi=phoi, status=status, label=label,
                             differences=plan.differences(self.session, actual), gap=None, warnings=[]))

        trucks, drivers = defaultdict(list), defaultdict(list)
        for plan in all_plans:
            actual, _ = self.data(plan)
            data = actual if actual and not actual.get('cancelled') else plan.planned_data(self.session)
            item = (plan.id, data)
            trucks[data['truck_id']].append(item)
            if data.get('driver_id'):
                drivers[data['driver_id']].append(item)
        by_id = {row['plan'].id: row for row in rows}
        for kind, groups in (('Xe', trucks), ('Tài xế', drivers)):
            for group in groups.values():
                group.sort(key=lambda item: (item[1]['departure_date'], item[0]))
                for index, (identity, data) in enumerate(group):
                    if identity not in by_id:
                        continue
                    row = by_id[identity]
                    if kind == 'Xe' and index + 1 < len(group) and data.get('return_date'):
                        row['gap'] = (parse_day(group[index + 1][1]['departure_date'], 'Ngày đi')
                                      - parse_day(data['return_date'], 'Ngày về')).days
                    if not data.get('return_date'):
                        continue
                    for other_id, other in group:
                        if other_id == identity or not other.get('return_date'):
                            continue
                        if data['departure_date'] < other['return_date'] and other['departure_date'] < data['return_date']:
                            warning = f'{kind} chồng lịch với kế hoạch #{other_id}'
                            if kind == 'Xe' or not any(w.endswith(f'#{other_id}') for w in row['warnings']):
                                row['warnings'].append(warning)
        return rows


def calendar_data(rows, start, end):
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    for row in rows:
        row['bars'] = []
        for key, label in (('planned', 'Kế hoạch'), ('actual', 'Thực tế')):
            data = row[key]
            if not data or not overlaps(data, start, end):
                continue
            first = max(start, parse_day(data['departure_date'], 'Ngày đi'))
            returned = parse_day(data.get('return_date'), 'Ngày về')
            last = min(end, returned or end)
            if last < first:
                continue
            row['bars'].append(dict(kind=key, label=label, start=(first-start).days + 1,
                                    end=(last-start).days + 2, unknown=returned is None))
    return days
