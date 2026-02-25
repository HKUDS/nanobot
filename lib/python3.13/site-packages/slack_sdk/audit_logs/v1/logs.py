import json
from typing import Optional, List, Union, Any, Dict


class App:
    id: Optional[str]
    name: Optional[str]
    is_distributed: Optional[bool]
    is_directory_approved: Optional[bool]
    is_workflow_app: Optional[bool]
    scopes: Optional[List[str]]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        is_distributed: Optional[bool] = None,
        is_directory_approved: Optional[bool] = None,
        is_workflow_app: Optional[bool] = None,
        scopes: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.is_distributed = is_distributed
        self.is_directory_approved = is_directory_approved
        self.is_workflow_app = is_workflow_app
        self.scopes = scopes
        self.unknown_fields = kwargs


class User:
    id: Optional[str]
    name: Optional[str]
    email: Optional[str]
    team: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        email: Optional[str] = None,
        team: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.email = email
        self.team = team
        self.unknown_fields = kwargs


class Actor:
    type: Optional[str]
    user: Optional[User]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        type: Optional[str] = None,
        user: Optional[Union[User, Dict[str, Any]]] = None,
        **kwargs,
    ) -> None:
        self.type = type
        self.user = User(**user) if isinstance(user, dict) else user
        self.unknown_fields = kwargs


class Location:
    type: Optional[str]
    id: Optional[str]
    name: Optional[str]
    domain: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        type: Optional[str] = None,
        id: Optional[str] = None,
        name: Optional[str] = None,
        domain: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.type = type
        self.id = id
        self.name = name
        self.domain = domain
        self.unknown_fields = kwargs


class Context:
    location: Optional[Location]
    ua: Optional[str]
    ip_address: Optional[str]
    session_id: Optional[str]
    app: Optional[App]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        location: Optional[Union[Location, Dict[str, Any]]] = None,
        ua: Optional[str] = None,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
        app: Optional[Union[App, Dict[str, Any]]] = None,
        **kwargs,
    ) -> None:
        self.location = Location(**location) if isinstance(location, dict) else location
        self.ua = ua
        self.ip_address = ip_address
        self.session_id = session_id
        self.app = App(**app) if isinstance(app, dict) else app
        self.unknown_fields = kwargs


class RetentionPolicy:
    type: Optional[str]
    duration_days: Optional[int]

    def __init__(
        self,
        *,
        type: Optional[str] = None,
        duration_days: Optional[int] = None,
        **kwargs,
    ) -> None:
        self.type = type
        self.duration_days = duration_days
        self.unknown_fields = kwargs


class ConversationPref:
    type: Optional[List[str]]
    user: Optional[List[str]]

    def __init__(
        self,
        *,
        type: Optional[List[str]] = None,
        user: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        self.type = type
        self.user = user
        self.unknown_fields = kwargs


class FeatureEnablement:
    enabled: Optional[bool]

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        **kwargs,
    ) -> None:
        self.enabled = enabled
        self.unknown_fields = kwargs


