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

즉시 전송과 예약 작업 화면에서 **웹 검색 사용**을 켤 수 있습니다. 기간은 오늘·최근 24시간, 최근 7일, 최근 1개월, 최근 1년 중 선택합니다. **검색어**를 비우면 전체 프롬프트로 검색하고, 값을 입력하면 그 짧은 검색어만 Tavily에 전달한 뒤 원래의 전체 프롬프트로 결과를 요약합니다.

검색 고급 설정에서는 주제(뉴스·일반·금융), 검색 깊이, 결과 수(1~20), 포함 도메인, 제외 도메인을 설정할 수 있습니다. 기본값은 뉴스·기본 깊이·8개 결과이며, 고급 깊이는 Tavily API 크레딧을 더 사용합니다.

### 리서치 데이터 소스: 날씨 API

리서치 카드에서 기본으로 작성하는 것은 **리서치 프롬프트**입니다. 필요한 자료 수집 방식만 선택하면 해당 설정이 펼쳐집니다.

- **웹 검색(Tavily)**: 검색어, 기간, 주제, 검색 깊이, 결과 수, 도메인, 원문 콘텐츠 포함 여부를 설정합니다.
- **날씨 API**: 설정 화면에서 선택한 Open-Meteo 또는 기상청 엔진으로 위치·좌표·시간대·예보 일수를 조회합니다.

서울은 자치구까지 바로 선택할 수 있습니다. 다른 지역은 연결 설정에 카카오 REST API 키를 저장한 뒤 `전국 지역 검색`에서 주소나 장소를 검색해 선택할 수 있습니다.

연결 설정의 **날씨 엔진**에서 제공자를 고릅니다. Open-Meteo는 API 키가 필요 없고, 기상청 엔진은 공공데이터포털의 `기상청_단기예보 조회서비스` 서비스 키가 필요합니다. 기상청 엔진은 초단기실황과 단기예보를 사용하므로 국내 현재 실황·강수확률 확인에 적합합니다. 설정 화면의 **서울 날씨 연결 테스트**로 키와 엔진을 바로 확인할 수 있습니다.

기상청 엔진에서는 리서치별로 **기상특보 포함**, **주간 예보 포함**도 선택할 수 있습니다. 특보는 `기상특보 조회서비스`, 주간(중기) 예보는 `중기예보 조회서비스`를 추가로 활용 신청해야 합니다. 특보·중기예보 권한이 없거나 발표 자료가 없으면 해당 항목만 조회 실패로 표시되고 나머지 날씨 데이터는 계속 전달됩니다.

둘 중 하나 또는 둘 다를 선택할 수 있습니다. 날씨 API만 선택한 리서치는 검색어 없이 실행되며, 구조화된 날씨 데이터를 리서치 프롬프트 또는 원본 전달 방식으로 최상위 작업에 넘깁니다. 최상위 프롬프트에는 해당 결과를 `{{ research.리서치ID }}` 또는 `{{ research_context }}`로 넣으세요.

**하위 LLM 프롬프트 실행**을 끄면 모델을 호출하지 않습니다. 선택한 Tavily 검색 결과와 날씨 API 결과가 원문 형태로 바로 최상위 프롬프트에 전달됩니다.

YAML로 작성할 때는 리서치 작업에 날씨 데이터를 넣습니다.

```yaml
research:
  tasks:
    - id: seoul_weather
      name: 오늘 서울 날씨
      use_web_search: false
      summary_prompt: 제공된 날씨 데이터만 사용해 서울 날씨를 요약하세요.
      weather_sources:
        - id: seoul
          name: 서울
          latitude: 37.5665
          longitude: 126.9780
          timezone: Asia/Seoul
          include_current: true
          include_daily: true
          forecast_days: 3
          include_alerts: true
          include_weekly: true
```

### 상위 작업: 여러 리서치 요약을 하나의 메시지로 합치기

예약 작업 편집 화면의 **상위 작업: 리서치 작업**에는 JSON 배열로 여러 검색 작업을 등록할 수 있습니다. 각 작업은 `Tavily 검색 → 모델 요약`을 독립적으로 수행하고, 모든 요약이 끝난 뒤 최종 프롬프트를 한 번 실행해 채널에는 하나의 메시지만 전송합니다.

```json
[
  {"id":"politics","name":"정치","query":"오늘 주요 정치 뉴스","time_range":"day","topic":"news","max_results":5},
  {"id":"economy","name":"경제","query":"오늘 주요 경제 뉴스","time_range":"day","topic":"news","max_results":5}
]
```

최종 프롬프트에서는 개별 결과를 `{{ research.politics }}`처럼, 모든 결과를 합친 문서는 `{{ research_context }}`처럼 참조합니다. 리서치 ID에 하이픈이 있다면 `{{ research['mobility-ai'] }}` 표기를 사용하세요. `query`와 `summary_prompt`에는 기존 Jinja 변수도 사용할 수 있습니다.

