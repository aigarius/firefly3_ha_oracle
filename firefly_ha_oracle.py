from decimal import Decimal
import requests
from datetime import datetime, timedelta
import appdaemon.plugins.hass.hassapi as hass


class FireflyOracle(hass.Hass):
    def initialize(self):
        # Run once per hour
        self.run_every(self.update_future, "now", 60 * 60)

    def update_future(self, kwargs):
        ent = self.get_entity("sensor.firefly3_main_account_future")
        if not ent.exists():
            ent.add(
                state=Decimal(0.0),
                attributes={
                    "native_value": Decimal(0.0),
                    "native_unit_of_measurement": "EUR",
                    "state_class": "measurement",
                    "device_class": "monetary",
                    "current_balance_date": datetime.now(),
                    "future_target_date": datetime.now(),
                },
            )
        future_date = datetime.now().date()
        if future_date.day >= 5:
            future_date = future_date + timedelta(days=30)
        future_date = future_date.replace(day=5)
        (value, balance_date) = self._calculate_future(future_date)
        ent.set_state(
            state=str(value),
            attributes={
                "native_value": str(value),
                "current_balance_date": balance_date.date().isoformat(),
                "future_target_date": future_date.isoformat(),
            },
        )

        future_date = future_date + timedelta(days=30)
        future_date = future_date.replace(day=5)
        ent = self.get_entity("sensor.firefly3_main_account_future_deep")
        if not ent.exists():
            ent.add(
                state=Decimal(0.0),
                attributes={
                    "native_value": Decimal(0.0),
                    "native_unit_of_measurement": "EUR",
                    "state_class": "measurement",
                    "device_class": "monetary",
                    "current_balance_date": datetime.now(),
                    "future_target_date": datetime.now(),
                },
            )
        (value, balance_date) = self._calculate_future(future_date)
        ent.set_state(
            state=str(value),
            attributes={
                "native_value": str(value),
                "current_balance_date": balance_date.date().isoformat(),
                "future_target_date": future_date.isoformat(),
            },
        )

    def _calculate_future(self, prediction_date):
        self.log(f"Predicting balance for {prediction_date}")
        running_balance = Decimal(0.0)

        # Get id, balance and date of the main account
        main_acc = self._get_main_account_info()
        if main_acc["balance_date"].date() > prediction_date:
            return self._return_past_balance(main_acc["id"], prediction_date)

        running_balance += main_acc["balance"]
        self.log(
            f"Main account balance: {running_balance} on {main_acc['balance_date'].date()}")
        running_balance += self._salary_prediction(
            prediction_date, balance_date=main_acc["balance_date"], main_account_id=main_acc["id"]
        )
        self.log(f"Balance after salary: {running_balance}")
        running_balance -= self._bills_due_amount(
            prediction_date, balance_date=main_acc["balance_date"])
        self.log(f"Balance after bills: {running_balance}")
        running_balance -= self._credit_cards_due(
            prediction_date, balance_date=main_acc["balance_date"], main_account_id=main_acc["id"]
        )
        self.log(f"Balance after credit cards: {running_balance}")

        return (
            running_balance,
            main_acc["balance_date"],
        )

    def _get_data_from_request(self, url):
        self.log(f"Reading from '{url}'.")
        r = requests.get(
            self.args["firefly_url"] + url,
            headers={
                "Authorization": "Bearer " + self.args["firefly_app_token"],
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/json",
            },
        )
        data = r.json()
        real_data = data["data"]
        if "links" in data and data["links"]["self"] != data["links"]["last"]:
            self.log("Next page is there!")
            real_data.extend(
                self._get_data_from_request(data["links"]["next"]))
        return real_data

    def _salary_prediction(self, prediction_date, balance_date, main_account_id):
        salary_counter = 0
        days_to_salary = self.args["salary_date"] - balance_date.day
        if days_to_salary < 0:
            self.log("Salary for this month is expected to be in already")
        elif days_to_salary > 10:
            self.log("Long time to this months salary - not checking it")
            salary_counter += 1
        else:
            self.log("Salary close, should check if it's in already")
            from_date = datetime.now().date().replace(
                day=self.args["salary_date"] - 10)
            transactions = self._get_data_from_request(
                f"/api/v1/accounts/{main_account_id}/transactions?limit=100&start={from_date}&type=deposit"
            )
            salary_found = False
            for transaction in transactions:
                transaction = transaction["attributes"]["transactions"][0]
                if (
                    Decimal(self.args["salary_amount"]) * Decimal(0.8)
                    < Decimal(transaction["amount"])
                    < Decimal(self.args["salary_amount"]) * Decimal(1.2)
                ):
                    self.log("This months salary is found")
                    salary_found = True
            if not salary_found:
                self.log("This months salary is not found")
                salary_counter += 1

        counted_date = balance_date.date()
        salary_counter -= 1
        while counted_date < prediction_date:
            counted_date = (counted_date + timedelta(days=30)
                            ).replace(day=counted_date.day)
            salary_counter += 1

        total = salary_counter * Decimal(self.args["salary_amount"])
        self.log(
            f"Expecting {salary_counter} months of salary until {prediction_date}, total: {total}")
        return total

    def _bills_due_amount(self, prediction_date, balance_date):
        running_balance = Decimal(0.0)
        bills = self._get_data_from_request(
            f"/api/v1/bills?start={balance_date.date()}&end={prediction_date}")
        for bill in bills:
            bill = bill["attributes"]
            if bill["next_expected_match"]:
                bill_date = datetime.fromisoformat(
                    bill["next_expected_match"]).date()
                if bill["repeat_freq"] == "monthly":
                    while bill_date < prediction_date:
                        self.log(
                            f"Adding bill {bill['name']} in {bill_date} for {bill['amount_max']}")
                        bill_date = (bill_date + timedelta(days=30) * (int(bill["skip"] + 1))).replace(
                            day=bill_date.day
                        )
                        running_balance += Decimal(bill["amount_max"])
                else:
                    if bill_date < prediction_date:
                        self.log(
                            f"Adding bill {bill['name']} in {bill_date} for {bill['amount_max']}")
                        running_balance += float(bill["amount_max"])
        self.log(f"All bills due: {running_balance}")
        return running_balance

    def _credit_cards_due(self, prediction_date, balance_date, main_account_id):
        outstanding_balance = Decimal(0.0)
        for account in self._get_data_from_request("/api/v1/accounts?type=asset"):
            if "attributes" not in account or "name" not in account["attributes"]:
                continue
            account_id = account["id"]
            account = account["attributes"]
            if account["account_role"] == "ccAsset" and account["credit_card_type"] == "monthlyFull":
                current_balance = Decimal(account["current_balance"])
                self.log(
                    f"Checking credit card {account['name']} with balance {current_balance}")
                repayment_date = datetime.fromisoformat(
                    account["monthly_payment_date"]).day
                self.log(f"Repayment expected on {repayment_date}")
                if (
                    balance_date.month == prediction_date.month
                    and balance_date.day < repayment_date < prediction_date.day
                ):
                    self.log(
                        "Current balance will roll over this month, adding that up")
                    outstanding_balance -= current_balance
                if balance_date.month < prediction_date.month and repayment_date < prediction_date.day:
                    self.log(
                        "Current balance will roll over by next month, adding that up")
                    outstanding_balance -= current_balance
                if (prediction_date - balance_date.date()) > timedelta(days=30):
                    self.log("Current balance will roll over, adding that up")
                    outstanding_balance -= current_balance
                if repayment_date + 6 <= balance_date.day:
                    self.log(
                        "Current month credit card balance should already be on the main account")
                if repayment_date <= balance_date.day < repayment_date + 6:
                    self.log("Repayment could be in transfer, need to check")
                    check_date = balance_date.replace(day=repayment_date - 1)
                    end_date = check_date + timedelta(days=7)
                    transfers = self._get_data_from_request(
                        f"/api/v1/transactions?type=transfers&start={check_date.date().isoformat()}&end={end_date.date().isoformat()}"
                    )
                    amount_in_flight = None
                    for transfer in transfers:
                        transfer = transfer["attributes"]
                        for sub_trans in transfer["transactions"]:
                            if sub_trans["destination_id"] == str(account_id):
                                amount_in_flight = Decimal(
                                    sub_trans["amount"]).quantize(Decimal("0.01"))
                                self.log(
                                    f"Found transfer to card account: {amount_in_flight} on {sub_trans['date']}")
                    if not amount_in_flight:
                        self.log(
                            f"No credit card repayment found - adding current balance of {current_balance}")
                        outstanding_balance += current_balance
                    else:
                        # Let's see if it arrived in main account
                        main_account_found = False
                        for transfer in transfers:
                            transfer = transfer["attributes"]
                            for sub_trans in transfer["transactions"]:
                                if sub_trans["source_id"] == str(main_account_id):
                                    if Decimal(sub_trans["amount"]) == amount_in_flight:
                                        self.log(
                                            "Found matching transfer from main account")
                                        main_account_found = True
                        if main_account_found:
                            self.log(
                                "Transfer arrived in the main account already")
                        else:
                            self.log(
                                "Transfer still in flight, adding that up")
                            outstanding_balance += amount_in_flight
        self.log(f"Credit card balances: {outstanding_balance}")
        return outstanding_balance

    def _get_main_account_info(self):
        # Get balances of main account
        for account in self._get_data_from_request("/api/v1/accounts?type=asset"):
            if "attributes" not in account or "name" not in account["attributes"]:
                continue
            account_id = account["id"]
            account = account["attributes"]
            if account["name"] == self.args["main_account_name"]:
                return {
                    "id": account_id,
                    "balance": Decimal(account["current_balance"]),
                    "balance_date": datetime.fromisoformat(account["updated_at"]),
                }


if __name__ == "__main__":
    FireflyOracle()
