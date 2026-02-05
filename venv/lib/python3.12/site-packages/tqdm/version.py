"""`tqdm` version detector. Precedence: installed dist, git, 'UNKNOWN'."""
try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # py<3.8
    from importlib_metadata import PackageNotFoundError, version

try:
    __version__ = version('tqdm')
except PackageNotFoundError:
    __version__ = "UNKNOWN"
