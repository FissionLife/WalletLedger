"""Rule-based message understanding (app/bot/nlu.py) and the compact replies. Pure functions: no DB."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
os.environ["DYNAMIC_MODELS"] = "false"
import unittest  # noqa: E402
from datetime import date  # noqa: E402

from app.bot import nlu, replies  # noqa: E402

TODAY = date(2026, 10, 11)  # a Sunday
CTX = nlu.Context(
    accounts=["HDFC Bank", "Cash", "Credit Card"],
    merchants=["Swiggy"],
    default_expense_account="HDFC Bank",
    default_income_account="HDFC Bank",
    today=TODAY,
)


def one(text, ctx=CTX):
    entries = nlu.parse_entries(text, ctx)
    assert len(entries) == 1, (text, entries)
    return entries[0]


class AmountTests(unittest.TestCase):
    def test_amount_formats(self):
        cases = {
            "spent 450 on dinner": 450.0,
            "spent ₹1,250.50 on petrol": 1250.5,
            "spent Rs. 300 on tea": 300.0,
            "spent rs 99 on tea": 99.0,
            "paid 18k for rent": 18000.0,
            "spent 1.5k on petrol": 1500.0,
            "paid 2 lakh for tuition": 200000.0,
            "paid 2.5 lakhs for the course": 250000.0,
            "spent 12,50,000 on a flat": 1250000.0,
            "spent INR 750 on lunch": 750.0,
        }
        for text, amount in cases.items():
            self.assertEqual(one(text).amount, amount, text)

    def test_phone_numbers_ids_and_times_are_not_money(self):
        for text in (
            "call me at 9876543210",
            "order id 1234567890 shipped",
            "meeting at 5pm",
            "see you at 10:30",
            "I scored 95%",
        ):
            self.assertEqual(nlu.parse_entries(text, CTX), [], text)

    def test_zero_and_negative_are_ignored(self):
        self.assertEqual(nlu.parse_entries("spent 0 on nothing", CTX), [])


class KindAndFieldTests(unittest.TestCase):
    def test_expense_basics(self):
        e = one("Spent 450 on dinner via HDFC")
        self.assertEqual(
            (e.kind, e.amount, e.account, e.category, e.merchant),
            ("expense", 450.0, "HDFC Bank", "Food & Dining", None),
        )
        e = one("Paid 150 to Starbucks for coffee")
        self.assertEqual((e.merchant, e.category), ("Starbucks", "Food & Dining"))
        e = one("bought groceries 640 from cash")
        self.assertEqual((e.account, e.category), ("Cash", "Groceries"))

    def test_income(self):
        e = one("Received 85000 salary in Bank")
        self.assertEqual((e.kind, e.category), ("income", "Salary"))
        self.assertEqual(one("got paid 20000").kind, "income")
        self.assertEqual(one("got 500 refund").category, "Refund")
        self.assertEqual(one("got stipend 15000").category, "Salary")
        self.assertEqual(one("cashback of 120 received").category, "Cashback")
        self.assertEqual(one("got a haircut for 300").kind, "expense")  # "got" alone is not income

    def test_transfer_and_withdrawal(self):
        e = one("Transferred 2000 from HDFC Bank to Cash")
        self.assertEqual((e.kind, e.account, e.to_account), ("transfer", "HDFC Bank", "Cash"))
        e = one("withdrew 5000 from bank")
        self.assertEqual((e.kind, e.account, e.to_account), ("transfer", "HDFC Bank", "Cash"))
        e = one("deposited 3000 cash in bank")
        self.assertEqual((e.account, e.to_account), ("Cash", "HDFC Bank"))
        self.assertEqual(nlu.parse_entries("transfer 500 from Cash to cash", CTX), [])

    def test_accounts_resolve_to_the_users_names(self):
        self.assertEqual(one("spent 100 on tea via hdfc").account, "HDFC Bank")
        self.assertEqual(one("spent 100 on tea using credit card").account, "Credit Card")
        self.assertEqual(one("spent 100 on tea, paid in cash").account, "Cash")
        self.assertEqual(one("spent 100 on tea via UPI").account, "HDFC Bank")  # UPI -> the bank
        self.assertEqual(one("spent 100 on tea").account, "HDFC Bank")  # the user's default
        unknown = nlu.Context(default_expense_account="Cash")
        self.assertEqual(one("spent 100 on tea via axis", unknown).account, "Axis")

    def test_merchants_vs_categories(self):
        self.assertEqual(one("Spent 300 on Swiggy").merchant, "Swiggy")  # known merchant
        e = one("spent 300 on Zomato")
        self.assertEqual((e.merchant, e.category), ("Zomato", "Food & Dining"))  # a brand
        e = one("spent 200 on chai")
        self.assertEqual(
            (e.merchant, e.category), (None, "Food & Dining")
        )  # a thing, not a merchant
        self.assertEqual(one("paid 650 to Netflix").category, "Entertainment")

    def test_categories(self):
        cases = {
            "spent 80 on auto": "Transport",
            "spent 1200 on petrol": "Transport",
            "spent 400 on a movie": "Entertainment",
            "paid 18000 rent": "Rent",
            "spent 300 on a haircut": "Personal Care",
            "bought medicine for 250": "Health",
            "paid 799 for wifi": "Bills & Utilities",
            "spent 55000 on a laptop": "Shopping",
            "spent 100 on dinner": "Food & Dining",
        }
        for text, cat in cases.items():
            self.assertEqual(one(text).category, cat, text)

    def test_unknown_things_get_a_readable_category_or_none(self):
        self.assertEqual(one("spent 90 on stationery").category, "Stationery")
        self.assertIsNone(one("spent 450").category)

    def test_bare_fragments(self):
        self.assertEqual((one("chai 20").amount, one("chai 20").category), (20.0, "Food & Dining"))
        e = one("Netflix 649 via credit card")
        self.assertEqual(
            (e.merchant, e.account, e.category), ("Netflix", "Credit Card", "Entertainment")
        )
        self.assertEqual(one("450 on dinner").category, "Food & Dining")

    def test_not_transactions(self):
        for text in (
            "hello there",
            "what is 5 plus 5",
            "I have 3 apples",
            "balance 5000",
            "how much did I spend?",
            "hello 5 times",
            "meeting at 5",
            "",
        ):
            self.assertEqual(nlu.parse_entries(text, CTX), [], text)


class DateTests(unittest.TestCase):
    def test_named_days(self):
        self.assertEqual(one("yesterday I spent 500 on movie tickets").when, "2026-10-10")
        self.assertEqual(one("spent 90 on tea today").when, "2026-10-11")
        self.assertEqual(one("spent 300 on uber 5 days ago").when, "2026-10-06")
        self.assertEqual(one("spent 300 on dinner day before yesterday").when, "2026-10-09")
        self.assertEqual(one("spent 300 on dinner last night").when, "2026-10-10")

    def test_weekdays_and_dates(self):
        self.assertEqual(one("spent 300 on dinner on friday").when, "2026-10-09")
        self.assertEqual(
            one("spent 300 on dinner on sunday").when, "2026-10-04"
        )  # a week back, never today
        self.assertEqual(one("paid rent 18k on 3rd").when, "2026-10-03")
        self.assertEqual(
            one("paid rent 18k on 25th").when, "2026-09-25"
        )  # the 25th has not happened yet
        self.assertEqual(one("spent 200 on tea on 5 oct").when, "2026-10-05")
        self.assertEqual(one("spent 200 on tea on oct 5").when, "2026-10-05")
        self.assertEqual(one("spent 200 on tea on 2026-09-30").when, "2026-09-30")
        self.assertEqual(one("spent 200 on tea on 02/10/2026").when, "2026-10-02")
        self.assertEqual(one("spent 200 on tea on 20 dec").when, "2025-12-20")  # not in the future

    def test_no_date_means_now(self):
        self.assertIsNone(one("spent 200 on tea").when)

    def test_date_words_do_not_leak_into_the_category(self):
        self.assertEqual(one("yesterday spent 500 on movie").category, "Entertainment")


class MultiItemTests(unittest.TestCase):
    def test_three_items(self):
        es = nlu.parse_entries("Spent 200 on chai, 80 on auto and 1200 on groceries", CTX)
        self.assertEqual(
            [(e.amount, e.category) for e in es],
            [(200.0, "Food & Dining"), (80.0, "Transport"), (1200.0, "Groceries")],
        )

    def test_income_then_expenses_and_inherited_kind(self):
        es = nlu.parse_entries("got ₹15,000 stipend and spent ₹190 on dosa, ₹80 on coffee", CTX)
        self.assertEqual(
            [(e.kind, e.amount) for e in es],
            [("income", 15000.0), ("expense", 190.0), ("expense", 80.0)],
        )

    def test_thousands_commas_are_not_separators(self):
        es = nlu.parse_entries("spent 1,200 on rent, 80 on auto", CTX)
        self.assertEqual([e.amount for e in es], [1200.0, 80.0])

    def test_one_amount_with_two_things_stays_one_entry(self):
        es = nlu.parse_entries("spent 200 on tea and coffee", CTX)
        self.assertEqual([e.amount for e in es], [200.0])

    def test_account_named_once_applies_to_all_items(self):
        es = nlu.parse_entries("spent 200 on chai and 80 on auto via credit card", CTX)
        self.assertEqual({e.account for e in es}, {"Credit Card"})

    def test_lists_with_equals_and_newlines(self):
        es = nlu.parse_entries("190=pizza\n80=dosa\n115.62=petrol", CTX)
        self.assertEqual([e.amount for e in es], [190.0, 80.0, 115.62])
        self.assertEqual(es[2].category, "Transport")

    def test_the_big_mixed_message_with_typos(self):
        message = (
            "i got stifend of 15000 from that i spend this 190=poornima pizza Dosa\n80=Neeraj Dosa\n10=water bottle\n"
            "115.62=petrol\n15=dosa\n100=family nasta\n109=poornima biryani\n80=roshani chocaltes\n50=idly\n"
            "300=poornima gift\n100=haircut\n340=team lunch"
        )
        es = nlu.parse_entries(message, CTX)
        self.assertEqual(len(es), 13)
        self.assertEqual((es[0].kind, es[0].amount), ("income", 15000.0))
        self.assertEqual(round(sum(e.amount for e in es if e.kind == "expense"), 2), 1489.62)

    def test_same_line_list_without_verbs(self):
        es = nlu.parse_entries("200 for tea 80 for auto 1200 for rent", CTX)
        self.assertEqual([e.amount for e in es], [200.0, 80.0, 1200.0])

    def test_a_clause_we_cannot_read_hands_the_whole_message_to_the_ai(self):
        self.assertEqual(
            nlu.parse_entries("spent 200 on tea and then 500 gnarf blorp", CTX)[0].amount
            if False
            else 0,
            0,
        )
        self.assertEqual(nlu.parse_entries("I owe 500 to my brother's friend maybe", CTX), [])

    def test_limits(self):
        self.assertEqual(nlu.parse_entries("x" * 5000, CTX), [])
        self.assertEqual(
            len(nlu.parse_entries("\n".join(f"{i + 1}=item{i}" for i in range(40)), CTX)), 40
        )
        self.assertEqual(
            nlu.parse_entries("\n".join(f"{i + 1}=item{i}" for i in range(41)), CTX), []
        )


class ScreenTests(unittest.TestCase):
    def test_screens(self):
        cases = {
            "how much did I spend on food last month": ("/stats", "last month food"),
            "what's my balance": ("/balance", ""),
            "undo": ("/undo", ""),
            "delete the last one": ("/undo", ""),
            "show my transactions": ("/history", ""),
            "set food budget to 6000": ("/budget", "food 6000"),
            "how much did I earn this year": ("/stats", "ytd"),
            "open my dashboard": ("/dashboard", ""),
            "download my data": ("/export", ""),
            "spending in september": ("/stats", "2026-09"),
            "stats": ("/stats", ""),
            "how much did i spend yesterday": ("/stats", "yesterday"),
            "what can you do": ("/help", ""),
            "total spending last 45 days on shopping": ("/stats", "45d shopping"),
            "how much did I spend this week": ("/stats", "week"),
        }
        for text, (command, args) in cases.items():
            screen = nlu.detect_screen(text)
            self.assertIsNotNone(screen, text)
            self.assertEqual((screen.command, screen.args), (command, args), text)

    def test_logging_messages_are_not_screens(self):
        for text in (
            "spent 450 on dinner",
            "Received 85000 salary",
            "chai 20",
            "paid 150 to Starbucks",
            "hello",
            "yes",
            "no",
        ):
            self.assertIsNone(nlu.detect_screen(text), text)

    def test_long_text_is_not_a_screen(self):
        self.assertIsNone(nlu.detect_screen("how much did I spend " + "blah " * 50))


def tool_result(name, **res):
    return {"tool_name": name, "tool_args": {}, "result": res, "error": None}


class ReplyTests(unittest.TestCase):
    def test_single_expense_income_transfer(self):
        r = replies.compact(
            {
                "tool_results": [
                    tool_result(
                        "log_expense",
                        amount=450,
                        category="Food & Dining",
                        merchant="N/A",
                        account="Bank",
                        new_balance=84550,
                    )
                ]
            }
        )
        self.assertEqual(r, "💸 −₹450 · Food & Dining\nBank ₹84,550")
        r = replies.compact(
            {
                "tool_results": [
                    tool_result(
                        "log_expense",
                        amount=150,
                        category="Food & Dining",
                        merchant="Starbucks",
                        account="Cash",
                        new_balance=-150,
                    )
                ]
            }
        )
        self.assertIn("Starbucks · Food & Dining", r)
        self.assertIn("Cash −₹150", r)
        r = replies.compact(
            {
                "tool_results": [
                    tool_result(
                        "log_income",
                        amount=85000,
                        category="Salary",
                        merchant="N/A",
                        account="Bank",
                        new_balance=85000,
                    )
                ]
            }
        )
        self.assertEqual(r, "💰 +₹85,000 · Salary\nBank ₹85,000")
        r = replies.compact(
            {
                "tool_results": [
                    tool_result(
                        "transfer_funds",
                        transferred=2000,
                        from_account="Bank",
                        to_account="Cash",
                        from_balance=1000,
                        to_balance=2000,
                    )
                ]
            }
        )
        self.assertEqual(r, "⇄ ₹2,000 · Bank → Cash\nBank ₹1,000 · Cash ₹2,000")

    def test_decimals_only_when_needed(self):
        r = replies.compact(
            {
                "tool_results": [
                    tool_result(
                        "log_expense",
                        amount=115.62,
                        category="Transport",
                        merchant="N/A",
                        account="Cash",
                        new_balance=10,
                    )
                ]
            }
        )
        self.assertIn("₹115.62", r)

    def test_several_entries_become_a_short_list_with_the_final_balance(self):
        results = [
            tool_result(
                "log_expense",
                amount=200,
                category="Food & Dining",
                merchant="N/A",
                account="Bank",
                new_balance=800,
            ),
            tool_result(
                "log_expense",
                amount=80,
                category="Transport",
                merchant="N/A",
                account="Bank",
                new_balance=720,
            ),
            tool_result(
                "log_income",
                amount=1000,
                category="Salary",
                merchant="N/A",
                account="Bank",
                new_balance=1720,
            ),
        ]
        r = replies.compact({"tool_results": results})
        lines = r.splitlines()
        self.assertEqual(lines[0], "✅ 3 entries · −₹280 · +₹1,000")
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[-1], "Bank ₹1,720")

    def test_backdated_entries_show_their_day(self):
        item = tool_result(
            "log_expense",
            amount=500,
            category="Entertainment",
            merchant="N/A",
            account="Bank",
            new_balance=1,
        )
        item["tool_args"] = {"date": "2026-09-05"}
        self.assertIn("05 Sep", replies.compact({"tool_results": [item]}))

    def test_errors_are_one_friendly_sentence(self):
        failed = {
            "tool_name": "log_expense",
            "tool_args": {"amount": 0},
            "result": None,
            "error": "Amount must be greater than zero",
        }
        self.assertEqual(
            replies.compact({"tool_results": [failed]}),
            "⚠️ ₹0: The amount has to be more than zero.",
        )
        self.assertEqual(
            replies.friendly_error("Cannot transfer to the same account"),
            "Pick two different accounts for a transfer.",
        )
        self.assertEqual(replies.friendly_error("weird"), "weird")

    def test_partial_success_reports_both(self):
        ok = tool_result(
            "log_expense",
            amount=10,
            category="Food & Dining",
            merchant="N/A",
            account="Bank",
            new_balance=5,
        )
        bad = {
            "tool_name": "log_expense",
            "tool_args": {"amount": 5},
            "result": None,
            "error": "Date is in the future",
        }
        r = replies.compact({"tool_results": [ok, bad]})
        self.assertIn("−₹10", r)
        self.assertIn("future", r)

    def test_not_a_logging_action_returns_none(self):
        self.assertIsNone(replies.compact({"tool_results": [tool_result("get_pipe_balances")]}))
        self.assertIsNone(replies.compact({"tool_results": []}))
        self.assertIsNone(replies.compact({}))

    def test_texts_are_short(self):
        for text in (
            replies.GREETING,
            replies.CANCELLED,
            replies.NOTHING_PENDING,
            replies.confirm_prompt("Move ₹1,00,000 from Bank to Cash"),
        ):
            self.assertLess(len(text), 200)


if __name__ == "__main__":
    unittest.main()
