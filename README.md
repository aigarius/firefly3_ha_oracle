# firefly3_ha_oracle
AppDaemon script to integrate Firefly III data into Home Assistant and predict some future

apps.yaml needs to define the "firefly_app_token" variable with a personal access token
from the Firefly III instance being used as well as main account name and salary info

You should be able to run the script with the following command locally:

PYTHONPATH=$(pwd)/mocks python3 firefly_ha_oracle.py
