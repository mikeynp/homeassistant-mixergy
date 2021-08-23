import logging
import asyncio
import json
from homeassistant.helpers import aiohttp_client

_LOGGER = logging.getLogger(__name__)

ROOT_ENDPOINT = "https://www.mixergy.io/api/v2"

class TankUrls:
    def __init__(self, account_url):
        self.account_url = account_url

class Tank:

    manufacturer = "Mixergy Ltd"

    def __init__(self, hass, username, password, serial_number):
        self._id = serial_number.lower()
        self.username = username
        self.password = password
        self.serial_number = serial_number.upper()
        self._hass = hass
        self._callbacks = set()
        self._loop = asyncio.get_event_loop()
        self._hot_water_temperature = 0
        self._coldest_water_temperature = 0
        self._eletric_heat = False
        self._indriect_heat = False
        self._hasFetched = False
        self.model = ""
        self.firmware_version = "0.0.0"

    @property
    def tank_id(self):
        return self._id

    async def test_authentication(self):
        return await self.authenticate()

    async def test_connection(self):
        return await self.fetch_tank_information()

    async def authenticate(self):

        session = aiohttp_client.async_get_clientsession(self._hass, verify_ssl=False)

        async with session.get(ROOT_ENDPOINT) as resp:

            if resp.status != 200:
                _LOGGER.info("Fetch of root at %s failed with status code %i", ROOT_ENDPOINT, resp.status)
                return False

            root_result = await resp.json()

            self._account_url = root_result["_links"]["account"]["href"]

            _LOGGER.info("Account URL: %s", self._account_url)

            async with session.get(self._account_url) as resp:

                if resp.status != 200:
                    _LOGGER.info("Fetch of account at %s failed with status code %i", self._account_url, resp.status)
                    return False

                account_result = await resp.json()

                self._login_url = account_result["_links"]["login"]["href"]

                _LOGGER.info("Login URL: %s", self._login_url)

        async with session.post(self._login_url, json={'username': self.username, 'password': self.password}) as resp:

            if resp.status != 201:
                _LOGGER.info("Authentication failed with status code %i", resp.status)
                return False

            login_result = await resp.json()
            token = login_result['token']
            self._token = token
            return True

    async def fetch_tank_information(self):

        session = aiohttp_client.async_get_clientsession(self._hass, verify_ssl=False)

        headers = {'Authorization': f'Bearer {self._token}'}

        async with session.get(ROOT_ENDPOINT, headers=headers) as resp:

            if resp.status != 200:
                _LOGGER.info("Fetch of root at %s failed with status code %i", ROOT_ENDPOINT, resp.status)
                return False

            root_result = await resp.json()

            self._tanks_url = root_result["_links"]["tanks"]["href"]

        async with session.get(self._tanks_url, headers=headers) as resp:

            if resp.status != 200:
                _LOGGER.info("Fetch of tanks at %s failed with status code %i", self._tanks_url, resp.status)
                return False

            tank_result = await resp.json()

            tanks = tank_result['_embedded']['tankList']

            _LOGGER.debug(tanks)

            tank = None

            for i, subjobj in enumerate(tanks):
                if self.serial_number == subjobj['serialNumber']:
                    _LOGGER.info("Found matching tank!")
                    tank = subjobj
                    break

            if not tank:
                _LOGGER.info("Could not find a tank with the serial number %s", self.serial_number)
                return False

            tank_url = tank["_links"]["self"]["href"]
            self.firmwareVersion = tank["firmwareVersion"]
            self.modelCode = tank["tankModelCode"]

            async with session.get(tank_url, headers=headers) as resp:

                if resp.status != 200:
                    _LOGGER.info("Fetch of the tanks details at %s failed with status %i", tank_url, resp.status)
                    return False

                tank_url_result = await resp.json()

                _LOGGER.debug(tank_url_result)

                self._latest_measurement_url = tank_url_result["_links"]["latest_measurement"]["href"]

                _LOGGER.debug("Measurement URL is %s", self._latest_measurement_url)

                return True

    async def fetch_last_measurement(self):

        session = aiohttp_client.async_get_clientsession(self._hass, verify_ssl=False)

        headers = {'Authorization': f'Bearer {self._token}'}

        async with session.get(self._latest_measurement_url, headers=headers) as resp:

            if resp.status != 200:
                _LOGGER.info("Fetch of the latest measurement at %s failed with status %i", self._latest_measurement_url, resp.status)
                return

            tank_result = await resp.json()
            _LOGGER.debug(tank_result)
            self._hot_water_temperature = tank_result["topTemperature"]
            self._coldest_water_temperature = tank_result["bottomTemperature"]
            self._charge = tank_result["charge"]

    async def fetch_data(self):

        _LOGGER.info('Fetching data....')

        await self.authenticate()

        await self.fetch_tank_information()

        await self.fetch_last_measurement()

        await self.publish_updates()

    def register_callback(self, callback):
        self._callbacks.add(callback)

    def remove_callback(self, callback):
        self._callbacks.discard(callback)

    async def publish_updates(self):
        for callback in self._callbacks:
            callback()

    @property
    def online(self):
        return True

    @property
    def hot_water_temperature(self):
        return self._hot_water_temperature

    @property
    def coldest_water_temperature(self):
        return self._coldest_water_temperature

    @property
    def charge(self):
        return self._charge