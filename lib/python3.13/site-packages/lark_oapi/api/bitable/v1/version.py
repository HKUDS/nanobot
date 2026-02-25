from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.app: App = App(config)
        self.app_dashboard: AppDashboard = AppDashboard(config)
        self.app_role: AppRole = AppRole(config)
        self.app_role_member: AppRoleMember = AppRoleMember(config)
        self.app_table: AppTable = AppTable(config)
        self.app_table_field: AppTableField = AppTableField(config)
        self.app_table_form: AppTableForm = AppTableForm(config)
        self.app_table_form_field: AppTableFormField = AppTableFormField(config)
        self.app_table_record: AppTableRecord = AppTableRecord(config)
        self.app_table_view: AppTableView = AppTableView(config)
        self.app_workflow: AppWorkflow = AppWorkflow(config)
