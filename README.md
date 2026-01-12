# Launchpad Retracer Operator

**Launchpad Retracer Operator** is a [charm](https://juju.is/charms-architecture) for retracing launchpad crashes.

This reposistory contains the code for the charm, the application is coming from that [repository](https://github.com/canonical/apport).

## Basic usage

Assuming you have access to a bootstrapped [Juju](https://juju.is) controller, you can deploy the charm with:

```bash
❯ juju deploy launchpad-retracer
```

Once the charm is deployed, you can check the status with Juju status:

```bash
❯ juju status
Model        Controller  Cloud/Region         Version  SLA          Timestamp
retracer       lxd         localhost/localhost  3.6.7    unsupported  13:29:50+02:00

App            Version  Status  Scale  Charm          Channel  Rev  Exposed  Message
launchpad-retracer           active      1  launchpad-retracer             0  no

Unit              Workload  Agent  Machine  Public address  Ports      Message
launchpad-retracer/0*  active    idle    1       10.142.46.109   8080/tcp, 8081/tcp
```

On first start up, the charm will install the application and install a systemd timer unit to trigger retracer updates on a regular basis.

The charm relies on having launchpad a credentials allowing to see bug reports to provided as a secret.

```
$ juju add-secret launchpad-secret lpcredentials#file=launchpad-credentials
$ juju grant-secret launchpad-secret launchpad-retracer
```

There charm has this configuration option:

`launchpad-credentials-id`, which you can set:

```bash
❯ juju config launchpad-retracer launchpad-credentials-id=secret:SECRET_ID
```

## Testing

There are unit tests which can be run directly without influence to
the system and dependencies handled by uv.

```bash
❯ make unit
```

## Contribute to Launchpad Retracer Operator

Launchpad Retracer Operator is open source and part of the Canonical family. We would love your help.

If you're interested, start with the [contribution guide](CONTRIBUTING.md).

## License and copyright

Launchpad Retracer Operator is released under the [GPL-3.0 license](LICENSE).
