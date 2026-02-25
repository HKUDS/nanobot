import html
from typing import Optional


class RedirectUriPageRenderer:
    def __init__(
        self,
        *,
        install_path: str,
        redirect_uri_path: str,
        success_url: Optional[str] = None,
        failure_url: Optional[str] = None,
    ):
        self.install_path = install_path
        self.redirect_uri_path = redirect_uri_path
        self.success_url = success_url
        self.failure_url = failure_url

    def render_success_page(
        self,
        app_id: str,
        team_id: Optional[str],
        is_enterprise_install: Optional[bool] = None,
        enterprise_url: Optional[str] = None,
    ) -> str:
        url = self.success_url
        if url is None:
            if is_enterprise_install is True and enterprise_url is not None and app_id is not None:
                url = f"{enterprise_url}manage/organization/apps/profile/{app_id}/workspaces/add"
            elif team_id is None or app_id is None:
                url = "slack://open"
            else:
                url = f"slack://app?team={team_id}&id={app_id}"
        browser_url = f"https://app.slack.com/client/{team_id}"

        return f"""
<html>
<head>
<meta http-equiv="refresh" content="0; URL={html.escape(url)}">
<style>
body {{
  padding: 10px 15px;
  font-family: verdana;
  text-align: center;
}}
</style>
</head>
<body>
<h2>Thank you!</h2>
<p>Redirecting to the Slack App... click <a href="{html.escape(url)}">here</a>. If you use the browser version of Slack, click <a href="{html.escape(browser_url)}" target="_blank">this link</a> instead.</p>
</body>
</html>
"""  # noqa: E501

    def render_failure_page(self, reason: str) -> str:
        return f"""
<html>
<head>
<style>
body {{
  padding: 10px 15px;
  font-family: verdana;
  text-align: center;
}}
</style>
</head>
<body>
<h2>Oops, Something Went Wrong!</h2>
<p>Please try again from <a href="{html.escape(self.install_path)}">here</a> or contact the app owner (reason: {html.escape(reason)})</p>
</body>
</html>
"""  # noqa: E501
