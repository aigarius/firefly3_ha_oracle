import requests
from datetime import datetime, timedelta
import appdaemon.plugins.hass.hassapi as hass


class FireflyOracle(hass.Hass):

    def initialize(self):
        # Run once per hour
        self.run_every(self.update_future, "now", 60*60)

    def update_future(self, kwargs):
        ent = self.get_entity("sensor.firefly3_main_account_future")
        if not ent.exists():
            ent.add(
                state=0.0,
                attributes={
                    "native_value": 0.0,
                    "native_unit_of_measurement": "EUR",
                    "state_class": "measurement",
                    "device_class": "monetary",
                    "current_balance_date": datetime.now(),
                    "future_target_date": datetime.now(),
                })
        (value, balance_date, future_date) = self._calculate_future()
        ent.set_state(
            state=value,
            attributes={
                "native_value": value,
                "current_balance_date": balance_date,
                "future_target_date": future_date,
            })

    def _calculate_future(self):
        prediction_date = self.args["prediction_date"]
        print(f"Predicting balance for {prediction_date}")
        running_balance = 0.0

        # Get id, balance and date of the main account
        main_acc = self._get_main_account_info()
        if main_acc["balance_date"].date() > prediction_date:
            return self._return_past_balance(main_acc["id"], prediction_date)

        running_balance += main_acc["balance"]
        print(f"Main account balance is {running_balance}")
        running_balance += self._salary_prediction(
            prediction_date, balance_date=main_acc["balance_date"], main_account_id=main_acc["id"])
        running_balance -= self._bills_due_amount(
            prediction_date, balance_date=main_acc["balance_date"])
        running_balance -= self._credit_cards_due(
            prediction_date, balance_date=main_acc["balance_date"])

        return (
            running_balance,
            main_acc["balance_date"],
            prediction_date,
        )

    def _get_data_from_request(self, url):
        print(f"Reading from {url} .")
        r = requests.get(
            self.args["firefly_url"] + url,
            headers={
                "Authorization": "Bearer " + self.args["firefly_app_token"],
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/json",
            })
        data = r.json()
        print(data)
        if "links" in data and "next" in data["links"] and data["links"]["self"] != data["links"]["next"]:
            print("Next page is there!")
            print(data["links"], data["meta"])
        return data["data"]

    def _salary_prediction(self, prediction_date, balance_date, main_account_id):
        salary_counter = 0
        days_to_salary = self.args["salary_date"] - balance_date.day
        print(days_to_salary)
        if days_to_salary < 0:
            print("Salary for this month is expected to be in already")
        elif days_to_salary > 5:
            print("Long time to this months salary - not checking it")
            salary_counter += 1
        else:
            print("Salary close, should check if it's in already")
            from_date = datetime.now().date().replace(
                day=self.args["salary_date"] - 10)
            transactions = self._get_data_from_request(
                f"/api/v1/accounts/{main_account_id}/transactions?limit=100&start={from_date}&type=deposit")
            for transaction in transactions:
                transaction = transaction["attributes"]["transactions"][0]
                print(transaction)
                if float(self.args["salary_amount"]) * 0.8 < float(transaction["amount"]) < float(self.args["salary_amount"]) * 1.2:
                    print("This months salary is found")
                    salary_counter += 1
                else:
                    print("Not a salary")

        counted_date = balance_date.date()
        while counted_date < prediction_date:
            counted_date = (counted_date + timedelta(days=30)
                            ).replace(day=counted_date.day)
            salary_counter += 1
        print(
            f"Expecting {salary_counter} months of salary until {prediction_date}")

        return salary_counter * float(self.args["salary_amount"])

    def _bills_due_amount(self, prediction_date, balance_date):
        return 0.0

    def _credit_cards_due(self, prediction_date, balance_date):
        return 0.0

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
                    "balance": float(account["current_balance"]),
                    "balance_date": datetime.fromisoformat(account["current_balance_date"]),
                }

    def _get_credit_card_balances(self):
        # Get balances of credit cards
        credit_cards = []
        for account in self._get_data_from_request("/api/v1/accounts?type=asset"):
            if "attributes" not in account or "name" not in account["attributes"]:
                continue
            account_id = account["id"]
            account = account["attributes"]
            if account["account_role"] == "ccAsset" and account["credit_card_type"] == 'monthlyFull':
                credit_cards.append({
                    "id": account_id,
                    "name": account["name"],
                    "current_balance": float(account["current_balance"]),
                    "current_balance_date": datetime.fromisoformat(account["current_balance_date"]),
                    "monthly_payment_date": datetime.fromisoformat(account["monthly_payment_date"]).day,
                })
        return credit_cards


if __name__ == "__main__":
    FireflyOracle()
