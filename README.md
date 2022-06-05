# 쿠버네티스 설치



## 프로젝트 설명

**현재 이 브렌치는 싱글 마스터 노드 입니다. **

앤서블 기반으로 쿠버네티스 설치를 도와주는 도구 입니다. 현재 이 도구는 CentOS/RHEL를 지원하고 있습니다.
멀티 노드 및 Debian/Ubuntu에서 설치를 원하는 경우 multi-master branch를 사용하세요.

싱글노드는 간단하게 테스트 용도 및 학습 용도로 만들었습니다. 실무용은 multi-master로 사용하세요.


## 알림사항

- CentOS 7/8버전에서 제일 안정적으로 설치가 지원 됩니다.
- 추가 기능은 멀티 노드 브렌치에서 다운로드 받으세요. 
  
## 컴퓨터 사양

* **CPU:** Intel E5 or AMD Ryzen 5 5600X (Physical 6 core)
* **Memory:** Minimun 8 GiB
* **Disk:** least 500GiB HDD or SSD 1TiB Recommend
* **NIC:** least 1GiB 

리눅스 기반으로 구성하시는 경우, libvirt기반으로 가상머신 구성이 가능 합니다. 

## 가상머신에 설치하는 방법

### 가상머신 구성

가상머신을 생성하려면 다음과 같은 명령어로 실행 합니다.

```bash
# ansible-playbook playbooks/classroom.yaml
```

위의 명령어를 실행하면, 한대의 master와 3대의 node가 구성이 됩니다. 멀티 컨트롤노드가 필요한 경우에는 아래처럼 변경 합니다.

쿠버네티스 설치시 다음과 같은 명령어로 실행 합니다.

```bash
# ansible-playbook playbooks/k8s-install.yaml
``
ㅡ 
## 문의

다른 문의사항이 있으시면 아래로 연락 주세요! :)

**E-Mail:** <bluehelix@gmail.com>
**Name:** 최국현(Choi Gook Hyun)

## License

GNU 2라이센스
