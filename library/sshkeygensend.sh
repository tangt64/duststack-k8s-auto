keyName=$2

echo $keyName

case "$1" in
  openstack)
    server=$(awk '{ print $2 }' /etc/hosts | grep -e 'node1' -e 'node2' -e 'node3' -e 'node4' )
    password=openstack
    ;;
  kubernetes)
    server=$(awk '{ print $2 }' /etc/hosts | grep -e 'master1' -e 'master2' -e 'master3' -e 'node1' -e 'node2' -e 'utility' )
    password=kubernetes
    ;;
  *)
    echo "Using: $1 {openstack|kubernetes} {rsa_key_name}"
    exit 1
esac

function sendkeys(){
  for ipadr in ${server} ; do echo $Server ${server} && sshpass -p ${password} ssh-copy-id -i $HOME/.ssh/$keyName -o PubkeyAuthentication=no -o StrictHostKeyChecking=no root@${ipadr} ; done
  for ipadr in ${server} ; do ssh-keyscan ${server} >> $HOME/.ssh/known_hosts ; done
}

function genkeys(){
  ssh-keygen -t rsa -N '' -f $HOME/.ssh/$keyName
}

if [ -f $HOME/.ssh/$2 ]; then
  echo "the file exist. passed it"
  sendkeys $2
else
  echo "make a keys and send key to hosts"
  genkeys $keyName
  sendkeys $keyName
fi
