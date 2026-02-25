import logging
import sys

logger = logging.getLogger("Lark")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[Lark] [%(asctime)s] [%(levelname)s] %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.WARNING)
