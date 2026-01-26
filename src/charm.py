#!/usr/bin/env python3
# Copyright 2026 Canonical
# See LICENSE file for licensing details.

"""Charmed Operator for launchpad retracers."""

import logging
import shutil
from subprocess import CalledProcessError

import ops
from charmlibs.apt import PackageError, PackageNotFoundError
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer as IngressRequirer
from ops.model import Secret

from retracer import Retracer

logger = logging.getLogger(__name__)

INGRESS_PORT = 80


class LaunchpadRetracerCharm(ops.CharmBase):
    """Charmed Operator for Launchpad Retracers."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.ingress = IngressRequirer(
            self, port=INGRESS_PORT, strip_prefix=True, relation_name="ingress"
        )

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.upgrade_charm, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        # Ingress URL changes require updating the configuration and also regenerating sitemaps,
        # therefore we can bind events for this relation to the config_changed event.
        self.framework.observe(self.ingress.on.ready, self._on_config_changed)
        self.framework.observe(self.ingress.on.revoked, self._on_config_changed)

        self._retracer = Retracer()

    def _on_install(self, event: ops.EventBase):
        """Handle install, upgrade, config-changed, or ingress events."""
        self.unit.status = ops.MaintenanceStatus("Setting up environment")
        try:
            architectures = self._get_architectures()
            self._retracer.install(architectures)
        except (
            CalledProcessError,
            PackageError,
            PackageNotFoundError,
            OSError,
            shutil.Error,
            ValueError,
        ):
            self.unit.status = ops.BlockedStatus(
                "Failed to set up the environment. Check `juju debug-log` for details."
            )
            return
        self.unit.status = ops.ActiveStatus()

    def _on_start(self, event: ops.StartEvent):
        """Start the retracer service."""
        self.unit.status = ops.MaintenanceStatus("Starting retracer service")
        try:
            # Get the apport commit id as workload version
            apportversion = self._retracer.get_workload_version()
            self.unit.set_workload_version(apportversion)

            if not self._retracer.has_credentials():
                self.unit.status = ops.BlockedStatus("Launchpad credentials not available.")
                return

            architectures = self._get_architectures()
            self._retracer.start(architectures)
            self.unit.status = ops.ActiveStatus()
        except (CalledProcessError, ValueError):
            self.unit.status = ops.BlockedStatus(
                "Failed to start services. Check `juju debug-log` for details."
            )
            return

    def _on_config_changed(self, event):
        """Update configuration."""
        self.unit.status = ops.MaintenanceStatus("Importing launchpad credentials")

        try:
            secret_id = self.config["launchpad-credentials-id"]
        except KeyError:
            logger.warning("No 'launchpad-credentials-id' config")
            self.unit.status = ops.BlockedStatus("Config 'launchpad-credentials-id' required.")
            return

        try:
            launchpad_secret: Secret = self.model.get_secret(id=secret_id)
        except (ops.SecretNotFoundError, ops.model.ModelError, TypeError):
            logger.warning("Error getting secret")
            self.unit.status = ops.BlockedStatus(
                "Secret not available. Check that access was granted."
            )
            return

        lpcredentials = launchpad_secret.get_content(refresh=True).get("lpcredentials")
        if not lpcredentials:
            logger.warning("Launchpad credentials secret not found")
            self.unit.status = ops.BlockedStatus(
                "Secret not available. Check that the 'lpcredentials' key exists."
            )
            return

        try:
            self._retracer.import_lpcredentials(lpcredentials)
            logger.debug("Launchpad credentials imported")
        except (OSError, KeyError):
            self.unit.status = ops.BlockedStatus(
                "Failed to import the launchpad credentials. Check `juju debug-log` for details."
            )
            return

        try:
            architectures = self._get_architectures()
            self._retracer.configure(architectures)
        except (CalledProcessError, OSError, ValueError):
            self.unit.status = ops.BlockedStatus(
                "Failed to configure the retracer. Check `juju debug-log` for details."
            )
            return

        self.unit.status = ops.ActiveStatus()

    def _get_architectures(self) -> list[str]:
        """Get and validate the architectures configuration."""
        architectures = self.config["architectures"].split()
        if not architectures:
            raise ValueError("Config 'architectures' cannot be empty.")
        return architectures


if __name__ == "__main__":  # pragma: nocover
    ops.main(LaunchpadRetracerCharm)
