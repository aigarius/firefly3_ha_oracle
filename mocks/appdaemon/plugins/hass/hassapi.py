import yaml
import datetime


class Entity:
    def exists(self):
        return True

    def set_state(self, state, attributes):
        print("State: ", str(state))
        print("Attributes: ", str(attributes))


class Hass:
    def __init__(self):
        self.log = print
        self.args = {
            "firefly_url": "http://192.168.0.52:3475",
            "main_account_name": "Sparkasse giro",
            "salary_amount": 4900,
            "salary_date": 28,
            "prediction_date": datetime.date(2023, 11, 5)
        }
        with open("secrets.yaml") as infile:
            self.args["firefly_app_token"] = yaml.load(
                infile, Loader=yaml.CLoader)["firefly_app_token"].strip()

        self.initialize()

    def run_every(self, func, start_time, interval):
        func({})

    def get_entity(self, name):
        return Entity()
