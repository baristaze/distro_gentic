# The cloud pool's VMs

A session of the platform's cloud whose workspace is a VM runs on a
VM of its own: the cloud pool starts one per session, runs the
workspace host ([apps/host/](../../apps/host/README.md)) inside it, and
lets it go when the session is done with it
([ADR 2052](../../docs/adr/2052-the-cloud-pool-runs-a-VM-per-session-whose-host-pulls-its-work.md)).
The files here make the image every such VM starts from.

## What a VM holds

- **The host program**, installed by [`install.sh`](install.sh) under
  `/opt/acme-host`, run by its unit as the user `acme-host`, in Docker's
  group, so its session's commands build and run containers.
- **Its settings**, [`host.env`](host.env), which name where its seed and
  its home are, and nothing secret.
- **Its ceilings**, [`ceilings.toml`](ceilings.toml): the VM is its
  session's wall, so the host holds no ceiling of its own beyond it.
- **Its seed**, on `/run/acme-vm/seed.json`, which the pool hands
  each VM as it starts: where the platform answers, and a one-use key
  the host trades for its credential. On Lima the pool writes it through
  the hypervisor's channel; in the cloud it is the instance's first-boot
  data, which [`acme-vm-seed`](acme-vm-seed) reads at each boot.
- **Its home**, on `/run/acme-host`: its credential lives in memory, so
  the disk the pool snapshots holds none.

No database login, no model key, no credential of the platform's, and no
instance role.

## Building the image

On Lima, from the repository's root, with a hypervisor:

```bash
make VM-image NAME=acme-vm-image
```

It starts a VM from the Lima template `ACME_VM_IMAGE` names,
copies this checkout in, runs `install.sh` there, stops the VM, and
keeps it under the name given. Set `ACME_CLOUD_POOL_IMAGE` to that name,
`ACME_VMS_BACKEND=lima`, and `ACME_CLOUD_POOL_API_URL` to where the
API answers from inside a guest, such as `http://host.lima.internal:8000`.
The name must not start with `ACME_VM_PREFIX` and a `p`: those are
the pool's own VMs.

In the cloud, the image is an AMI made the same way: an instance of a
Linux whose packages hold Docker, `install.sh` run in it, then an image
made of it. The [cloud pool's module](../terraform/modules/cloud_pool/)
takes its id as `image_id`, and maps its root device in the launch
template, encrypted under the pool's key. Set `ACME_CLOUD_POOL_IMAGE` to
the same id, `ami-` and its hex: a new VM boots the image by it.
