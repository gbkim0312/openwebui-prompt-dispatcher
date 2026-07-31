# Open WebUI Prompt Dispatcher

Open WebUI에 예약 프롬프트를 보내고, 생성된 응답을 Telegram 또는 Nextcloud Talk으로 전달하는 Python 서비스입니다. Cron 스케줄, 프롬프트 템플릿, 모델·도구 설정, 채널 목적지는 웹 UI 또는 YAML 파일로 관리할 수 있습니다.

핵심 로직은 외부 통신 및 프레임워크와 분리한 Hexagonal Architecture로 구성되어 있습니다. 따라서 Open WebUI, 채널, 저장소, 스케줄러를 Fake Adapter로 교체해 외부 서비스 없이 테스트할 수 있습니다.

## 주요 기능

- Open WebUI Chat Completions 호출 및 Skill/Tool ID 전달
- Cron 기반 예약 실행과 중복 실행 방지
- Telegram 및 Nextcloud Talk 메시지 전달
- 채널 하나가 실패해도 나머지 채널은 계속 전송
- SQLite 실행 이력 및 채널별 결과 저장
- 웹 UI에서 Job·프롬프트·키·채널 설정 관리
- Open WebUI 모델 목록 캐시·검색·선택
- Dry Run, Fake Channel, Fake Open WebUI 등 로컬 검증 지원

## 빠른 시작: Docker

```bash
cp .env.example .env
# .env에 Open WebUI와 채널 정보를 채웁니다.
docker build -t prompt-dispatcher:local .
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

기본 빌드는 서비스 실행용 `runtime` 이미지를 만듭니다. 테스트 이미지를 명시적으로 만들 때만 `--target test`를 사용합니다.

```bash
docker build --target test -t prompt-dispatcher:test .
docker run --rm prompt-dispatcher:test
```

이미지를 다른 태그로 빌드했다면 해당 태그를 `IMAGE`에 지정합니다.

```bash
PUID=$(id -u) PGID=$(id -g) IMAGE=내가-빌드한-이미지:태그 docker compose up -d
```

기본 태그는 `prompt-dispatcher:local`입니다. 따라서 처음부터 빌드한다면 다음 조합을 사용할 수 있습니다.

```bash
docker build -t prompt-dispatcher:local .
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

Compose는 `.env`를 컨테이너 환경으로 전달하고, `jobs`, `prompts`, `data`를 호스트 디렉터리에 영속화합니다. Linux에서는 반드시 현재 호스트 사용자의 UID/GID로 실행하세요.

```bash
PUID=$(id -u) PGID=$(id -g) docker compose up -d
```

이전에 root로 실행해 `data` 안의 파일이 root 소유가 된 경우에만 아래를 한 번 실행한 뒤 다시 시작합니다.

```bash
sudo chown -R "$(id -u):$(id -g)" data jobs prompts
```

Compose 파일에는 의도적으로 `build:`가 없습니다. 먼저 로컬 이미지를 빌드해야 합니다.

```bash
make build
make up
make logs
```

관리 UI는 `http://127.0.0.1:8787/`에서 열 수 있습니다.

기본 예약 Job은 포함하지 않습니다. 웹 UI에서 새 작업을 만들거나 아래 Job 예시를 바탕으로 직접 등록하세요.

## Docker 없이 실행

Python 3.12 이상에서 가상환경을 만들고 직접 실행할 수 있습니다.

```bash
make dev
```

