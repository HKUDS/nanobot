"""Exercise the Windows file boundary used by the WSL browser handoff."""

import base64
import os
import shutil
import subprocess

import pytest

from nanobot.cli.windows_browser import _WSL_OPEN_SCRIPT, _redirect_html


@pytest.mark.skipif(
    not shutil.which("powershell.exe") or not (os.name == "nt" or os.environ.get("WSL_DISTRO_NAME")),
    reason="Requires Windows PowerShell, natively or through WSL",
)
@pytest.mark.parametrize("opens", [True, False])
def test_windows_handoff_file_is_private_readable_and_removed(opens):
    # Keep the native filesystem and helper lifecycle; replace only desktop
    # activation so this regression never opens a user's browser during pytest.
    script = _WSL_OPEN_SCRIPT.replace(
        "return ShellExecuteEx(ref info);", f"return {str(opens).lower()};",
    ).replace("Start-Sleep -Seconds 120", "Start-Sleep -Milliseconds 30")
    check = r'''
    $acl = $guard.GetAccessControl()
    $rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 1 -or
        $acl.GetOwner([Security.Principal.SecurityIdentifier]) -ne $user -or
        $rules[0].IdentityReference -ne $user -or $rules[0].IsInherited -or
        $rules[0].AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) {
        throw 'Private ACL missing'
    }
    $reader = [IO.File]::OpenRead($path)
    try { if ($reader.Length -ne $content.Length) { throw 'Incomplete redirect' } }
    finally { $reader.Dispose() }
    $blocked = $false
    try { [IO.File]::Delete($path) } catch [IO.IOException] { $blocked = $true }
    if (-not $blocked) { throw 'Active redirect was not protected from deletion' }
    $blocked = $false
    try { [IO.File]::OpenWrite($path).Dispose() } catch [IO.IOException] { $blocked = $true }
    if (-not $blocked) { throw 'Active redirect was writable' }
    [Console]::Write('private;')
'''
    script = script.replace("    if (-not [NanobotBrowser]::Open($path))", check + "    if (-not [NanobotBrowser]::Open($path))")
    script = script.replace(
        "    if ($owned) { try { [IO.File]::Delete($path) } catch {} }",
        "    if ($owned) { [IO.File]::Delete($path) }\n"
        "    [Console]::Write('removed=' + (-not [IO.File]::Exists($path)))",
    )
    # A timeout must identify the native stage, not dump the encoded script.
    # Keep the same deadline and all filesystem/security assertions.
    script = """
$testTimer = [Diagnostics.Stopwatch]::StartNew()
function Test-Trace($stage) {
    [Console]::Error.WriteLine($stage + ': ' + $testTimer.ElapsedMilliseconds + 'ms')
}
Test-Trace 'PowerShell started'
""" + script
    for anchor, stage in (
        ("    Add-Type -TypeDefinition", "Compile helper"),
        ("    $content =", "Helper compiled"),
        ("    $file =", "Create private file"),
        ("    $acl =", "Check private file"),
        ("    if ($guard)", "Clean up private file"),
    ):
        assert anchor in script
        script = script.replace(anchor, f"    Test-Trace '{stage}'\n" + anchor, 1)
    content = _redirect_html('http://localhost/#/?bootstrapSecret="/><script>$(test)&中文</script>')

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            input=base64.b64encode(content) + b"\n", capture_output=True, timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        stages = (exc.stderr or b"").decode("utf-8", errors="replace")
        pytest.fail(f"Windows handoff exceeded 15s. Native stages:\n{stages}", pytrace=False)

    assert result.returncode == (0 if opens else 1), result.stderr
    assert result.stdout == b"private;" + (b"1" if opens else b"") + b"removed=True"
