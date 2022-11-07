.PHONY: default
default: help ;
PATH  := $(PWD)/.venv/bin:$(PATH)
SHELL := /bin/bash

.config.env:
	echo "export BIND=$${BIND:-0.0.0.0}" > .config.env
	echo "export PORT=$${PORT:-8999}" >> .config.env
	echo "export WHOAMI=`whoami`" >> .config.env
	chmod +x .config.env

checks:
	@if [ "`docker --version | cut -d " " -f3 | tr -d 'v'| cut -c1`" -lt 2 ]; \
		then echo "docker version is too old"; exit 1; fi
	@if [ "`docker compose version | cut -d " " -f4 | tr -d 'v'| cut -c1`" -lt 2 ]; \
		then echo "docker compose version is too old"; exit 1; fi

latest: checks
	docker pull ghcr.io/azulinho/klines_caching_service:latest

build: checks
	$(PREFIX_VARS) docker compose build


.ONESHELL:
up: checks .config.env
	@set -e
	@source .config.env >/dev/null
	@echo "LISTENING on $$BIND:$$PORT"
	U=`id -u` G=`id -g` BIND=$$BIND PORT=$$PORT WHOAMI=`whoami` docker compose up -d

.ONESHELL:
down: checks
	U=`id -u` G=`id -g` BIND=$$BIND PORT=$$PORT WHOAMI=`whoami` docker compose down

.venv:
	python -m venv .venv

.ONESHELL:
pip_packages: .venv
	source .venv/bin/activate
	pip install wheel
	pip install -r requirements.txt
	pip install -r ../requirements-dev.txt

.ONESHELL:
pre-commit-checks: pip_packages
	set -e
	source .venv/bin/activate
	black --check klines_caching_service.py
	black --check tests/
	# pylint
	pylint klines_caching_service.py
	# mypy
	mypy klines_caching_service.py
	# pytests
	pytest tests/

tests: pre-commit-checks

help:
	@echo "USAGE:"
	@echo "BIND=0.0.0.0 PORT=8999 make klines_caching_service"