UI에서 저장한 연결 키는 `data/management.env`에 저장되며, 저장 즉시 실행 중인 Open WebUI·채널·검색·날씨 클라이언트와 예약 스케줄에 반영됩니다. 이 파일은 Git에 포함되지 않습니다.

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
| `WEATHER_ENGINE` | `open_meteo` | 날씨 데이터 제공자입니다. `open_meteo` 또는 `kma`를 사용합니다. UI에서 저장한 값이 우선 적용됩니다. |
| `KMA_SERVICE_KEY` | 빈 값 | `WEATHER_ENGINE=kma`일 때 필요한 공공데이터포털 기상청 단기예보 조회서비스의 **일반 인증키**입니다. Encoding·Decoding 형태 모두 사용할 수 있으며, 민감값이므로 Git에 저장하지 마세요. |
| `KMA_ALERT_SERVICE_KEY` | 빈 값 | 기상특보 조회서비스 전용 일반 인증키입니다. 비우면 `KMA_SERVICE_KEY`를 사용합니다. |
| `KMA_MID_SERVICE_KEY` | 빈 값 | 중기예보 조회서비스 전용 일반 인증키입니다. 비우면 `KMA_SERVICE_KEY`를 사용합니다. |
| `KAKAO_REST_API_KEY` | 빈 값 | 전국 지역 검색에 사용하는 카카오 Developers REST API 키입니다. 비워두면 서울 자치구 선택과 직접 좌표 입력은 계속 사용할 수 있지만, 전국 주소·장소 검색은 사용할 수 없습니다. |
| `EXECUTION_RETENTION_DAYS` | `30` | 실행 이력과 최종 응답을 DB에 보관할 일수입니다. 기간이 지난 기록과 전송 이력은 다음 작업 실행 시 자동 삭제됩니다. |
| `TELEGRAM_PERSONAL_BOT_TOKEN` | 빈 값 | `target: personal` Telegram 채널의 Bot Token입니다. target이 `team-alert`라면 `TELEGRAM_TEAM_ALERT_BOT_TOKEN` 형식을 사용합니다. |
| `TELEGRAM_PERSONAL_CHAT_ID` | 빈 값 | 해당 Telegram target의 Chat ID입니다. target 별칭 규칙은 Bot Token과 같습니다. |
| `NEXTCLOUD_URL` | 빈 값 | Nextcloud 서버 기본 URL입니다. |
| `NEXTCLOUD_VERIFY_TLS` | `true` | Nextcloud HTTPS 인증서 검증 여부입니다. 운영에서는 비활성화하지 마세요. |
| `NEXTCLOUD_TALK_PERSONAL_USERNAME` | 빈 값 | `target: personal` Talk 전송용 사용자명입니다. |
| `NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD` | 빈 값 | Talk 전송용 Nextcloud 앱 비밀번호입니다. 일반 비밀번호 대신 앱 비밀번호를 사용하세요. |
| `NEXTCLOUD_TALK_PERSONAL_ROOM_TOKEN` | 빈 값 | 메시지를 보낼 Talk Room Token입니다. |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP 서버 주소입니다. Gmail은 기본값을 그대로 사용합니다. |
| `SMTP_PORT` | `587` | SMTP 서버 포트입니다. Gmail STARTTLS는 `587`을 사용합니다. |
| `SMTP_USERNAME` | 빈 값 | SMTP 로그인 계정입니다. Gmail은 발신 Gmail 주소를 입력합니다. |
| `SMTP_PASSWORD` | 빈 값 | SMTP 로그인 비밀값입니다. Gmail은 일반 계정 비밀번호가 아니라 Google 계정의 **앱 비밀번호**를 입력합니다. |
| `SMTP_FROM` | `SMTP_USERNAME` | 메일의 발신자 주소입니다. 비우면 `SMTP_USERNAME`을 사용합니다. SMTP 서버에서 허용한 주소여야 합니다. |
| `SMTP_USE_TLS` | `true` | STARTTLS 사용 여부입니다. Gmail은 `true`를 유지하세요. |
| `SMTP_PERSONAL_TO` | 빈 값 | `type: email`, `target: personal`로 보낼 수신자 이메일입니다. 여러 명은 쉼표로 구분합니다. |
| `ENABLE_FAKE_CHANNEL` | `false` | `true`일 때 `type: fake` 채널을 활성화합니다. 테스트와 로컬 검증 전용입니다. |

### Gmail SMTP 설정

Gmail 전송에는 API 키가 아니라 SMTP용 **앱 비밀번호**를 사용합니다. Google 계정에서 2단계 인증을 켠 뒤 앱 비밀번호를 발급하고, 설정 탭의 `SMTP 사용자 이메일`에 Gmail 주소, `SMTP 앱 비밀번호`에 발급받은 앱 비밀번호를 입력하세요. 서버는 `smtp.gmail.com`, 포트는 `587`, STARTTLS는 `true`로 둡니다. `수신 이메일`에 실제 받을 주소를 입력하고 저장하면 전송 채널 목록에 `email: personal`이 나타납니다.

예약 또는 즉시 전송 화면에서 `email: personal`을 체크하면 동일한 결과를 이메일로도 전송합니다. 수신자를 여러 명 지정할 때는 `person1@example.com, person2@example.com` 형식으로 입력하세요.

## 실행 이력 및 재전송

예약 작업이 실제 실행되면 최종 응답 전문, 실행 상태, 오류 및 채널 전송 결과가 SQLite DB에 저장됩니다. 좌측 **실행 이력**에서 기본 최근 30일 기록을 작업 ID 또는 응답 내용으로 검색하고, 하나를 선택해 내용을 확인할 수 있습니다. 원하는 채널을 체크해 모델을 다시 호출하지 않고 저장된 응답을 수동 재전송할 수 있습니다. 보존 기간은 연결 설정의 `실행 이력 보관 기간` 또는 `EXECUTION_RETENTION_DAYS`로 변경합니다.

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
