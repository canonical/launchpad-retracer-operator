# Copyright 2026 Canonical
# See LICENSE file for licensing details.

"""Unit tests for the charm.

These tests only cover those methods that do not require internet access,
and do not attempt to manipulate the underlying machine.
"""

from subprocess import CalledProcessError
from unittest.mock import patch

import pytest
from charmlibs.apt import PackageError, PackageNotFoundError
from ops.testing import (
    ActiveStatus,
    BlockedStatus,
    Context,
    Secret,
    State,
)

from charm import LaunchpadRetracerCharm


@pytest.fixture
def ctx():
    return Context(LaunchpadRetracerCharm)


@pytest.fixture
def base_state(ctx):
    return State(leader=True)


@patch("charm.Retracer.install", autospec=True)
def test_on_install_success(install_mock, ctx, base_state):
    install_mock.return_value = True
    out = ctx.run(ctx.on.install(), base_state)
    assert out.unit_status == ActiveStatus()
    assert install_mock.called


def test_on_install_no_architectures(ctx, base_state):
    state = State(
        leader=True,
        config={"architectures": ""},
    )
    out = ctx.run(ctx.on.install(), state)
    assert out.unit_status == BlockedStatus(
        "Failed to set up the environment. Check `juju debug-log` for details."
    )


@patch("charm.Retracer.install")
@pytest.mark.parametrize(
    "exception",
    [
        PackageError,
        PackageNotFoundError,
        CalledProcessError(1, "foo"),
        OSError,
        ValueError("Config 'architectures' cannot be empty."),
    ],
)
def test_on_install_failure(install_mock, exception, ctx, base_state):
    install_mock.side_effect = exception
    out = ctx.run(ctx.on.install(), base_state)
    assert out.unit_status == BlockedStatus(
        "Failed to set up the environment. Check `juju debug-log` for details."
    )
    assert install_mock.called


@patch("charm.Retracer.get_workload_version")
@patch("charm.Retracer.has_credentials")
@patch("charm.Retracer.start")
def test_on_start_success(
    start_mock, has_credentials_mock, get_workload_version_mock, ctx, base_state
):
    start_mock.return_value = True
    get_workload_version_mock.return_value = "v1.2.3"
    has_credentials_mock.return_value = True
    out = ctx.run(ctx.on.start(), base_state)
    assert out.unit_status == ActiveStatus()
    assert out.workload_version == "v1.2.3"
    assert get_workload_version_mock.called
    assert has_credentials_mock.called
    assert start_mock.called


@patch("charm.Retracer.has_credentials")
@patch("charm.Retracer.start")
def test_on_start_failure(start_mock, has_credentials_mock, ctx, base_state):
    has_credentials_mock.return_value = True
    start_mock.side_effect = CalledProcessError(1, "foo")
    out = ctx.run(ctx.on.start(), base_state)
    assert out.unit_status == BlockedStatus(
        "Failed to start services. Check `juju debug-log` for details."
    )
    assert has_credentials_mock.called
    assert start_mock.called


@patch("charm.Retracer.has_credentials")
@patch("charm.Retracer.start")
def test_on_start_no_credentials(start_mock, has_credentials_mock, ctx, base_state):
    has_credentials_mock.return_value = False
    out = ctx.run(ctx.on.start(), base_state)
    assert out.unit_status == BlockedStatus("Launchpad credentials not available.")
    assert has_credentials_mock.called
    assert not start_mock.called


@patch("charm.Retracer.import_lpcredentials")
@patch("charm.Retracer.configure")
def test_on_config_changed_success(configure_mock, import_lpcredentials_mock, ctx, base_state):
    import_lpcredentials_mock.return_value = True
    configure_mock.return_value = True
    config_secret = Secret(tracked_content={"lpcredentials": "GPG_PRIVATE_KEY"})
    state = State(
        leader=True,
        secrets=[config_secret],
        config={"launchpad-credentials-id": config_secret.id},
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == ActiveStatus()
    assert import_lpcredentials_mock.called
    assert configure_mock.called


def test_on_config_changed_no_secret_id(ctx, base_state):
    out = ctx.run(ctx.on.config_changed(), base_state)
    assert out.unit_status == BlockedStatus("Config 'launchpad-credentials-id' required.")


def test_on_config_changed_secret_not_granted(ctx, base_state):
    config_secret = Secret(tracked_content={"lpcredentials": "GPG_PRIVATE_KEY"})
    state = State(
        leader=True,
        config={"launchpad-credentials-id": config_secret.id},
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == BlockedStatus("Secret not available. Check that access was granted.")


def test_on_config_changed_secret_not_found(ctx, base_state):
    config_secret = Secret(tracked_content={})
    state = State(
        leader=True,
        secrets=[config_secret],
        config={"launchpad-credentials-id": config_secret.id},
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == BlockedStatus(
        "Secret not available. Check that the 'lpcredentials' key exists."
    )


@patch("charm.Retracer.import_lpcredentials")
@pytest.mark.parametrize(
    "exception",
    [
        OSError,
        KeyError("lpcredentials"),
    ],
)
def test_on_config_changed_lpcredentials_import_failed(
    import_lpcredentials_mock, exception, ctx, base_state
):
    import_lpcredentials_mock.side_effect = exception
    config_secret = Secret(tracked_content={"lpcredentials": "GPG_PRIVATE_KEY"})
    state = State(
        leader=True,
        secrets=[config_secret],
        config={"launchpad-credentials-id": config_secret.id},
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == BlockedStatus(
        "Failed to import the launchpad credentials. Check `juju debug-log` for details."
    )
    assert import_lpcredentials_mock.called


@patch("charm.Retracer.import_lpcredentials")
@patch("charm.Retracer.configure")
@pytest.mark.parametrize(
    "exception",
    [
        CalledProcessError(1, "foo"),
        OSError,
        ValueError("Config 'architectures' cannot be empty."),
    ],
)
def test_on_config_changed_configure_failed(
    configure_mock, import_lpcredentials_mock, exception, ctx, base_state
):
    import_lpcredentials_mock.return_value = True
    configure_mock.side_effect = exception

    config_secret = Secret(tracked_content={"lpcredentials": "GPG_PRIVATE_KEY"})
    state = State(
        leader=True,
        secrets=[config_secret],
        config={"launchpad-credentials-id": config_secret.id},
    )
    out = ctx.run(ctx.on.config_changed(), state)
    assert out.unit_status == BlockedStatus(
        "Failed to configure the retracer. Check `juju debug-log` for details."
    )
    assert import_lpcredentials_mock.called
    assert configure_mock.called
