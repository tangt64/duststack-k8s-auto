# 쿠버네티스 설치

## 프로젝트 설명

앤서블 기반으로 쿠버네티스 설치를 도와주는 도구 입니다. 현재 이 도구는 CentOS/RHEL를 지원하고 있으며, 추후에 Debian/Ubuntu지원할 예정 입니다.

바로 상용환경에서 사용이 가능하도록 설치 및 구성할 수 있도록 환경을 제공해주는게 주요 프로젝트의 목적 입니다. 지원하는 기능은 아래와 같습니다.

- CentOS 7 and CentOS 8 Stream
- Debian and Ubuntu **(현재 준비중 입니다)**
- CI/CD 지원 **(현재 준비중 입니다)**
- 컨테이너 스토리지 시스템 지원 **(현재 준비중 입니다)**
- HA/Router/Helm 같은 확장 기능 지원 **(현재 준비중 입니다)**

## 알림사항

- CentOS 7/8버전에서 제일 안정적으로 설치가 지원 됩니다.

- Debian/Ubuntu는 곧 지원할 예정입니다.
  
  **아직은 개발버전 입니다** 

## 컴퓨터 사양

* **CPU:** Intel E5 or AMD Ryzen 7 3700X (Physical 8 core)
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





## 문의

다른 문의사항이 있으시면 아래로 연락 주세요! :)

**E-Mail:** <bluehelix@gmail.com>
**Name:** 최국현(Choi Gook Hyun)

## License

GNU 2라이센스
