"""Authenticate release approval separately from the download service's hashes.

The installed verifier owns the trust policy. Neither a feed, a signature bundle,
nor an environment variable may choose the signing identity or trust root.
"""

from __future__ import annotations

RELEASE_IDENTITY = (
    "https://github.com/HKUDS/nanobot/.github/workflows/release-approve.yml@refs/heads/main"
)
RELEASE_ISSUER = "https://token.actions.githubusercontent.com"


def verify_release_approval(payload: bytes, signature: bytes) -> None:
    """Require the official, manually approved workflow's logged signature.

    Sigstore verifies the certificate chain, transparency-log inclusion and
    artifact signature. Refreshing its production TUF root is fail-closed; do
    not replace this with an unverified local cache or a root from the release.
    Imports are lazy so a broken/missing verifier cannot prevent gateway startup
    or the independent recovery worker from running.
    """
    if not payload or len(payload) > 64 * 1024 or not signature or len(signature) > 256 * 1024:
        raise ValueError("Release approval is missing or exceeds its size limit")
    try:
        from sigstore.models import Bundle
        from sigstore.verify import Verifier
        from sigstore.verify.policy import AllOf, GitHubWorkflowTrigger, Identity

        policy = AllOf([
            Identity(identity=RELEASE_IDENTITY, issuer=RELEASE_ISSUER),
            GitHubWorkflowTrigger("workflow_dispatch"),
        ])
        # Reject malformed remote input before refreshing the trust service.
        # Parsing a bundle grants no authority: the fixed verifier still checks
        # its certificate, log proof, policy and signature over the exact bytes.
        bundle = Bundle.from_json(signature)
        Verifier.production().verify_artifact(payload, bundle, policy)
    except Exception as exc:
        # Keep library/network/certificate details out of the public job. A
        # missing verifier, unavailable trust service or invalid proof all deny
        # installation; none authorize a checksum-only fallback.
        raise ValueError("Could not verify the official release approval; the current installation was not changed") from exc
