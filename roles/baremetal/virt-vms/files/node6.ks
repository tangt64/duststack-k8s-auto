#platform=x86, AMD64, or Intel EM64T
#version=DEVEL
# Install OS instead of upgrade
install
# Keyboard layouts
keyboard 'us'
# Root password
rootpw --iscrypted $1$vZhANTdH$a5juvIOCLLNWs2Xc2UU3v1
# Use network installation
repo --name="AppStream" --baseurl="http://mirror.kakao.com/centos/8-stream/"
# System language
lang en_US
# System authorization information
auth  --useshadow  --passalgo=sha512
# Use text mode install
text
firstboot --disable
# SELinux configuration
selinux --disabled
# Do not configure the X Window System
skipx

# Firewall configuration
firewall --disabled
# Network information
network  --bootproto=static --device=eth0 --gateway=192.168.122.1 --ip=192.168.122.140 --nameserver=8.8.8.8 --netmask=255.255.255.0 --hostname=node6.example.com
network  --bootproto=static --device=eth1 --ip=192.168.90.140 --netmask=255.255.255.0 --nodefroute
# Reboot after installation
reboot
# System timezone
timezone Asia/Seoul
# System bootloader configuration
bootloader --location=mbr
# Clear the Master Boot Record
zerombr
# Partition clearing information
clearpart --all
# Disk partitioning information
part / --fstype="xfs" --size=20000

%post
hostnamectl set-hostname storage1.example.com

cat <<EOF>> /etc/hosts
192.168.90.110 node1.example.com node1
192.168.90.120 node2.example.com node2
192.168.90.130 node3.example.com node3
192.168.90.140 node4.example.com node4
EOF
%end
