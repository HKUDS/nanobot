.PHONY: help install uninstall install-cron uninstall-cron show-cron diff-cron test

help:
	@echo "Targets:"
	@echo "  install         Install nanobot host-side automation (currently: cron jobs)"
	@echo "  uninstall       Remove nanobot host-side automation"
	@echo "  install-cron    Install/refresh the nanobot crontab block (idempotent)"
	@echo "  uninstall-cron  Remove the nanobot crontab block"
	@echo "  show-cron       Show the currently installed nanobot crontab block"
	@echo "  diff-cron       Show what install-cron would change vs current crontab"
	@echo "  test            Run the test suite (skips matrix channel)"

install: install-cron

uninstall: uninstall-cron

install-cron:
	@scripts/install-cron.sh install

uninstall-cron:
	@scripts/install-cron.sh uninstall

show-cron:
	@scripts/install-cron.sh show

diff-cron:
	@scripts/install-cron.sh diff

test:
	@uv run pytest tests/ --ignore=tests/test_matrix_channel.py
