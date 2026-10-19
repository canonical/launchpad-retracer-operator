# Copyright 2026 Canonical
# See LICENSE file for licensing details.

"""Unit tests for retracer service helpers."""

from pathlib import Path
from unittest.mock import patch

import requests

from retracer import RETRACER_CONFIG_LOCATION, RETRACER_CONFIG_URL, SRVDIR, Retracer


@patch.object(Retracer, "_restart_nginx")
@patch.object(Retracer, "_nginx_config")
@patch.object(Retracer, "_setup_systemd_units")
@patch.object(Retracer, "_download_crashdb")
@patch.object(Retracer, "_create_directories")
@patch.object(Retracer, "_install_scripts")
@patch.object(Retracer, "_clone_repository")
@patch.object(Retracer, "_install_packages")
def test_install_restarts_nginx(
    install_packages_mock,
    clone_repository_mock,
    install_scripts_mock,
    create_directories_mock,
    download_crashdb_mock,
    setup_systemd_units_mock,
    nginx_config_mock,
    restart_nginx_mock,
):
    retracer = Retracer()

    retracer.install(["amd64"])

    install_packages_mock.assert_called_once_with()
    clone_repository_mock.assert_called_once_with(RETRACER_CONFIG_URL, RETRACER_CONFIG_LOCATION)
    install_scripts_mock.assert_called_once_with()
    create_directories_mock.assert_called_once_with(["amd64"])
    download_crashdb_mock.assert_called_once_with()
    setup_systemd_units_mock.assert_called_once_with(["amd64"])
    nginx_config_mock.assert_called_once_with()
    restart_nginx_mock.assert_called_once_with()


@patch.object(Retracer, "_restart_nginx")
@patch.object(Retracer, "_nginx_config")
@patch.object(Retracer, "_setup_systemd_units")
@patch.object(Retracer, "_download_crashdb")
@patch.object(Retracer, "_create_directories")
@patch.object(Retracer, "_install_scripts")
@patch.object(Retracer, "_clone_repository")
@patch.object(Retracer, "_install_packages")
def test_install_continues_when_crashdb_seed_download_fails(
    install_packages_mock,
    clone_repository_mock,
    install_scripts_mock,
    create_directories_mock,
    download_crashdb_mock,
    setup_systemd_units_mock,
    nginx_config_mock,
    restart_nginx_mock,
):
    download_crashdb_mock.side_effect = requests.RequestException()
    retracer = Retracer()

    retracer.install(["amd64"])

    install_packages_mock.assert_called_once_with()
    clone_repository_mock.assert_called_once_with(RETRACER_CONFIG_URL, RETRACER_CONFIG_LOCATION)
    install_scripts_mock.assert_called_once_with()
    create_directories_mock.assert_called_once_with(["amd64"])
    download_crashdb_mock.assert_called_once_with()
    setup_systemd_units_mock.assert_called_once_with(["amd64"])
    nginx_config_mock.assert_called_once_with()
    restart_nginx_mock.assert_called_once_with()


@patch.object(Retracer, "_restart_nginx")
@patch.object(Retracer, "_update_checkout")
def test_start_restarts_nginx(update_checkout_mock, restart_nginx_mock):
    retracer = Retracer()

    retracer.start(["amd64"])

    update_checkout_mock.assert_called_once_with(RETRACER_CONFIG_LOCATION)
    restart_nginx_mock.assert_called_once_with()


def test_duplicate_db_shared_and_outside_publish_dir():
    dupcheck = Path("src/systemd/launchpad-retracer-dupcheck.service").read_text()
    wrapper = Path("src/scripts/worker-wrapper").read_text()
    db_path = str(SRVDIR / "apport_duplicates.db")
    publish_dir = str(SRVDIR / "apport-duplicates")

    assert f"-d {db_path} " in dupcheck
    assert f'"-d" "{db_path}"' in wrapper
    # crash-digger replaces the publish directory, the db must not live in it
    assert f'"--publish-db" "{publish_dir}"' in wrapper
    assert not db_path.startswith(publish_dir + "/")
