# Copyright 2026 Canonical
# See LICENSE file for licensing details.

"""Representation of the retracer service."""

import glob
import logging
import os
import shutil
from pathlib import Path
from subprocess import PIPE, STDOUT, CalledProcessError, run

import charms.operator_libs_linux.v1.systemd as systemd
import requests
from charmlibs import apt
from charmlibs.apt import PackageError, PackageNotFoundError

logger = logging.getLogger(__name__)

# Packages installed as part of the update process.
PACKAGES = [
    "apport-retrace",
    "git",
    "nginx-light",
    "python3-apt",
    "python3-requests",
]

RETRACER_CONFIG_LOCATION = Path("/app/config-apport")
RETRACER_CONFIG_URL = "https://git.launchpad.net/~ubuntu-archive/+git/lp-retracer-config"

SRVDIR = Path("/srv/retracers")
LP_CREDENTIALS = Path("/app/launchpad-credentials")

NGINX_SITE_CONFIG_PATH = Path("/etc/nginx/conf.d/crashdb.conf")


class Retracer:
    """Represent a retracer instance in the workload."""

    def __init__(self):
        logger.debug("Retracer class init")
        self.env = os.environ.copy()
        self.proxies = {}
        juju_http_proxy = self.env.get("JUJU_CHARM_HTTP_PROXY")
        juju_https_proxy = self.env.get("JUJU_CHARM_HTTPS_PROXY")
        if juju_http_proxy:
            logger.debug("Setting HTTP_PROXY env to %s", juju_http_proxy)
            self.env["HTTP_PROXY"] = juju_http_proxy
            self.proxies["http"] = juju_http_proxy
        if juju_https_proxy:
            logger.debug("Setting HTTPS_PROXY env to %s", juju_https_proxy)
            self.env["HTTPS_PROXY"] = juju_https_proxy
            self.proxies["https"] = juju_https_proxy

    def install(self, architectures: list[str]):
        """Install the retracer environment."""
        self._install_packages()
        self._clone_repository(RETRACER_CONFIG_URL, RETRACER_CONFIG_LOCATION)
        self._install_scripts()
        self._create_directories(architectures)
        self._download_crashdb()
        self._setup_systemd_units(architectures)
        self._nginx_config()

    def configure(self, architectures: list[str]):
        """Configure the retracer for the given architectures."""
        self._create_directories(architectures)
        self._setup_systemd_units(architectures)

    def start(self, architectures: list[str]):
        """Enable the launchpad retracer service."""
        self._update_checkout(RETRACER_CONFIG_LOCATION)
        try:
            systemd.service_restart("nginx")
            logger.debug("Nginx restarted")
        except CalledProcessError as e:
            logger.error("Failed to start systemd services: %s", e)
            raise

    def import_lpcredentials(self, lpcredentials: str):
        """Import the launchpad credentials."""
        try:
            fd = os.open(LP_CREDENTIALS, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            os.write(fd, lpcredentials.encode("utf-8"))
            os.close(fd)
            shutil.chown(LP_CREDENTIALS, "ubuntu", "ubuntu")
        except OSError as e:
            logger.debug("Error creating launchpad credentials: %s", e)
            raise

    def has_credentials(self) -> bool:
        """Check if the launchpad credentials file exists."""
        return LP_CREDENTIALS.exists()

    def _install_packages(self):
        """Install the Debian packages needed."""
        try:
            apt.update()
            logger.debug("Apt index refreshed.")
        except CalledProcessError as e:
            logger.error("Failed to update package cache: %s", e)
            raise

        for p in PACKAGES:
            try:
                apt.add_package(p)
                logger.debug("Package %s installed", p)
            except PackageNotFoundError:
                logger.error("Failed to find package %s in package cache", p)
                raise
            except PackageError as e:
                logger.error("Failed to install %s: %s", p, e)
                raise

    def _setup_systemd_units(self, architectures: list[str]):
        """Set up the systemd service and timer."""
        systemd_unit_location = Path("/etc/systemd/system")
        systemd_unit_location.mkdir(parents=True, exist_ok=True)

        systemd_proxy = ""
        for proto, proxy in self.proxies.items():
            systemd_proxy += f"\nEnvironment={proto}_proxy={proxy}"
            systemd_proxy += f"\nEnvironment={proto.upper()}_proxy={proxy}"

        # Dupcheck units
        systemd_service = Path("src/systemd/launchpad-retracer-dupcheck.service")
        service_txt = systemd_service.read_text()
        systemd_timer = Path("src/systemd/launchpad-retracer-dupcheck.timer")
        timer_txt = systemd_timer.read_text()

        (systemd_unit_location / "launchpad-retracer-dupcheck.service").write_text(
            service_txt + systemd_proxy
        )
        (systemd_unit_location / "launchpad-retracer-dupcheck.timer").write_text(timer_txt)
        systemd.service_enable("--now", "launchpad-retracer-dupcheck.timer")

        # Worker units
        worker_service_txt = Path("src/systemd/launchpad-retracer-worker@.service").read_text()
        worker_timer_txt = Path("src/systemd/launchpad-retracer-worker@.timer").read_text()

        (systemd_unit_location / "launchpad-retracer-worker@.service").write_text(
            worker_service_txt + systemd_proxy
        )
        (systemd_unit_location / "launchpad-retracer-worker@.timer").write_text(worker_timer_txt)
        systemd.daemon_reload()

        # Handle architecture changes
        active_timers = glob.glob(
            "/etc/systemd/system/timers.target.wants/launchpad-retracer-worker@*.timer"
        )
        current_archs = [t.split("@")[1].split(".")[0] for t in active_timers]

        # Enable units
        for arch in architectures:
            systemd.service_enable("--now", f"launchpad-retracer-worker@{arch}.timer")

        # Disable and clean up retired ones
        for arch in current_archs:
            if arch not in architectures:
                try:
                    systemd.service_stop(f"launchpad-retracer-worker@{arch}.timer")
                    systemd.service_stop(f"launchpad-retracer-worker@{arch}.service")
                    systemd.service_disable(f"launchpad-retracer-worker@{arch}.timer")
                    (systemd_unit_location / f"launchpad-retracer-worker@{arch}.timer").unlink(
                        missing_ok=True
                    )
                    (systemd_unit_location / f"launchpad-retracer-worker@{arch}.service").unlink(
                        missing_ok=True
                    )
                    logger.debug("Disabled and cleaned up retired worker for %s", arch)
                except Exception as e:
                    logger.warning("Failed to disable retired worker for %s: %s", arch, e)

        logger.debug("Systemd units synchronized")

    def _create_directories(self, architectures: list[str]):
        """Create the directories needed for the retracer."""
        try:
            SRVDIR.mkdir(parents=True, exist_ok=True)
            shutil.chown(SRVDIR, "ubuntu", "ubuntu")
            logger.debug("Directory %s created", SRVDIR)
        except OSError as e:
            logger.error("Setting up %s directory failed: %s", SRVDIR, e)
            raise

        publish_db_dir = SRVDIR / "apport-duplicates"
        publish_db_dir.mkdir(parents=True, exist_ok=True)
        shutil.chown(publish_db_dir, "ubuntu", "ubuntu")

        ubuntu_home = Path("/home/ubuntu")
        for arch in architectures:
            cache_dir = ubuntu_home / f"cache-{arch}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.chown(cache_dir, "ubuntu", "ubuntu")

        # Needed by apport in sandbox mode
        try:
            debugdir = Path("/usr/lib/debug/.dwz")
            debugdir.mkdir(parents=True, exist_ok=True)
            shutil.chown(debugdir, "ubuntu", "ubuntu")
            logger.debug("Directory %s created", debugdir)
        except OSError as e:
            logger.error("Setting up %s directory failed: %s", debugdir, e)
            raise

    def _install_scripts(self):
        """Install helper scripts."""
        wrapper_source = Path("src/scripts/worker-wrapper")
        wrapper_dest = Path("/app/retracer-worker-wrapper")
        try:
            shutil.copy(wrapper_source, wrapper_dest)
            os.chmod(wrapper_dest, 0o755)
            logger.debug("Worker wrapper script installed.")
        except OSError as e:
            logger.error("Failed to install worker wrapper script: %s", e)
            raise

    def _clone_repository(self, url: str, directory: str):
        """Clone a repository."""
        if Path(directory).exists():
            logger.debug("Directory %s already exists, skipping clone.", directory)
            return
        try:
            run(
                [
                    "git",
                    "clone",
                    "-b",
                    "main",
                    url,
                    directory,
                ],
                check=True,
                stdout=PIPE,
                stderr=STDOUT,
                text=True,
                env=self.env,
            )
            logger.debug("Repository %s cloned to %s.", url, directory)
        except CalledProcessError as e:
            logger.error("Git clone of the code failed: %s", e.stdout)
            raise

    def _update_checkout(self, directory: str):
        """Update a git repository checkout."""
        try:
            run(
                [
                    "git",
                    "-C",
                    directory,
                    "pull",
                ],
                check=True,
                stdout=PIPE,
                stderr=STDOUT,
                text=True,
                env=self.env,
            )
            logger.debug("%s checkout updated.", directory)

        except CalledProcessError as e:
            logger.debug("Git pull in the %s directory failed: %s", directory, e.stdout)
            raise

    def get_workload_version(self):
        """Get the workload version."""
        try:
            result = run(
                ["dpkg-query", "-W", "-f=${Version}", "apport-retrace"],
                check=True,
                stdout=PIPE,
                stderr=STDOUT,
                text=True,
                env=self.env,
            )
            workload_version = result.stdout.strip()
            logger.debug("Current 'apport-retrace' version: %s", workload_version)
            return workload_version
        except CalledProcessError as e:
            logger.warning("Failed to get 'apport-retrace' version: %s", e.stdout)
            return "unknown"

    def _download_crashdb(self):
        """Download the crashdb."""
        db_path = SRVDIR / "apport_duplicates.db"
        if db_path.exists():
            logger.debug("Crashdb %s already exists, skipping download.", db_path)
            return
        try:
            url = "https://ubuntu-archive-team.ubuntu.com/apport-duplicates/apport_duplicates.db"
            with requests.get(url, stream=True, timeout=60, proxies=self.proxies) as r:
                r.raise_for_status()

                with open(db_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            shutil.chown(db_path, "ubuntu", "ubuntu")
        except requests.RequestException as e:
            logger.error("Could not download the crashdb: %s", e)
            raise
        except OSError as e:
            logger.error("Could not write the crashdb to %s: %s", SRVDIR, e)
            raise
        except Exception:
            logger.exception("Error in download_crashdb")
            raise

    def _nginx_config(self):
        """Configure nginx."""
        try:
            shutil.copy("src/nginx/crashdb.conf", NGINX_SITE_CONFIG_PATH)
            logger.debug("Nginx config copied")
        except (OSError, shutil.Error) as e:
            logger.warning("Error copying files: %s", str(e))
            raise

        # Remove default nginx configuration
        Path("/etc/nginx/sites-enabled/default").unlink(missing_ok=True)
        logger.debug("Nginx default configuration removed")
