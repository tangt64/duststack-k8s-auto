#platform=x86, AMD64, or Intel EM64T
#version=DEVEL
# Install OS instead of upgrade
install
# Keyboard layouts
keyboard 'us'
# Root password
rootpw --iscrypted $6$AvdjZxuqmPqE0Kqe$ATNI9NVyRF/o4b9OfNGFjxB8zRBqE46G0khMOxxemf/7Cz./7jM5EccXf1fJ9H0UsNwdKQoQL1skkqIMjnTlu1
# Use network installation
url --url="http://mirror.kakao.com/centos/7/os/x86_64/"
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
network  --bootproto=static --device=eth0 --gateway=192.168.122.1 --ip=192.168.122.220 --nameserver=8.8.8.8 --netmask=255.255.255.0 --hostname=master2.example.com
network  --bootproto=static --device=eth1 --ip=192.168.90.220 --netmask=255.255.255.0 --nodefroute --nameserver=192.168.122.200
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
hostnamectl set-hostname master2.example.com

cat <<EOF>> /etc/hosts
192.168.90.210 master1.example.com master1
192.168.90.220 master2.example.com master2
192.168.90.230 master3.example.com master3
192.168.90.240 node1.example.com node1
192.168.90.250 node2.example.com node2
192.168.90.200 utility.example.com utility
EOF

cat <<EOF> /root/.vimrc
au! BufNewFile,BufReadPost *.{yaml,yml} set filetype=yaml foldmethod=indent
autocmd FileType yaml setlocal ts=2 sts=2 sw=2 expandtab
EOF

yum install vim nfs-utils -y

systemctl enable firewalld
%end
