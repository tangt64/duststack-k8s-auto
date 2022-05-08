keyName=$2
PassName=$3

echo $keyName
echo $PassName

case "$1" in
  k8s)
    server=$(awk '{ print $2 }' /etc/hosts | grep -e 'master' -e 'node1' -e 'node2' )
    password=${PassName}
    ;;
  *)
    echo "Using: k8s {rsa_key_name} {password}"
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
