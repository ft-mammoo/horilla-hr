"""
An earning paid outside the salary structure (a bonus, a one-time allowance) sits on top of a CTC Down
package: it does not shrink the balance component, and a full pay month pays its fixed amount in full.
"""

from datetime import date

from payroll.methods.earning_working import earning_workings
from payroll.methods.proration import MONTH_CALENDAR_DAYS, period_factor
from payroll.models.models import Allowance, Contract, Payslip
from payroll.tests.test_contract_structure_types import StructureTypeFixture, day


def month(start, end, days):
    return {"start_date": start, "end_date": end, "days": days}


class FullPayMonthFactor(StructureTypeFixture):
    def test_a_pay_month_crossing_a_calendar_month_is_one_whole_month(self):
        slices = [
            month("2026-09-29", "2026-09-30", 30),
            month("2026-10-01", "2026-10-28", 31),
        ]
        self.assertEqual(period_factor(slices, MONTH_CALENDAR_DAYS), 1.0)

    def test_a_part_of_a_pay_month_is_still_shared_by_calendar_days(self):
        slices = [
            month("2026-09-29", "2026-09-30", 30),
            month("2026-10-01", "2026-10-13", 31),
        ]
        self.assertAlmostEqual(
            period_factor(slices, MONTH_CALENDAR_DAYS), 2 / 30 + 13 / 31
        )

    def test_a_calendar_month_is_unchanged(self):
        self.assertEqual(
            period_factor([month("2026-04-01", "2026-04-30", 30)], MONTH_CALENDAR_DAYS),
            1.0,
        )


class OutsideTheStructure(StructureTypeFixture):
    def pay(self, with_bonus):
        structure = self.ctc_structure("C1", 50.0, 400.0)
        kw = dict(
            employee_id=self.employee,
            wage_type="monthly",
            wage=60000.0,
            contract_status="active",
            deduct_leave_from_basic_pay=True,
            calculate_daily_leave_amount=True,
            deduction_for_one_leave_amount=0,
            salary_structure_id=structure,
        )
        Contract.objects.create(contract_name="Main", contract_start_date=day(1), **kw)
        if with_bonus:
            bonus = Allowance.objects.create(
                title="Xmas", is_fixed=True, amount=5000.0, is_taxable=True
            )
            bonus.specific_employees.add(self.employee)
        (payslip,) = self.run_month()
        return payslip

    def rows(self, payslip):
        return {row["title"]: row for row in payslip.pay_head_data["allowances"]}

    def test_the_balance_is_the_same_with_or_without_the_bonus(self):
        plain = self.pay(with_bonus=False)
        Payslip.objects.all().delete()
        Contract.objects.all().delete()
        with_bonus = self.pay(with_bonus=True)
        self.assertAlmostEqual(
            self.rows(with_bonus)["C1 Special"]["amount"],
            self.rows(plain)["C1 Special"]["amount"],
            places=2,
        )

    def test_the_bonus_is_paid_in_full_on_top_of_the_package(self):
        payslip = self.pay(with_bonus=True)
        self.assertAlmostEqual(self.rows(payslip)["Xmas"]["amount"], 5000.0, places=2)
        self.assertTrue(self.rows(payslip)["Xmas"]["outside_ctc"])
        self.assertAlmostEqual(payslip.gross_pay, 60000.0 + 5000.0, places=2)

    def test_structure_components_are_not_marked_outside(self):
        payslip = self.pay(with_bonus=True)
        self.assertFalse(self.rows(payslip)["C1 HRA"]["outside_ctc"])

    def test_the_payslip_says_so(self):
        payslip = self.pay(with_bonus=True)
        working = earning_workings(payslip)[
            f"a:{self.rows(payslip)['Xmas']['allowance_id']}"
        ]
        self.assertIn("Outside The Salary Structure", " ".join(working["notes"]))
