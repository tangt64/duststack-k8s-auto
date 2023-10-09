lang en_US
keyboard us
timezone Asia/Seoul --isUtc
rootpw $2b$10$ZaD6PdAGgg4PnvztEgvZ6eSJgRy7WP9k4L8ihcwGu246xOetJjBEO --iscrypted
#platform x86, AMD64, or Intel EM64T
reboot
text
url --url=http://mirror.kakao.com/centos/8-stream/BaseOS/x86_64/os/
part biosboot --fstype=biosboot --size=1
bootloader --location=mbr --append="rhgb quiet crashkernel=auto"
zerombr
clearpart --all --initlabel
part / --fstype=xfs --size=20000
network --device=eth0 --hostname=node2.example.com --bootproto=static --ip=192.168.122.120 --netmask=255.255.255.0 --gateway=192.168.122.1 --nameserver=8.8.8.8
network --device=eth1 --hostname=node2.example.com --bootproto=static --ip=192.168.90.120 --netmask=255.255.255.0
auth --passalgo=sha512 --useshadow
selinux --enforcing
firewall --enabled --ssh
skipx
firstboot --disable
%post
cat <<EOF>> /etc/hosts
192.168.90.110 node1.example.com node2
192.168.90.120 node2.example.com node2
192.168.90.130 node3.example.com node3
192.168.90.140 node4.example.com node4
EOF
%end
%packages
@^minimal-environment
kexec-tools
%end

