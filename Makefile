.PHONY: run web test test-v kill

run:
	python bot.py

web:
	uvicorn main:app --reload --port 8000

test:
	python -m pytest tests/

test-v:
	python -m pytest tests/ -v

kill:
	powershell -Command "Get-WmiObject Win32_Process | Where-Object {$$_.Name -eq 'python.exe' -and $$_.CommandLine -like '*bot.py*'} | ForEach-Object { $$_.Terminate() }"
	powershell -Command "Get-WmiObject Win32_Process | Where-Object {$$_.Name -eq 'python.exe' -and $$_.CommandLine -like '*uvicorn*'} | ForEach-Object { $$_.Terminate() }"