class SharedWith:
    channel_id: Optional[str]
    access_level: Optional[str]

    def __init__(
        self,
        *,
        channel_id: Optional[str] = None,
        access_level: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.channel_id = channel_id
        self.access_level = access_level
        self.unknown_fields = kwargs


class Profile:
    real_name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    display_name: Optional[str]
    image_original: Optional[str]
    image_24: Optional[str]
    image_32: Optional[str]
    image_48: Optional[str]
    image_72: Optional[str]
    image_192: Optional[str]
    image_512: Optional[str]
    image_1024: Optional[str]

    def __init__(
        self,
        *,
        real_name: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        display_name: Optional[str] = None,
        image_original: Optional[str] = None,
        image_24: Optional[str] = None,
        image_32: Optional[str] = None,
        image_48: Optional[str] = None,
        image_72: Optional[str] = None,
        image_192: Optional[str] = None,
        image_512: Optional[str] = None,
        image_1024: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.real_name = real_name
        self.first_name = first_name
        self.last_name = last_name
        self.display_name = display_name
        self.image_original = image_original
        self.image_24 = image_24
        self.image_32 = image_32
        self.image_48 = image_48
        self.image_72 = image_72
        self.image_192 = image_192
        self.image_512 = image_512
        self.image_1024 = image_1024


class SpaceFileId:
    payload: Optional[str]

    def __init__(
        self,
        *,
        payload: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.payload = payload


class AttributeItems:
    type: Optional[str]

    def __init__(
        self,
        *,
        type: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.type = type


class Attribute:
    name: Optional[str]
    type: Optional[str]
    items: Optional[AttributeItems]

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        type: Optional[str] = None,
        items: Optional[AttributeItems] = None,
        **kwargs,
    ) -> None:
        self.name = name
        self.type = type
        self.items = items


class AAARuleActionResolution:
    value: Optional[str]

    def __init__(
        self,
        *,
        value: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.value = value


class AAARuleActionNotify:
    entity_type: Optional[str]

    def __init__(
        self,
        *,
        entity_type: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.entity_type = entity_type


class AAARuleAction:
    resolution: Optional[AAARuleActionResolution]
    notify: Optional[List[AAARuleActionNotify]]

    def __init__(
        self,
        *,
        resolution: Optional[Union[Dict[str, Any], AAARuleActionResolution]] = None,
        notify: Optional[List[Union[Dict[str, Any], AAARuleActionNotify]]] = None,
        **kwargs,
    ) -> None:
        self.resolution = (
            resolution
            if resolution is None or isinstance(resolution, AAARuleActionResolution)
            else AAARuleActionResolution(**resolution)
        )
        self.notify = None
        if notify is not None:
            self.notify = []
            for a in notify:
                if isinstance(a, dict):
                    self.notify.append(AAARuleActionNotify(**a))
                else:
                    self.notify.append(a)


class AAARuleConditionValue:
    field: Optional[str]
    values: Optional[List[str]]
    datatype: Optional[str]
    operator: Optional[str]

    def __init__(
        self,
        *,
        field: Optional[str] = None,
        values: Optional[List[str]] = None,
        datatype: Optional[str] = None,
        operator: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.field = field
        self.values = values
        self.datatype = datatype
        self.operator = operator


class AAARuleCondition:
    datatype: Optional[str]
    operator: Optional[str]
    values: Optional[List[AAARuleConditionValue]]
    entity_type: Optional[str]

    def __init__(
        self,
        *,
        datatype: Optional[str] = None,
        operator: Optional[str] = None,
        values: Optional[List[Union[Dict[str, Any], AAARuleConditionValue]]] = None,
        entity_type: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.datatype = datatype
        self.operator = operator
        self.values = None
        if values is not None:
            self.values = []
            for a in values:
                if isinstance(a, dict):
                    self.values.append(AAARuleConditionValue(**a))
                else:
                    self.values.append(a)
        self.entity_type = entity_type


class AAARule:
    id: Optional[str]
    team_id: Optional[str]
    title: Optional[str]
    action: Optional[AAARuleAction]
    condition: Optional[AAARuleCondition]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        team_id: Optional[str] = None,
        title: Optional[str] = None,
        action: Optional[Union[Dict[str, Any], AAARuleAction]] = None,
        condition: Optional[Union[Dict[str, Any], AAARuleCondition]] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.team_id = team_id
        self.title = title
        self.action = action if action is None or isinstance(action, AAARuleAction) else AAARuleAction(**action)
        self.condition = (
            condition if condition is None or isinstance(condition, AAARuleCondition) else AAARuleCondition(**condition)
        )


class AAARequest:
    id: Optional[str]
    team_id: Optional[str]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.team_id = team_id


class Details:
    name: Optional[str]
    new_value: Optional[Union[str, List[str], Dict[str, Any]]]
    previous_value: Optional[Union[str, List[str], Dict[str, Any]]]
    expires_on: Optional[int]
    mobile_only: Optional[bool]
    web_only: Optional[bool]
    non_sso_only: Optional[bool]
    type: Optional[str]
    is_workflow: Optional[bool]
    inviter: Optional[User]
    kicker: Optional[User]
    shared_to: Optional[str]
    reason: Optional[str]
    origin_team: Optional[str]
    target_team: Optional[str]
    is_internal_integration: Optional[bool]
    cleared_resolution: Optional[str]
    app_owner_id: Optional[str]
    bot_scopes: Optional[List[str]]
    new_scopes: Optional[List[str]]
    previous_scopes: Optional[List[str]]
    granular_bot_token: Optional[bool]
    scopes: Optional[List[str]]
    scopes_bot: Optional[List[str]]
    resolution: Optional[str]
    app_previously_resolved: Optional[bool]
    admin_app_id: Optional[str]
    bot_id: Optional[str]
    installer_user_id: Optional[str]
    approver_id: Optional[str]
    approval_type: Optional[str]
    app_previously_approved: Optional[bool]
    old_scopes: Optional[List[str]]
    channels: Optional[List[str]]
    permissions: Optional[List[Dict[str, Any]]]
    new_version_id: Optional[str]
    trigger: Optional[str]
    export_type: Optional[str]
    export_start_ts: Optional[str]
    export_end_ts: Optional[str]
    barrier_id: Optional[str]
    primary_usergroup_id: Optional[str]
    barriered_from_usergroup_ids: Optional[List[str]]
    restricted_subjects: Optional[List[str]]
    duration: Optional[int]
    desktop_app_browser_quit: Optional[bool]
    invite_id: Optional[str]
    external_organization_id: Optional[str]
    external_organization_name: Optional[str]
    external_user_id: Optional[str]
    external_user_email: Optional[str]
    channel_id: Optional[str]
    added_team_id: Optional[str]
    unknown_fields: Dict[str, Any]
    is_token_rotation_enabled_app: Optional[bool]
    old_retention_policy: Optional[RetentionPolicy]
    new_retention_policy: Optional[RetentionPolicy]
    who_can_post: Optional[ConversationPref]
    can_thread: Optional[ConversationPref]
    is_external_limited: Optional[bool]
    exporting_team_id: Optional[int]
    session_search_start: Optional[int]
    deprecation_search_end: Optional[int]
    is_error: Optional[bool]
    creator: Optional[str]
    team: Optional[str]
    app_id: Optional[str]
    enable_at_here: Optional[FeatureEnablement]
    enable_at_channel: Optional[FeatureEnablement]
    can_huddle: Optional[FeatureEnablement]
    url_private: Optional[str]
    shared_with: Optional[SharedWith]
    initiated_by: Optional[str]
    source_team: Optional[str]
    destination_team: Optional[str]
    succeeded_users: Optional[List[str]]
    failed_users: Optional[List[str]]
    enterprise: Optional[str]
    subteam: Optional[str]
    action: Optional[str]
    idp_group_member_count: Optional[int]
    workspace_member_count: Optional[int]
    added_user_count: Optional[int]
    added_user_error_count: Optional[int]
    reactivated_user_count: Optional[int]
    removed_user_count: Optional[int]
    removed_user_error_count: Optional[int]
    total_removal_count: Optional[int]
    is_flagged: Optional[str]
    target_user: Optional[str]
    idp_config_id: Optional[str]
    config_type: Optional[str]
    idp_entity_id_hash: Optional[str]
    label: Optional[str]
    previous_profile: Optional[Profile]
    new_profile: Optional[Profile]
    target_user_id: Optional[str]
    space_file_id: Optional[SpaceFileId]
    target_entity: Optional[str]
    target_entity_id: Optional[str]
    changed_permissions: Optional[List[str]]
    datastore_name: Optional[str]
    attributes: Optional[List[Attribute]]
    channel: Optional[str]
    entity_type: Optional[str]
    actor: Optional[str]
    access_level: Optional[str]
    functions: Optional[List[str]]
    workflows: Optional[List[str]]
    datastores: Optional[List[str]]
    permissions_updated: Optional[bool]
    matched_rule: Optional[AAARule]
    request: Optional[AAARequest]
    rules_checked: Optional[List[AAARule]]
    disconnecting_team: Optional[str]
    is_channel_canvas: Optional[bool]
    linked_channel_id: Optional[str]
    column_id: Optional[str]
    row_id: Optional[str]
    cell_date_updated: Optional[int]
    view_id: Optional[str]
    user: Optional[str]

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        new_value: Optional[Union[str, List[str], Dict[str, Any]]] = None,
        previous_value: Optional[Union[str, List[str], Dict[str, Any]]] = None,
        expires_on: Optional[int] = None,
        mobile_only: Optional[bool] = None,
        web_only: Optional[bool] = None,
        non_sso_only: Optional[bool] = None,
        type: Optional[str] = None,
        is_workflow: Optional[bool] = None,
        inviter: Optional[Union[Dict[str, Any], User]] = None,
        kicker: Optional[Union[Dict[str, Any], User]] = None,
        shared_to: Optional[str] = None,
        reason: Optional[str] = None,
        origin_team: Optional[str] = None,
        target_team: Optional[str] = None,
        is_internal_integration: Optional[bool] = None,
        cleared_resolution: Optional[str] = None,
        app_owner_id: Optional[str] = None,
        bot_scopes: Optional[List[str]] = None,
        new_scopes: Optional[List[str]] = None,
        previous_scopes: Optional[List[str]] = None,
        granular_bot_token: Optional[bool] = None,
        scopes: Optional[List[str]] = None,
        scopes_bot: Optional[List[str]] = None,
        resolution: Optional[str] = None,
        app_previously_resolved: Optional[bool] = None,
        admin_app_id: Optional[str] = None,
        bot_id: Optional[str] = None,
        installer_user_id: Optional[str] = None,
        approver_id: Optional[str] = None,
        approval_type: Optional[str] = None,
        app_previously_approved: Optional[bool] = None,
        old_scopes: Optional[List[str]] = None,
        channels: Optional[List[str]] = None,
        permissions: Optional[List[Dict[str, Any]]] = None,
        new_version_id: Optional[str] = None,
        trigger: Optional[str] = None,
        export_type: Optional[str] = None,
        export_start_ts: Optional[str] = None,
        export_end_ts: Optional[str] = None,
        barrier_id: Optional[str] = None,
        primary_usergroup_id: Optional[str] = None,
        barriered_from_usergroup_ids: Optional[List[str]] = None,
        restricted_subjects: Optional[List[str]] = None,
        duration: Optional[int] = None,
        desktop_app_browser_quit: Optional[bool] = None,
        invite_id: Optional[str] = None,
        external_organization_id: Optional[str] = None,
        external_organization_name: Optional[str] = None,
        external_user_id: Optional[str] = None,
        external_user_email: Optional[str] = None,
        channel_id: Optional[str] = None,
        added_team_id: Optional[str] = None,
        is_token_rotation_enabled_app: Optional[bool] = None,
        old_retention_policy: Optional[Union[Dict[str, Any], RetentionPolicy]] = None,
        new_retention_policy: Optional[Union[Dict[str, Any], RetentionPolicy]] = None,
        who_can_post: Optional[Union[Dict[str, List[str]], ConversationPref]] = None,
        can_thread: Optional[Union[Dict[str, List[str]], ConversationPref]] = None,
        is_external_limited: Optional[bool] = None,
        exporting_team_id: Optional[int] = None,
        session_search_start: Optional[int] = None,
        deprecation_search_end: Optional[int] = None,
        is_error: Optional[bool] = None,
        creator: Optional[str] = None,
        team: Optional[str] = None,
        app_id: Optional[str] = None,
        enable_at_here: Optional[Union[Dict[str, Any], FeatureEnablement]] = None,
        enable_at_channel: Optional[Union[Dict[str, Any], FeatureEnablement]] = None,
        can_huddle: Optional[Union[Dict[str, Any], FeatureEnablement]] = None,
        url_private: Optional[str] = None,
        shared_with: Optional[Union[Dict[str, Any], SharedWith]] = None,
        initiated_by: Optional[str] = None,
        source_team: Optional[str] = None,
        destination_team: Optional[str] = None,
        succeeded_users: Optional[Union[List[str], str]] = None,
        failed_users: Optional[Union[List[str], str]] = None,
        enterprise: Optional[str] = None,
        subteam: Optional[str] = None,
        action: Optional[str] = None,
        idp_group_member_count: Optional[int] = None,
        workspace_member_count: Optional[int] = None,
        added_user_count: Optional[int] = None,
        added_user_error_count: Optional[int] = None,
        reactivated_user_count: Optional[int] = None,
        removed_user_count: Optional[int] = None,
        removed_user_error_count: Optional[int] = None,
        total_removal_count: Optional[int] = None,
        is_flagged: Optional[str] = None,
        target_user: Optional[str] = None,
        idp_config_id: Optional[str] = None,
        config_type: Optional[str] = None,
        idp_entity_id_hash: Optional[str] = None,
        label: Optional[str] = None,
        previous_profile: Optional[Union[Dict[str, Any], Profile]] = None,
        new_profile: Optional[Union[Dict[str, Any], Profile]] = None,
        target_user_id: Optional[str] = None,
        space_file_id: Optional[Union[Dict[str, Any], SpaceFileId]] = None,
        target_entity: Optional[str] = None,
        target_entity_id: Optional[str] = None,
        changed_permissions: Optional[List[str]] = None,
        datastore_name: Optional[str] = None,
        attributes: Optional[List[Union[Dict[str, str], Attribute]]] = None,
        channel: Optional[str] = None,
        entity_type: Optional[str] = None,
        actor: Optional[str] = None,
        access_level: Optional[str] = None,
        functions: Optional[List[str]] = None,
        workflows: Optional[List[str]] = None,
        datastores: Optional[List[str]] = None,
        permissions_updated: Optional[bool] = None,
        matched_rule: Optional[Union[Dict[str, Any], AAARule]] = None,
        request: Optional[Union[Dict[str, Any], AAARequest]] = None,
        rules_checked: Optional[List[Union[Dict[str, Any], AAARule]]] = None,
        disconnecting_team: Optional[str] = None,
        is_channel_canvas: Optional[bool] = None,
        linked_channel_id: Optional[str] = None,
        column_id: Optional[str] = None,
        row_id: Optional[str] = None,
        cell_date_updated: Optional[int] = None,
        view_id: Optional[str] = None,
        user: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.name = name
        self.new_value = new_value
        self.previous_value = previous_value
        self.expires_on = expires_on
        self.mobile_only = mobile_only
        self.web_only = web_only
        self.non_sso_only = non_sso_only
        self.type = type
        self.is_workflow = is_workflow
        self.inviter = inviter if inviter is None or isinstance(inviter, User) else User(**inviter)
        self.kicker = kicker if kicker is None or isinstance(kicker, User) else User(**kicker)
        self.shared_to = shared_to
        self.reason = reason
        self.origin_team = origin_team
        self.target_team = target_team
        self.is_internal_integration = is_internal_integration
        self.cleared_resolution = cleared_resolution
        self.app_owner_id = app_owner_id
        self.bot_scopes = bot_scopes
        self.new_scopes = new_scopes
        self.previous_scopes = previous_scopes
        self.granular_bot_token = granular_bot_token
        self.scopes = scopes
        self.scopes_bot = scopes_bot
        self.resolution = resolution
        self.app_previously_resolved = app_previously_resolved
        self.admin_app_id = admin_app_id
        self.bot_id = bot_id
        self.unknown_fields = kwargs
        self.installer_user_id = installer_user_id
        self.approver_id = approver_id
        self.approval_type = approval_type
        self.app_previously_approved = app_previously_approved
        self.old_scopes = old_scopes
        self.channels = channels
        self.permissions = permissions
        self.new_version_id = new_version_id
        self.trigger = trigger
        self.export_type = export_type
        self.export_start_ts = export_start_ts
        self.export_end_ts = export_end_ts
        self.barrier_id = barrier_id
        self.primary_usergroup_id = primary_usergroup_id
        self.barriered_from_usergroup_ids = barriered_from_usergroup_ids
        self.restricted_subjects = restricted_subjects
        self.duration = duration
        self.desktop_app_browser_quit = desktop_app_browser_quit
        self.invite_id = invite_id
        self.external_organization_id = external_organization_id
        self.external_organization_name = external_organization_name
        self.external_user_id = external_user_id
        self.external_user_email = external_user_email
        self.channel_id = channel_id
        self.added_team_id = added_team_id
        self.is_token_rotation_enabled_app = is_token_rotation_enabled_app
        self.old_retention_policy = (
            old_retention_policy
            if old_retention_policy is None or isinstance(old_retention_policy, RetentionPolicy)
            else RetentionPolicy(**old_retention_policy)
        )
        self.new_retention_policy = (
            new_retention_policy
            if new_retention_policy is None or isinstance(new_retention_policy, RetentionPolicy)
            else RetentionPolicy(**new_retention_policy)
        )
        self.who_can_post = (
            who_can_post
            if who_can_post is None or isinstance(who_can_post, ConversationPref)
            else ConversationPref(**who_can_post)
        )
        self.can_thread = (
            can_thread if can_thread is None or isinstance(can_thread, ConversationPref) else ConversationPref(**can_thread)
        )
        self.is_external_limited = is_external_limited
        self.exporting_team_id = exporting_team_id
        self.session_search_start = session_search_start
        self.deprecation_search_end = deprecation_search_end
        self.is_error = is_error
        self.creator = creator
        self.team = team
        self.app_id = app_id
        self.enable_at_here = (
            enable_at_here
            if enable_at_here is None or isinstance(enable_at_here, FeatureEnablement)
            else FeatureEnablement(**enable_at_here)
        )
        self.enable_at_channel = (
            enable_at_channel
            if enable_at_channel is None or isinstance(enable_at_channel, FeatureEnablement)
            else FeatureEnablement(**enable_at_channel)
        )
        self.can_huddle = (
            can_huddle
            if can_huddle is None or isinstance(can_huddle, FeatureEnablement)
            else FeatureEnablement(**can_huddle)
        )
        self.url_private = url_private
        self.shared_with = (
            shared_with if shared_with is None or isinstance(shared_with, SharedWith) else SharedWith(**shared_with)
        )
        self.initiated_by = initiated_by
        self.source_team = source_team
        self.destination_team = destination_team
        self.succeeded_users = (
            succeeded_users if succeeded_users is None or isinstance(succeeded_users, list) else json.loads(succeeded_users)
        )
        self.failed_users = (
            failed_users if failed_users is None or isinstance(failed_users, list) else json.loads(failed_users)
        )
        self.enterprise = enterprise
        self.subteam = subteam
        self.action = action
        self.idp_group_member_count = idp_group_member_count
        self.workspace_member_count = workspace_member_count
        self.added_user_count = added_user_count
        self.added_user_error_count = added_user_error_count
        self.reactivated_user_count = reactivated_user_count
        self.removed_user_count = removed_user_count
        self.removed_user_error_count = removed_user_error_count
        self.total_removal_count = total_removal_count
        self.is_flagged = is_flagged
        self.target_user = target_user
        self.idp_config_id = idp_config_id
        self.config_type = config_type
        self.idp_entity_id_hash = idp_entity_id_hash
        self.label = label
        self.previous_profile = (
            previous_profile
            if previous_profile is None or isinstance(previous_profile, Profile)
            else Profile(**previous_profile)
        )
        self.new_profile = new_profile if new_profile is None or isinstance(new_profile, Profile) else Profile(**new_profile)
        self.target_user_id = target_user_id
        self.space_file_id = (
            space_file_id
            if space_file_id is None or isinstance(space_file_id, SpaceFileId)
            else SpaceFileId(**space_file_id)
        )
        self.target_entity = target_entity
        self.target_entity_id = target_entity_id
        self.changed_permissions = changed_permissions
        self.datastore_name = datastore_name
        self.attributes = None
        if attributes is not None:
            self.attributes = []
            for a in attributes:
                if isinstance(a, dict):
                    self.attributes.append(Attribute(**a))  # type: ignore[arg-type]
                else:
                    self.attributes.append(a)
        self.channel = channel
        self.entity_type = entity_type
        self.actor = actor
        self.access_level = access_level
        self.functions = functions
        self.workflows = workflows
        self.datastores = datastores
        self.permissions_updated = permissions_updated
        self.matched_rule = (
            matched_rule if matched_rule is None or isinstance(matched_rule, AAARule) else AAARule(**matched_rule)
        )
        self.request = request if request is None or isinstance(request, AAARequest) else AAARequest(**request)
        self.rules_checked = None
        if rules_checked is not None:
            self.rules_checked = []
            for a in rules_checked:  # type: ignore[assignment]
                if isinstance(a, dict):
                    self.rules_checked.append(AAARule(**a))  # type: ignore[arg-type]
                else:
                    self.rules_checked.append(a)  # type: ignore[arg-type]
        self.disconnecting_team = disconnecting_team
        self.is_channel_canvas = is_channel_canvas
        self.linked_channel_id = linked_channel_id
        self.column_id = column_id
        self.row_id = row_id
        self.cell_date_updated = cell_date_updated
        self.view_id = view_id
        self.user = user


class Channel:
    id: Optional[str]
    privacy: Optional[str]
    name: Optional[str]
    is_shared: Optional[bool]
    is_org_shared: Optional[bool]
    teams_shared_with: Optional[List[str]]
    original_connected_channel_id: Optional[str]
    is_salesforce_channel: Optional[bool]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        privacy: Optional[str] = None,
        name: Optional[str] = None,
        is_shared: Optional[bool] = None,
        is_org_shared: Optional[bool] = None,
        teams_shared_with: Optional[List[str]] = None,
        original_connected_channel_id: Optional[str] = None,
        is_salesforce_channel: Optional[bool] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.privacy = privacy
        self.name = name
        self.is_shared = is_shared
        self.is_org_shared = is_org_shared
        self.teams_shared_with = teams_shared_with
        self.original_connected_channel_id = original_connected_channel_id
        self.is_salesforce_channel = is_salesforce_channel
        self.unknown_fields = kwargs


class File:
    id: Optional[str]
    name: Optional[str]
    filetype: Optional[str]
    title: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        filetype: Optional[str] = None,
        title: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.filetype = filetype
        self.title = title
        self.unknown_fields = kwargs


class Usergroup:
    id: Optional[str]
    name: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.unknown_fields = kwargs


class Message:
    channel: Optional[str]
    team: Optional[str]
    timestamp: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        channel: Optional[str] = None,
        team: Optional[str] = None,
        timestamp: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.channel = channel
        self.team = team
        self.timestamp = timestamp
        self.unknown_fields = kwargs


class Huddle:
    id: Optional[str]
    date_start: Optional[int]
    date_end: Optional[int]
    participants: Optional[List[str]]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        date_start: Optional[int] = None,
        date_end: Optional[int] = None,
        participants: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.date_start = date_start
        self.date_end = date_end
        self.participants = participants
        self.unknown_fields = kwargs


class Role:
    id: Optional[str]
    name: Optional[str]
    type: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        type: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.type = type
        self.unknown_fields = kwargs


class Workflow:
    id: Optional[str]
    name: Optional[str]
    domain: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        domain: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.domain = domain
        self.unknown_fields = kwargs


class InformationBarrier:
    id: Optional[str]
    primary_usergroup: Optional[str]
    barriered_from_usergroups: Optional[List[str]]
    restricted_subjects: Optional[List[str]]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        primary_usergroup: Optional[str] = None,
        barriered_from_usergroups: Optional[List[str]] = None,
        restricted_subjects: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.primary_usergroup = primary_usergroup
        self.barriered_from_usergroups = barriered_from_usergroups
        self.restricted_subjects = restricted_subjects
        self.unknown_fields = kwargs


class WorkflowV2StepConfiguration:
    name: Optional[str]
    step_function_type: Optional[str]
    step_function_app_id: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        step_function_type: Optional[str] = None,
        step_function_app_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.name = name
        self.step_function_type = step_function_type
        self.step_function_app_id = step_function_app_id
        self.unknown_fields = kwargs


class WorkflowV2:
    id: Optional[str]
    app_id: Optional[str]
    date_updated: Optional[int]
    callback_id: Optional[str]
    name: Optional[str]
    updated_by: Optional[str]
    step_configuration: Optional[List[WorkflowV2StepConfiguration]]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        app_id: Optional[str] = None,
        date_updated: Optional[int] = None,
        callback_id: Optional[str] = None,
        name: Optional[str] = None,
        updated_by: Optional[str] = None,
        step_configuration: Optional[List[Union[Dict[str, Any], WorkflowV2StepConfiguration]]] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.app_id = app_id
        self.date_updated = date_updated
        self.callback_id = callback_id
        self.name = name
        self.updated_by = updated_by
        self.step_configuration = None
        if step_configuration is not None:
            self.step_configuration = []
            for a in step_configuration:
                if isinstance(a, dict):
                    self.step_configuration.append(WorkflowV2StepConfiguration(**a))
                else:
                    self.step_configuration.append(a)
        self.unknown_fields = kwargs


class AccountTypeRole:
    id: Optional[str]
    name: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        name: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.name = name
        self.unknown_fields = kwargs


class SlackList:
    id: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.unknown_fields = kwargs


class Entity:
    type: Optional[str]
    user: Optional[User]
    workspace: Optional[Location]
    enterprise: Optional[Location]
    channel: Optional[Channel]
    file: Optional[File]
    app: Optional[App]
    message: Optional[Message]
    huddle: Optional[Huddle]
    role: Optional[Role]
    usergroup: Optional[Usergroup]
    workflow: Optional[Workflow]
    barrier: Optional[InformationBarrier]
    workflow_v2: Optional[WorkflowV2]
    account_type_role: Optional[AccountTypeRole]
    list: Optional[SlackList]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        type: Optional[str] = None,
        user: Optional[Union[User, Dict[str, Any]]] = None,
        workspace: Optional[Union[Location, Dict[str, Any]]] = None,
        enterprise: Optional[Union[Location, Dict[str, Any]]] = None,
        channel: Optional[Union[Channel, Dict[str, Any]]] = None,
        file: Optional[Union[File, Dict[str, Any]]] = None,
        app: Optional[Union[App, Dict[str, Any]]] = None,
        message: Optional[Union[Message, Dict[str, Any]]] = None,
        huddle: Optional[Union[Huddle, Dict[str, Any]]] = None,
        role: Optional[Union[Role, Dict[str, Any]]] = None,
        usergroup: Optional[Union[Usergroup, Dict[str, Any]]] = None,
        workflow: Optional[Union[Workflow, Dict[str, Any]]] = None,
        barrier: Optional[Union[InformationBarrier, Dict[str, Any]]] = None,
        workflow_v2: Optional[Union[WorkflowV2, Dict[str, Any]]] = None,
        account_type_role: Optional[Union[AccountTypeRole, Dict[str, Any]]] = None,
        list: Optional[Union[SlackList, Dict[str, Any]]] = None,
        **kwargs,
    ) -> None:
        self.type = type
        self.user = User(**user) if isinstance(user, dict) else user
        self.workspace = Location(**workspace) if isinstance(workspace, dict) else workspace
        self.enterprise = Location(**enterprise) if isinstance(enterprise, dict) else enterprise
        self.channel = Channel(**channel) if isinstance(channel, dict) else channel
        self.file = File(**file) if isinstance(file, dict) else file
        self.app = App(**app) if isinstance(app, dict) else app
        self.message = Message(**message) if isinstance(message, dict) else message
        self.huddle = Huddle(**huddle) if isinstance(huddle, dict) else huddle
        self.role = Role(**role) if isinstance(role, dict) else role
        self.usergroup = Usergroup(**usergroup) if isinstance(usergroup, dict) else usergroup
        self.workflow = Workflow(**workflow) if isinstance(workflow, dict) else workflow
        self.barrier = InformationBarrier(**barrier) if isinstance(barrier, dict) else barrier
        self.workflow_v2 = WorkflowV2(**workflow_v2) if isinstance(workflow_v2, dict) else workflow_v2
        self.account_type_role = (
            AccountTypeRole(**account_type_role) if isinstance(account_type_role, dict) else account_type_role
        )
        self.list = SlackList(**list) if isinstance(list, dict) else list
        self.unknown_fields = kwargs


class Entry:
    id: Optional[str]
    date_create: Optional[int]
    action: Optional[str]
    actor: Optional[Actor]
    entity: Optional[Entity]
    context: Optional[Context]
    details: Optional[Details]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        id: Optional[str] = None,
        date_create: Optional[int] = None,
        action: Optional[str] = None,
        actor: Optional[Union[Actor, Dict[str, Any]]] = None,
        entity: Optional[Union[Entity, Dict[str, Any]]] = None,
        context: Optional[Union[Context, Dict[str, Any]]] = None,
        details: Optional[Union[Details, Dict[str, Any]]] = None,
        **kwargs,
    ) -> None:
        self.id = id
        self.date_create = date_create
        self.action = action
        self.actor = Actor(**actor) if isinstance(actor, dict) else actor
        self.entity = Entity(**entity) if isinstance(entity, dict) else entity
        self.context = Context(**context) if isinstance(context, dict) else context
        self.details = Details(**details) if isinstance(details, dict) else details
        self.unknown_fields = kwargs


class ResponseMetadata:
    next_cursor: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        next_cursor: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.next_cursor = next_cursor
        self.unknown_fields = kwargs


class LogsResponse:
    entries: Optional[List[Entry]]
    response_metadata: Optional[ResponseMetadata]
    ok: Optional[bool]
    error: Optional[str]
    needed: Optional[str]
    provided: Optional[str]
    unknown_fields: Dict[str, Any]

    def __init__(
        self,
        *,
        entries: Optional[List[Union[Entry, Dict[str, Any]]]] = None,
        response_metadata: Optional[Union[ResponseMetadata, Dict[str, Any]]] = None,
        ok: Optional[bool] = None,
        error: Optional[str] = None,
        needed: Optional[str] = None,
        provided: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.entries = [Entry(**e) if isinstance(e, dict) else e for e in entries]  # type: ignore[union-attr]
        self.response_metadata = (
            ResponseMetadata(**response_metadata) if isinstance(response_metadata, dict) else response_metadata
        )
        self.ok = ok
        self.error = error
        self.needed = needed
        self.provided = provided
        self.unknown_fields = kwargs
