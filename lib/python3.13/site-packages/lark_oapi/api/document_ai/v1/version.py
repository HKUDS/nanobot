from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.bank_card: BankCard = BankCard(config)
        self.business_card: BusinessCard = BusinessCard(config)
        self.business_license: BusinessLicense = BusinessLicense(config)
        self.chinese_passport: ChinesePassport = ChinesePassport(config)
        self.contract: Contract = Contract(config)
        self.driving_license: DrivingLicense = DrivingLicense(config)
        self.food_manage_license: FoodManageLicense = FoodManageLicense(config)
        self.food_produce_license: FoodProduceLicense = FoodProduceLicense(config)
        self.health_certificate: HealthCertificate = HealthCertificate(config)
        self.hkm_mainland_travel_permit: HkmMainlandTravelPermit = HkmMainlandTravelPermit(config)
        self.id_card: IdCard = IdCard(config)
        self.resume: Resume = Resume(config)
        self.taxi_invoice: TaxiInvoice = TaxiInvoice(config)
        self.train_invoice: TrainInvoice = TrainInvoice(config)
        self.tw_mainland_travel_permit: TwMainlandTravelPermit = TwMainlandTravelPermit(config)
        self.vat_invoice: VatInvoice = VatInvoice(config)
        self.vehicle_invoice: VehicleInvoice = VehicleInvoice(config)
        self.vehicle_license: VehicleLicense = VehicleLicense(config)
