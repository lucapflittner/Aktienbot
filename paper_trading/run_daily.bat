@echo off
cd /d "G:\Programmierzeugs\Aktienbot"
"C:\Users\lucap\anaconda3\envs\tf-gpu\python.exe" -m paper_trading.run_daily >> paper_trading\run_daily.log 2>&1
