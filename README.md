# 쿠버네티스 설치

## 프로젝트 설명

앤서블 기반으로 쿠버네티스 설치를 도와주는 도구 입니다. 현재 이 도구는 CentOS/RHEL를 지원하고 있으며, 추후에 Debian/Ubuntu지원할 예정 입니다.

바로 상용환경에서 사용이 가능하도록 설치 및 구성할 수 있도록 환경을 제공해주는게 주요 프로젝트의 목적 입니다. 지원하는 기능은 아래와 같습니다.

- CentOS 7, CentOS 8 Stream, Ubuntu, Debian 
- 컨테이너 스토리지 시스템 지원
- High Availability/Ingress/Helm Chart  확장 기능 지원
- OVN and OVS 지원

## 알림사항

- CentOS 7/8버전에서 제일 안정적으로 설치가 지원 됩니다.
- Debian/Ubuntu는 곧 지원할 예정입니다.
- 업데이트 기능 추가 예정
- 노드 스케일링(master, worker)추가 예정
  
## 컴퓨터 사양

* **CPU:** Intel E5 or AMD Ryzen 5 5600X (Physical 6 core)
* **Memory:** Minimun 8 GiB
* **Disk:** least 500GiB HDD or SSD 1TiB Recommend
* **NIC:** least 1GiB 

이 환경은 가상 및 물리적 환경 설치를 지원 합니다.

## 가상머신에 설치하는 방법

### 가상머신 구성

가상머신을 생성하려면 다음과 같은 명령어로 실행 합니다.

```bash
# ansible-playbook -i inventory/classroom playbooks/classroom.yaml
```

위의 명령어를 실행하면, 한대의 master와 3대의 node가 구성이 됩니다. 멀티 컨트롤노드가 필요한 경우에는 아래처럼 변경 합니다.

쿠버네티스 설치시 다음과 같은 명령어로 실행 합니다.

```bash
# ansible-playbook -i inventory/kubernetes playbooks/k8s-install.yaml
```

## 배포판 지원
리눅스 배포판은 RHEL, CentOS, Debian, Ubuntu를 지원합니다. 
배포판 변수는 "group_vars/all/kubernetes"에서 distribution_name 값을 변경 합니다.


## 스토리지 구성
유틸리티 노드가 구성이 되어 있는 경우, 유틸리티 노드에 기본적으로 NFS 스토리지 서버를 구성 합니다.
NFS스토리는 유틸리티 서버에 /srv/nfs-k8s의 디렉터리를 엑스포팅 합니다.

## master loadablancer mode 

## registry server 



## 문의

다른 문의사항이 있으시면 아래로 연락 주세요! :)

**E-Mail:** <bluehelix@gmail.com>
**Name:** 최국현(Choi Gook Hyun)

## License

GNU 2라이센스
