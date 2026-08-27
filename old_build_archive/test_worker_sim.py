import sys, os, subprocess
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()

PROJECT_ROOT = os.getcwd()
VENV_PYTHON = os.path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe')

result = subprocess.run(
    [VENV_PYTHON, os.path.join('scripts', 'run_full_pipeline.py'), '--pdf', 'sample_data/KSI_Noakers_053126.pdf'],
    cwd=PROJECT_ROOT,
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace',
    timeout=60
)
print('STDOUT:')
for line in result.stdout.split('\n')[:30]:
    print(line)