동일한 수동 절차는 다음과 같습니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m prompt_dispatcher serve
```

로컬 실행도 프로젝트 루트의 `.env`를 자동으로 읽습니다. Docker용 `/app/jobs`, `/app/prompts`, `/app/data` 경로는 로컬에서는 각각 `jobs`, `prompts`, `data`로 자동 전환됩니다. 종료하려면 실행 터미널에서 `Ctrl+C`를 누릅니다.

## 웹 관리 UI

웹 UI에서 다음을 관리할 수 있습니다.

- 예약 Job 생성·수정·삭제, 활성화 여부 및 Cron/시간대 설정
- 모델, Skill ID, Tool ID, 채널 목적지, 프롬프트 Markdown 편집
- Dry Run 및 Open WebUI를 건너뛴 프롬프트 확인 실행
- Open WebUI·Telegram·Nextcloud Talk 키 입력
- Open WebUI 실제 모델 목록 검색 및 선택

모델 목록은 `data/models.json`에 캐시됩니다. UI는 이 캐시를 즉시 표시하며, 모든 Job 실행 시작 시 Open WebUI의 `/api/models`와 `/api/v1/models`를 모두 조회해 중복 없이 병합합니다. 모델 선택 영역의 **모델 새로고침** 버튼으로 즉시 갱신할 수도 있습니다. 변경된 목록은 열린 UI에도 자동 반영됩니다.

`Web Search with Tavily` 툴을 선택하고 `TAVILY_API_KEY`를 설정하면, 디스패처가 Tavily 검색을 직접 실행한 뒤 검색 결과와 링크를 모델에 전달해 요약합니다. 따라서 다단계 Open WebUI 툴 호출에 의존하지 않습니다.

직접 Tavily 검색은 뉴스(`topic: news`)만 대상으로 하며 최근 7일(`time_range: week`)로 제한됩니다. 결과가 부족할 때 이전 기사를 섞지 않도록 모델에도 지시합니다.

UI에서 저장한 연결 키는 `data/management.env`에 저장됩니다. **키 저장 후 서비스를 재시작해야** 새 연결 설정이 적용됩니다. 이 파일은 Git에 포함되지 않습니다.

> 보안: 이 UI는 기본적으로 인증이 없습니다. 인터넷에 직접 공개하지 말고, 내부망에서만 사용하거나 인증 프록시(VPN, SSO, Basic Auth 등) 뒤에 두세요.

## 환경 변수

`.env.example`을 복사해 `.env`를 만듭니다. 비밀값이 있는 `.env`는 Git에 포함하지 않습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `TZ` | `Asia/Seoul` | 컨테이너 운영체제 시간대입니다. Job별 시간대는 YAML의 `schedule.timezone`이 우선합니다. |
| `LOG_LEVEL` | `INFO` | 애플리케이션 로그 레벨입니다. 현재 `INFO`, `WARNING`, `ERROR` 등을 사용할 수 있습니다. |
| `JOBS_DIRECTORY` | `/app/jobs` | `*.job.yaml` 예약 Job 파일 디렉터리입니다. 로컬 실행 시 Docker 경로는 자동 변환됩니다. |
| `PROMPTS_DIRECTORY` | `/app/prompts` | Job에서 참조하는 Markdown 프롬프트 디렉터리입니다. |
| `DATABASE_PATH` | `/app/data/dispatcher.db` | 실행 이력, 전송 결과, 중복 실행 방지에 쓰는 SQLite DB 파일입니다. |
| `HTTP_HOST` | `0.0.0.0` | 관리 API와 UI가 바인딩할 주소입니다. 로컬 전용이라면 `127.0.0.1`을 권장합니다. |
| `HTTP_PORT` | `8787` | 관리 API와 UI 포트입니다. |
| `OPENWEBUI_BASE_URL` | `http://open-webui:8080` | Open WebUI 서버 주소입니다. 끝의 `/` 없이 입력하는 것을 권장합니다. |
| `OPENWEBUI_API_KEY` | 빈 값 | Open WebUI Bearer API 키입니다. 절대 Git에 저장하지 마세요. |
| `OPENWEBUI_TIMEOUT_SECONDS` | `600` | 기본 Open WebUI 요청 제한 시간입니다. 개별 Job은 `openwebui.timeout_seconds`로 재정의합니다. |
| `OPENWEBUI_VERIFY_TLS` | `true` | HTTPS 인증서 검증 여부입니다. 운영 환경에서는 `true`를 유지하세요. |
| `TAVILY_API_KEY` | 빈 값 | `Web Search with Tavily` 선택 시 디스패처가 직접 호출할 Tavily API 키입니다. `tvly-`로 시작하는 비밀값이며 Git에 저장하지 마세요. |
| `TELEGRAM_PERSONAL_BOT_TOKEN` | 빈 값 | `target: personal` Telegram 채널의 Bot Token입니다. target이 `team-alert`라면 `TELEGRAM_TEAM_ALERT_BOT_TOKEN` 형식을 사용합니다. |
| `TELEGRAM_PERSONAL_CHAT_ID` | 빈 값 | 해당 Telegram target의 Chat ID입니다. target 별칭 규칙은 Bot Token과 같습니다. |
| `NEXTCLOUD_URL` | 빈 값 | Nextcloud 서버 기본 URL입니다. |
| `NEXTCLOUD_VERIFY_TLS` | `true` | Nextcloud HTTPS 인증서 검증 여부입니다. 운영에서는 비활성화하지 마세요. |
| `NEXTCLOUD_TALK_PERSONAL_USERNAME` | 빈 값 | `target: personal` Talk 전송용 사용자명입니다. |
| `NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD` | 빈 값 | Talk 전송용 Nextcloud 앱 비밀번호입니다. 일반 비밀번호 대신 앱 비밀번호를 사용하세요. |
| `NEXTCLOUD_TALK_PERSONAL_ROOM_TOKEN` | 빈 값 | 메시지를 보낼 Talk Room Token입니다. |
| `ENABLE_FAKE_CHANNEL` | `false` | `true`일 때 `type: fake` 채널을 활성화합니다. 테스트와 로컬 검증 전용입니다. |

