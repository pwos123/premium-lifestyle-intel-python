"""Shared runtime state for the Flask web layer."""

import logging
import os

from src.database import Database
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("app")

CONFIG = load_config()
DB_PATH = CONFIG["database"]["path"]
IMAGE_DIR = CONFIG.get("images", {}).get("cache_dir", "static/images")
OUTPUT_DIR = CONFIG.get("report", {}).get("output_dir", "output")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

db = Database(DB_PATH)
