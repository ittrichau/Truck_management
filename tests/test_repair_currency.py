"""Regression coverage for Decimal repair amounts through the edit form.

Run with: python -m unittest discover -s tests
Requires the app's Jinja2 dependency and Node.js for the actual JS formatter.
"""
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import unittest

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]


class Query:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return self.rows

    def count(self):
        return len(self.rows)


class RepairCurrencyTest(unittest.TestCase):
    def test_edit_and_resubmit_preserves_repair_amounts(self):
        template = Environment(
            loader=FileSystemLoader(ROOT / 'app/templates')
        ).get_template('phoi/_repair_expenses.html')
        javascript = (ROOT / 'app/static/js/app.js').read_text()
        # Execute the production formatter and submission normalizer in Node.
        formatter = javascript[
            javascript.index('function currencyDigits('):
            javascript.index('function prepareCurrencyInput(')
        ]
        cases = []
        for initial in ('350000.00', '35000000.00', '575000.00', '9999999999.00'):
            for home, driver_paid in ((True, False), (False, False), (False, True)):
                amount = Decimal(initial)
                for cycle in range(3):
                    expense = SimpleNamespace(
                        id=1, description='Repair', amount=amount,
                        is_home_repair=home, repair_location='Garage',
                        driver_paid=driver_paid, attachments=Query([]),
                    )
                    rendered = template.render(phoi=SimpleNamespace(expenses=Query([expense])))
                    value = re.search(r"amount: '([^']*)'", rendered).group(1)
                    cases.append((initial, home, driver_paid, cycle, value))
                    # Model the next database read as Numeric(12, 2).
                    amount = Decimal(value.replace(',', '')).quantize(Decimal('0.01'))

        script = formatter + '''
const cases = JSON.parse(process.argv[1]);
const result = cases.map(value => {
    const input = {value};
    formatCurrencyInput(input); // DOMContentLoaded
    formatCurrencyInput(input); // focusin
    return currencyDigits(input.value); // submit
});
process.stdout.write(JSON.stringify(result));
'''
        output = subprocess.check_output(
            ['node', '-e', script, json.dumps([case[-1] for case in cases])], text=True
        )
        for case, submitted in zip(cases, json.loads(output), strict=True):
            with self.subTest(case=case):
                self.assertEqual(Decimal(submitted), Decimal(case[0]))


if __name__ == '__main__':
    unittest.main()
