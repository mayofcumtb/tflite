.PHONY: all pip_install_user pip_install_venv
.PHONY: run_tests

all:
	@ echo "tensorflow quantize module"

pip_install_user:
	@ pip install --upgrade --no-deps --force-reinstall --user .
	@ echo 'may needed to export PATH=$$PATH:$$HOME/.local/bin'

pip_install_venv:
	@ pip install --upgrade --no-deps --force-reinstall .

run_tests:
	@ cd tests && python2 -m unittest discover -p "*_tests.py"
