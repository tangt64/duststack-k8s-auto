# Ansible Playbook: duststack

## Describe of Project

This Playbook builds for OpenStack/oVirt/Kubernetes Hybrid project playbook. You can use it as want as you can.

** The provisioning problem has been solved. :) **
** This playbook would not support a container mode. **

## Announcement

- **The placement** has a little problem. It will correct in future. **The Nova service** still useable it.
- Kubernetes will be installed based on **CRI-O** container runtime.
- The Playbook still working and building by someone.
- The OpenStack version on **rocky**. But, I will support another OpenStack version.
- The playbook commit will be late because I am super busy and lazy also too.

## FAQ

### Why the playbook update not often?

> Busy and Busy. 

### What is the difference between OpenStack Ansible and Duststack?

> Offical vs UnOffical

### Is Support other distribution?

> Yes, It will support such as Debian and Slackware

### What for this playbook propose?

> Intergration for OpenStack or oVIrt with Kubernetes

## Specification

* **CPU:** Intel E5 or AMD Ryzen 7 3700X (Physical 8 core)
* **Memory:** Minimun 8 GiB
* **Disk:** least 500GiB HDD or SSD 1TiB Recommend
* **NIC:** least 1GiB 

This Playbook can use on bare-metal machines or Virtual Machines as you want.

## How can do install the LAB

### Build a vLAB enviroment

If you wanna do build a OpenStack Lab, Use this command. 

```bash
# ansible-playbook -i inventory/classroom -e lab=openstack playbooks/classroom.yaml
```

If you wanna do build a Kubernetes Lab, Use this command.

```bash
# ansible-playbook -i inventory/classroom -e lab=kubernetes playbooks/classroom.yaml
# library/sshkeygensend.sh
```

If you want to make a SSH private/public key, use the this a shell script.

```bash
librar/sshkeygensend.sh [ openstack | kubernetes ]
```

### Prepare for install

You should install these are packages on your baremetal machine

```bash
# yum install ansible git -y
# yum group install "Virtualization Host" -y
# git clone http://git.howtodothat.kr/tang/duststack
```

Run the playbook for OpenStack or Kubernetes

```bash
# ansible-playbook -i inventory/openstack playbooks/openstack.yaml
# ansiple-playbook -i inventory/kubernetes playbooks/kubernetes.yaml
```

## openstack/kubernetes install video

[![kubernetes install video]()](https://youtu.be/cZyi61Oncrg)

The **group_vars** has two directories. The **classroom** directory use for LAB. Another group_var **all** directory has the OpenStack and kubernetes.

## Contact

If you have question please send a mail

**E-Mail:** <gochoi@redhat.com>
**Name:** 최국현(Choi Gook Hyun)

## License

MIT 라이센스
[MIT](LICENSE)
