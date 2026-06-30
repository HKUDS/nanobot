"""Turn-scoped opaque attachment handles.

A non-vision model never sees an uploaded image's pixels — the provider strip
layer replaces every ``image_url`` block with a text marker. Before this module
the marker leaked the raw server path, which let the model hallucinate the image
or ``read_file`` the path. PR #4346 replaced that with an opaque placeholder, but
that removed the *only* model-visible reference a non-vision model had to
*forward* the uploaded file (e.g. attach it to an email) without inspecting it.

This registry restores that flow safely. Each turn mints a short, opaque id
(``attachment_1``) per uploaded image and keeps the ``id -> path`` map in a
turn-scoped :class:`~contextvars.ContextVar`. The model only ever sees the id;
the path lives here (server-side) and in the message ``_meta`` (stripped before
send). The message tool resolves a handle by a pure dict lookup — never path
resolution — so a forged id or a smuggled path simply resolves to ``None``.

Layering: this module lives under ``nanobot/agent/`` and is read/written only by
agent code (``context.py`` mints, ``message.py`` resolves, ``loop.py`` resets per
turn). The provider strip layer in ``providers/base.py`` never imports it; the id
rides inside ``_meta`` in the message data instead.
"""

from contextvars import ContextVar

from loguru import logger

# ``default=None`` (not ``default={}``): a ContextVar with a mutable default
# shares one dict across every context that never calls ``.set()``, which would
# leak handles across turns and sessions. We instead start from ``None`` and have
# ``begin_turn()`` install a fresh dict each turn. See ``MessageTool`` and its
# ``_turn_delivered_media_var`` for the same pattern.
_registry_var: ContextVar[dict[str, str] | None] = ContextVar(
    "attachment_registry", default=None
)


def begin_turn() -> None:
    """Install a fresh, empty registry for the current turn.

    Called once per turn (next to ``MessageTool.start_turn()``) so handles minted
    this turn cannot collide with or resolve to a previous turn's uploads.
    """
    _registry_var.set({})


def mint(path: str) -> str:
    """Register ``path`` for this turn and return its opaque handle id.

    Ids are sequential (``attachment_1``, ``attachment_2``, …) and turn-scoped.
    They are greppable, never collide with a real filesystem path, and contain no
    path. A turn registry is normally installed by :func:`begin_turn` at the start
    of the turn; minting without one is a wiring bug (the handle would not share a
    context with ``resolve`` and would silently drop), so we warn loudly and create
    one rather than fail the user's turn.
    """
    registry = _registry_var.get()
    if registry is None:
        logger.warning(
            "attachment_registry.mint() called with no turn registry installed; "
            "begin_turn() should run first. Creating one lazily — handles may not "
            "resolve if mint and resolve are in different contexts."
        )
        registry = {}
        _registry_var.set(registry)
    handle = f"attachment_{len(registry) + 1}"
    registry[handle] = path
    return handle


def resolve(handle: str) -> str | None:
    """Return the path registered for ``handle`` this turn, or ``None``.

    Pure dict-key lookup — never path resolution. A forged id, a path string
    passed as a handle, or a handle from a previous turn all miss and return
    ``None``.
    """
    registry = _registry_var.get()
    if not registry:
        return None
    return registry.get(handle)
