from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.acct_item: AcctItem = AcctItem(config)
        self.cost_allocation_detail: CostAllocationDetail = CostAllocationDetail(config)
        self.cost_allocation_plan: CostAllocationPlan = CostAllocationPlan(config)
        self.cost_allocation_report: CostAllocationReport = CostAllocationReport(config)
        self.datasource: Datasource = Datasource(config)
        self.datasource_record: DatasourceRecord = DatasourceRecord(config)
        self.paygroup: Paygroup = Paygroup(config)
        self.payment_activity: PaymentActivity = PaymentActivity(config)
        self.payment_activity_detail: PaymentActivityDetail = PaymentActivityDetail(config)
        self.payment_detail: PaymentDetail = PaymentDetail(config)
