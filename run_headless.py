import os
import runpy
import sys
from pathlib import Path
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'ECUSimulation'))
os.environ['IVNS_HEADLESS'] = '1'
(root / 'TestSimulation/logs').mkdir(exist_ok=True)
runpy.run_path(str(root / 'TestSimulation/main_lwa_preset.py'), run_name='__main__')
