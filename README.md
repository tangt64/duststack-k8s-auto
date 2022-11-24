# 쿠버네티스 설치


## 프로젝트 설명

__이제는 싱글 노드 및 멀티노드 설치 둘 다 지원 합니다.__ :D

사용 방법에 대해서 조만간 유튜브에 동영상 찍어서 올리도록 하겠습니다.

계속 업데이트 중 입니다. 아직 버전은 v1.0이 아닙니다.

## 간단한 Q/A

자주 받은 메일 내용 정리해서 올려 드립니다.

__->왜 파일에 코멘트가 없어요?__
-> 귀찮아서...그냥 안적고 있어요. v1.0릴리즈 하면, 코멘트 꼬박꼬박 메모하겠습니다.

__->더 이상 rebase는 없나요?__
-> 네, 단일/다중 마스터 노드를 하나의 플레이북으로 통합이 완료가 되었습니다. 더 이상은 없을 듯 합니다.

__->유튜브 왜 자주 안올려주시나요?__
-> ㅈ...죄...죄송합니다..

## 설정 방법

설정은 플레이북 다운로드 하신 다음에 아래처럼 선택하시면 됩니다. 
멀티노드는 아래와 같이 설정 해주세요.

![설정파일](images/kubernetes-config-multi.jpg "기본 멀티노드 설정")


싱글모드는 다음과 같이 설정 해주세요.

![설정파일](images/kubernetes-config-single.jpg "기본 싱글노드 설정")

더 이상 **INI**형식의 인벤토리를 사용하지 않습니다. 레드햇에서는 **YAML**기반으로 작성을 권장하고 있습니다.

## 알림사항

- CentOS 7 그리고 CentOS-Stream-8/9버전에서 제일 안정적으로 설치가 지원 됩니다.
- Rocky Linux도 지원 합니다.
  
## 컴퓨터 사양

* **CPU:** Intel E5 or AMD Ryzen 5 5600X (Physically 4~6 cores)
* **Memory:** Minimun 8 GiB
* **Disk:** least 500GiB HDD or SSD 1TiB Recommend
* **NIC:** least 1GiB Bandwidth

리눅스 기반으로 구성하시는 경우, libvirt기반으로 가상머신 구성이 가능 합니다. 

**리눅스 기반**으로 설치를 매우 권장해드립니다. (:D)

## 가상머신에 설치하는 방법

### 가상머신 구성

#### 리눅스

가상머신을 생성하려면 다음과 같은 명령어로 실행 합니다.

```bash
# ansible-playbook playbooks/classroom.yaml
```

위의 명령어를 실행하면, 한대의 master와 3대의 node가 구성이 됩니다. 멀티 컨트롤노드가 필요한 경우에는 아래처럼 변경 합니다.

쿠버네티스 설치시 다음과 같은 명령어로 실행 합니다.

```bash
# ansible-playbook playbooks/k8s-install.yaml
```

혹은,

```
# deploy_k8s.sh
```

제거는 다음과 같은 명령어로 가능합니다.

```bash
# remove_k8s.sh
```

#### 윈도우

윈도우는 다음과 같은 소프트웨어를 사용을 권장 합니다.

- VMware Workstation Player
- VMware Workstation Fuse
- VirtualBox
- Hyper-V

사용은 가급적이면 "하이퍼-브이"를 매우 권장 합니다. 다른 소프트웨어는 "CPU"버그로 올바르게 동작이 안될수 도 있습니다. 특히 AMD계열은 **VirtualBox**를 권장하지 않습니다.

추후에 Hyper-V Server에서 자동설치를 앤서블로 지원할 예정 입니다.

## License
GNU 2 라이센스