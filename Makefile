PYTHON ?= python3

.PHONY: run test check build install-user uninstall-user clean

run:
	./scripts/run.sh

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) -m py_compile src/app.py src/metrics.py src/check_runtime.py scripts/build_release.py
	$(PYTHON) -m unittest discover -s tests -v

build:
	$(PYTHON) scripts/build_release.py

install-user:
	./scripts/install-user.sh

uninstall-user:
	./scripts/uninstall-user.sh

clean:
	rm -rf build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
