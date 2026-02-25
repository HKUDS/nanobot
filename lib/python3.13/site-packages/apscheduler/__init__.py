import importlib.metadata as importlib_metadata
import sys

try:
    release = importlib_metadata.version("APScheduler").split("-")[0]
except importlib_metadata.PackageNotFoundError:
    release = "3.5.0"

version_info = tuple(int(x) if x.isdigit() else x for x in release.split("."))
version = __version__ = ".".join(str(x) for x in version_info[:3])
del sys, importlib_metadata
