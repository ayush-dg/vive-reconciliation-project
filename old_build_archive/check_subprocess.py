import sys, os, subprocess
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
r = subprocess.run(
    [sys.executable, '-c', 
     'import sys,os; sys.path.insert(0,"."); from src.lakehouse.connection import _using_azure_sql; print("azure_sql:", _using_azure_sql()); print("env:", bool(os.getenv("AZURE_SQL_SERVER")))'],
    cwd=os.getcwd(), capture_output=True, text=True
)
print('stdout:', r.stdout)
print('stderr:', r.stderr[:300])
