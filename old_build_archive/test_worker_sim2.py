import sys, os, subprocess
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()

PROJECT_ROOT = os.getcwd()
VENV_PYTHON = os.path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe')

# Simulate worker exactly — same pdf_path format as stored in jobs table
pdf_path = os.path.join(PROJECT_ROOT, 'sample_data', 'KSI Noakers 053126.pdf')
relative_pdf_path = os.path.relpath(pdf_path, PROJECT_ROOT)
print('relative_pdf_path:', relative_pdf_path)

result = subprocess.run(
    [VENV_PYTHON, os.path.join('scripts', 'run_full_pipeline.py'), '--pdf', relative_pdf_path],
    cwd=PROJECT_ROOT,
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace',
    timeout=600
)
lines = (result.stdout + result.stderr).split('\n')
for line in lines[:40]:
    print(line)
