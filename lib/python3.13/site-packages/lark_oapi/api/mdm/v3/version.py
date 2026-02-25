from .resource import *


class V3(object):
    def __init__(self, config: Config) -> None:
        self.batch_country_region: BatchCountryRegion = BatchCountryRegion(config)
        self.country_region: CountryRegion = CountryRegion(config)