`personal` 이외의 채널 target도 지원합니다. target을 대문자화하고 하이픈을 밑줄로 바꿔 변수명에 넣습니다.

```yaml
delivery:
  channels:
    - type: telegram
      target: team-alert
```

```dotenv
TELEGRAM_TEAM_ALERT_BOT_TOKEN=...
TELEGRAM_TEAM_ALERT_CHAT_ID=...
```

## Job 및 프롬프트 작성

Job 하나당 `jobs/*.job.yaml` 파일 하나를 사용하고, 긴 프롬프트는 `prompts/*.md`로 분리합니다.

```yaml
version: 1
id: morning-ai-news
name: 매일 아침 AI 뉴스
enabled: true
schedule:
  cron: "0 7 * * *"
  timezone: Asia/Seoul
openwebui:
  model: qwen3-80b-instruct
  skill_ids: [daily-news-brief]
  tool_ids: [web-search]
  timeout_seconds: 600
prompt:
  file: morning-news.md
  variables:
    language: ko
delivery:
  channels:
    - type: telegram
      target: personal
execution:
  max_instances: 1
  skip_if_previous_running: true
```

프롬프트에는 Jinja 변수를 쓸 수 있습니다.

```markdown
{{ current_date }} 기준 {{ language }} AI 뉴스를 요약한다.
예약 시각: {{ scheduled_time }}
실행 시각: {{ execution_time }}
```

기본 제공 변수는 `job_id`, `job_name`, `scheduled_time`, `execution_time`, `current_date`, `current_datetime`, `timezone`입니다.

## CLI와 Make 명령

```bash
# Job 파일 및 채널 타입 검증
python -m prompt_dispatcher validate

# Job 목록
python -m prompt_dispatcher list

# 실제 수동 실행
python -m prompt_dispatcher run <job-id>

# 모델 응답은 받되 채널에는 보내지 않음
python -m prompt_dispatcher run <job-id> --dry-run

# Open WebUI 호출 없이 렌더링된 프롬프트 확인
python -m prompt_dispatcher run <job-id> --skip-openwebui
```

자주 쓰는 Docker 명령은 `make build`, `make up`, `make down`, `make logs`, `make validate`, `make test`, `make run JOB=morning-ai-news`입니다.

## 상태 확인과 데이터

- `GET /health`: 스케줄러 상태와 로드된 Job 수를 반환합니다.
- `GET /ready`: Job 설정 오류가 없을 때 준비 상태를 반환합니다.
- `data/dispatcher.db`: 실행 및 전송 이력입니다.
- `data/models.json`: Open WebUI 모델 목록 캐시입니다.
- `data/management.env`: 웹 UI에서 저장한 키입니다.

응답 전문, 프롬프트 전문, API 키, Bot Token, Nextcloud 앱 비밀번호는 실행 이력에 저장하지 않습니다.

## 테스트와 확장

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

새 채널은 `src/prompt_dispatcher/adapters/outbound/channels/`에 `MessageChannelPort` 구현체를 추가하고, `bootstrap/container.py`에 등록하면 됩니다. Gmail, KakaoTalk, Discord도 같은 위치에 추가할 수 있습니다.
