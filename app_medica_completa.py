from pathlib import Path
import runpy
import sys


APP_DIR = Path(__file__).resolve().parent / "max30102"
APP_FILE = APP_DIR / "app_medica_completa.py"

sys.path.insert(0, str(APP_DIR))
runpy.run_path(str(APP_FILE), run_name="__main__")
