from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.app: App = App(config)
        self.application_audit_log: ApplicationAuditLog = ApplicationAuditLog(config)
        self.application_environment_variable: ApplicationEnvironmentVariable = ApplicationEnvironmentVariable(config)
        self.application_flow: ApplicationFlow = ApplicationFlow(config)
        self.application_function: ApplicationFunction = ApplicationFunction(config)
        self.application_object: ApplicationObject = ApplicationObject(config)
        self.application_object_record: ApplicationObjectRecord = ApplicationObjectRecord(config)
        self.application_record_permission_member: ApplicationRecordPermissionMember = ApplicationRecordPermissionMember(
            config)
        self.application_role_member: ApplicationRoleMember = ApplicationRoleMember(config)
        self.approval_instance: ApprovalInstance = ApprovalInstance(config)
        self.approval_task: ApprovalTask = ApprovalTask(config)
        self.seat_activity: SeatActivity = SeatActivity(config)
        self.seat_assignment: SeatAssignment = SeatAssignment(config)
        self.user_task: UserTask = UserTask(config)
        self.workspace: Workspace = Workspace(config)
        self.workspace_enum: WorkspaceEnum = WorkspaceEnum(config)
        self.workspace_table: WorkspaceTable = WorkspaceTable(config)
        self.workspace_view: WorkspaceView = WorkspaceView(config)
