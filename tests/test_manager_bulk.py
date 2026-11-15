"""Save the actual page's successful HTML controls as one atomic batch."""
from html.parser import HTMLParser
import json
import unittest

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import MultiDict

import test_manager_scopes as fixtures
from app import db
from app.models import ActivityLog


class PageForm(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = MultiDict()
        self.forms = 0
        self.select = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form': self.forms += 1
        if tag == 'input' and attrs.get('name') and 'disabled' not in attrs:
            if attrs.get('type') != 'checkbox' or 'checked' in attrs:
                self.fields.add(attrs['name'], attrs.get('value', ''))
        if tag == 'select':
            self.select = {'name': attrs.get('name'), 'disabled': 'disabled' in attrs, 'options': []}
        if tag == 'option' and self.select is not None:
            self.select['options'].append((attrs.get('value', ''), 'selected' in attrs))

    def handle_endtag(self, tag):
        if tag == 'select' and self.select is not None:
            field = self.select
            if field['name'] and not field['disabled'] and field['options']:
                selected = next((value for value, checked in field['options'] if checked), field['options'][0][0])
                self.fields.add(field['name'], selected)
            self.select = None


class BulkAssignmentTests(unittest.TestCase):
    setUp = fixtures.ManagerScopeTests.setUp
    tearDown = fixtures.ManagerScopeTests.tearDown
    user = fixtures.ManagerScopeTests.user
    phoi = fixtures.ManagerScopeTests.phoi
    fuel = fixtures.ManagerScopeTests.fuel
    login = fixtures.ManagerScopeTests.login
    image_metadata = staticmethod(fixtures.ManagerScopeTests.image_metadata)

    def page(self):
        self.login(self.admin)
        response = self.client.get('/admin/management')
        self.assertEqual(response.status_code, 200)
        return PageForm(response.get_data(as_text=True))

    def save(self, form):
        return self.client.post('/admin/management', data=form.fields)

    def audits(self):
        return ActivityLog.query.filter_by(resource_type='manager_assignments').all()

    def test_one_form_and_one_save_button_covers_all_resource_types(self):
        page = self.page()
        self.assertEqual(page.forms, 1)
        self.assertEqual(page.fields['action'], 'save_all')
        self.assertIn(f'truck:{self.ta.id}', page.fields.getlist('rows'))
        self.assertIn(f'driver:{self.da.id}', page.fields.getlist('rows'))
        self.assertIn(f'customer:{self.ca.id}', page.fields.getlist('rows'))
        self.assertNotIn(f'manager_driver_{self.da.id}', page.fields) # follows truck
        self.assertIn(f'expected_driver_{self.da.id}', page.fields)

    def test_save_all_updates_trucks_unlinked_driver_and_shared_customer(self):
        driver = self.user('unlinked', 'driver', self.a.id); db.session.commit()
        page = self.page()
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        page.fields[f'manager_truck_{self.legacy.id}'] = str(self.a.id)
        page.fields[f'manager_driver_{driver.id}'] = str(self.b.id)
        page.fields.setlist(f'managers_customer_{self.ca.id}', [str(self.a.id), str(self.b.id)])
        self.assertEqual(self.save(page).status_code, 302)
        self.assertEqual((self.ta.manager_id, self.da.manager_id), (self.b.id, self.b.id))
        self.assertEqual(self.da.current_truck_id, self.ta.id)
        self.assertEqual((self.legacy.manager_id, driver.manager_id), (self.a.id, self.b.id))
        self.assertEqual({m.id for m in self.ca.managers}, {self.a.id, self.b.id})
        self.assertEqual(len(self.audits()), 4)

    def test_no_changes_do_not_write_assignment_audits(self):
        page = self.page()
        self.assertEqual(self.save(page).status_code, 302)
        self.assertEqual(self.audits(), [])

    def test_clearing_customer_checkboxes_revokes_all_grants(self):
        page = self.page()
        page.fields.poplist(f'managers_customer_{self.shared.id}')
        self.assertEqual(self.save(page).status_code, 302)
        self.assertEqual(self.shared.managers, [])

    def test_invalid_customer_rolls_back_all_and_retains_edits(self):
        page = self.page()
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        page.fields.setlist(f'managers_customer_{self.ca.id}', ['999999'])
        response = self.save(page)
        self.assertEqual(response.status_code, 400)
        self.assertEqual((self.ta.manager_id, self.da.manager_id), (self.a.id, self.a.id))
        self.assertEqual(self.audits(), [])
        restored = PageForm(response.get_data(as_text=True))
        self.assertEqual(restored.fields[f'manager_truck_{self.ta.id}'], str(self.b.id))
        self.assertEqual(restored.fields[f'expected_truck_{self.ta.id}'], str(self.a.id))

    def test_late_linked_driver_conflict_rolls_back_truck_transfer_and_audit(self):
        page = self.page()
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        # Explicitly move B's driver to A while B's truck remains owned by B.
        page.fields[f'manager_driver_{self.db.id}'] = str(self.a.id)
        self.assertEqual(self.save(page).status_code, 400)
        self.assertEqual((self.ta.manager_id, self.da.manager_id), (self.a.id, self.a.id))
        self.assertEqual(self.db.manager_id, self.b.id)
        self.assertEqual(self.audits(), [])

    def test_explicit_driver_edit_matching_truck_transfer_is_not_stale(self):
        page = self.page()
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        page.fields[f'manager_driver_{self.da.id}'] = str(self.b.id)
        self.assertEqual(self.save(page).status_code, 302)
        self.assertEqual(self.da.manager_id, self.b.id)
        self.assertEqual(len(self.audits()), 1)

    def test_stale_edited_row_stops_whole_batch_and_keeps_original_expected(self):
        page = self.page()
        self.legacy.manager_id = self.a.id; db.session.commit()
        page.fields[f'manager_truck_{self.legacy.id}'] = str(self.b.id)
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        response = self.save(page)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.ta.manager_id, self.a.id)
        self.assertEqual(self.legacy.manager_id, self.a.id)
        restored = PageForm(response.get_data(as_text=True))
        self.assertEqual(restored.fields[f'expected_truck_{self.legacy.id}'], '')
        self.assertEqual(restored.fields[f'manager_truck_{self.legacy.id}'], str(self.b.id))

    def test_unchanged_stale_row_does_not_overwrite_another_admin(self):
        page = self.page()
        self.legacy.manager_id = self.b.id; db.session.commit()
        page.fields.setlist(f'managers_customer_{self.ca.id}', [str(self.b.id)])
        self.assertEqual(self.save(page).status_code, 302)
        self.assertEqual(self.legacy.manager_id, self.b.id)
        self.assertEqual([m.id for m in self.ca.managers], [self.b.id])

    def test_duplicate_malformed_missing_or_nonexistent_rows_cannot_partially_save(self):
        for invalid in ('duplicate', 'malformed', 'missing', 'nonexistent'):
            with self.subTest(invalid=invalid):
                page = self.page()
                page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
                if invalid == 'duplicate': page.fields.add('rows', f'truck:{self.ta.id}')
                elif invalid == 'malformed': page.fields.add('rows', 'admin:1')
                elif invalid == 'missing': page.fields.pop(f'expected_truck_{self.ta.id}')
                else:
                    page.fields.add('rows', 'truck:999999')
                    page.fields['expected_truck_999999'] = ''
                    page.fields['manager_truck_999999'] = str(self.a.id)
                self.assertEqual(self.save(page).status_code, 400)
                self.assertEqual(self.ta.manager_id, self.a.id)
                self.assertEqual(self.audits(), [])

    def test_bulk_is_admin_only_and_csrf_protected(self):
        page = self.page()
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        self.login(self.a)
        self.assertEqual(self.save(page).status_code, 403)
        self.login(self.da)
        self.assertEqual(self.save(page).status_code, 403)
        self.login(self.admin)
        self.app.config['WTF_CSRF_ENABLED'] = True
        page.fields['csrf_token'] = ''
        self.assertEqual(self.save(page).status_code, 400)
        self.assertEqual(self.ta.manager_id, self.a.id)

    def test_audit_failure_rolls_back_entire_batch_and_keeps_edits(self):
        page = self.page()
        page.fields[f'manager_truck_{self.ta.id}'] = str(self.b.id)
        page.fields.setlist(f'managers_customer_{self.ca.id}', [str(self.b.id)])
        def fail(mapper, connection, target):
            if target.resource_type == 'manager_assignments': raise SQLAlchemyError('audit failed')
        event.listen(ActivityLog, 'before_insert', fail)
        try: response = self.save(page)
        finally: event.remove(ActivityLog, 'before_insert', fail)
        self.assertEqual(response.status_code, 409)
        db.session.expire_all()
        self.assertEqual((self.ta.manager_id, self.da.manager_id), (self.a.id, self.a.id))
        self.assertEqual([m.id for m in self.ca.managers], [self.a.id])
        self.assertEqual(self.audits(), [])
        restored = PageForm(response.get_data(as_text=True))
        self.assertEqual(restored.fields[f'manager_truck_{self.ta.id}'], str(self.b.id))
        self.assertEqual(restored.fields.getlist(f'managers_customer_{self.ca.id}'), [str(self.b.id)])


if __name__ == '__main__': unittest.main()
