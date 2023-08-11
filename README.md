쿠버네티스 설치 자동화
---

## 설명

쿠버네티스 설치 자동화 및 운영 자동화 프로젝트.

## 프로젝트 기록

1. __이제는 싱글 노드 및 멀티노드 설치 둘 다 지원 합니다.__ 
2. 사용 방법에 대해서 조만간 유튜브에 동영상 찍어서 올리도록 하겠습니다. 
3. 계속 업데이트 중 입니다. 아직 버전은 v1.0이 아닙니다. 
4. HelmChart기반으로 구성원 확장은 더 이상 지원하지 않을 예정 입니다. 
5. kube-virt 기능이 추가가 되었습니다.

  
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