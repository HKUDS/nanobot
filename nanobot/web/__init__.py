"""Embedded web UI assets.

The ``dist/`` subdirectory holds the production WebUI bundle served by the
gateway. It is shipped inside the published wheel and is rebuilt automatically
by the ``webui-build`` Hatch hook during ``python -m build``. In an editable
source checkout it stays empty until you run ``cd webui && bun run build``
(or use the Vite dev server at ``cd webui && bun run dev``).
"""
