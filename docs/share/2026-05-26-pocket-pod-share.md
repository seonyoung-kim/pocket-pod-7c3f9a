---
marp: true
theme: default
paginate: true
size: 16:9
title: pocket-pod - YouTube를 내 개인 팟캐스트로 바꾸기
description: 5~10분 공유용 슬라이드
---

<!--
발표 길이: 5~10분
권장 진행: 12장, 장당 30~50초
작성 기준: 기존 docs/share/2026-05-pocket-pod-talk.md 는 참고하지 않고,
README, 구현 코드, 테스트, 현재 런타임 state/feed 를 기준으로 새로 구성.
-->

# pocket-pod

## YouTube를 내 개인 팟캐스트로 바꾸기

채널을 등록하면  
최근 인기 영상을 후보로 보여주고  
내가 고른 영상만 오디오 팟캐스트 피드로 만든다

<!--
메모: 한 문장으로 시작한다. "이건 유튜브 영상을 다운로드하는 도구"가 아니라
"내가 구독할 수 있는 개인 팟캐스트 피드를 만드는 도구"라고 잡아준다.
-->

---

# 왜 만들었나

YouTube에는 좋은 긴 영상이 많지만  
소비 경험은 오디오와 잘 맞지 않는다.

- 화면을 계속 열어둬야 한다
- 추천 피드가 자꾸 옆길로 샌다
- "나중에 볼 동영상"은 거의 무덤이 된다
- 이동 중에는 팟캐스트 앱의 재생/이어듣기/속도 조절이 더 편하다

**목표:** 좋은 영상만 골라서, 폰의 팟캐스트 앱에 조용히 넣기

<!--
메모: 기술보다 사용 장면에서 출발한다. 출퇴근, 산책, 설거지처럼
화면을 볼 수 없는 시간을 예로 들면 공감이 빠르다.
-->

---

# 처음 계획은 버렸다

| v1 아이디어 | 지금 구조 |
|---|---|
| GitHub Actions cron | 내 맥에서 LaunchAgent |
| YouTube API + Gemini 점수 | yt-dlp + 조회수 + 최근성 |
| GitHub Release에 m4a 업로드 | LAN 내부에서 직접 서빙 |
| 완전 자동 다운로드 | 후보를 보고 수동 승인 |

**재설계의 핵심:** 자동화가 아니라, 실패 가능성이 낮은 사용자 주도 흐름

<!--
메모: 여기서 흥미로운 전환을 말한다. "더 자동화"가 항상 좋은 게 아니었다.
YouTube anti-bot, 외부 호스팅, API 의존성을 줄이고 로컬 LAN이라는 실제 요구에 맞췄다.
-->

---

# 사용 흐름

```text
Watchlist 등록
  -> Refresh Candidates
  -> Download / Skip / Download Selected
  -> feed.xml 재생성
  -> 팟캐스트 앱에서 http://<LAN_IP>:8000/feed.xml 구독
```

현재 로컬 상태 기준:

- 등록 채널: 3개
- 후보 영상: 10개
- 다운로드된 에피소드: 3개
- 생성된 오디오: 약 67 MiB

<!--
메모: 실제로 굴러간 데이터가 있다는 점을 보여준다.
IP 주소는 슬라이드에 직접 쓰지 않고 <LAN_IP>로 말한다.
-->

---

# 아키텍처

```text
             browser
                |
                v
        Flask console :8001
        candidates / watchlist / episodes
                |
                v
       Queue -> single download worker
                |
     +----------+-----------+
     |                      |
 state.json             feed.xml
 downloads/*.m4a           |
                            v
            Range static server :8000
                            |
                            v
                    podcast app
```

UI 서버와 피드 서버를 분리했다.  
사용자 콘솔은 자주 바뀌고, 팟캐스트 앱이 보는 RSS/오디오는 안정적으로 유지한다.

<!--
메모: 두 포트 구조가 중요한 설계 포인트다. :8001은 조작 화면,
:8000은 팟캐스트 앱이 보는 안정적인 파일 서버라고 설명한다.
-->

---

# 큐레이션 알고리즘

API key 없이, 채널의 `/videos` 페이지를 yt-dlp flat extract로 읽는다.

```python
seen = downloaded | skipped
for channel in watchlist:
    videos = fetch_recent(channel, limit=top_k * 5)
    videos = enrich_missing_metadata_once(videos)
    videos = filter_recent(videos, lookback_days)
    videos = exclude(videos, seen)
    candidates += top_by_view_count(videos, top_k)
sort(candidates, upload_date desc, view_count desc)
```

작은 결정들:

- 한글 핸들 URL은 path만 percent-encode
- `view_count` / `upload_date` 누락 시 영상 단위 deep fetch 1회
- 점수는 단순하게 `view_count`

<!--
메모: "AI 점수"를 빼고도 제품이 된다. lookback window가 최근성을,
view_count가 대중적 신호를 담당한다. 단순함이 오히려 안정성을 만든다.
-->

---

# Human-in-the-loop가 기능이다

상태는 작지만 의도가 분명하다.

```json
{
  "candidates": "이번 큐레이션 후보",
  "skipped": "다시는 추천하지 않을 영상",
  "episodes": "다운로드 완료 + RSS 입력",
  "in_progress": "다운로드 중",
  "last_errors": "재시도 가능한 실패 사유"
}
```

자동으로 다 받지 않는다.

- 후보를 채널별로 보고 고른다
- 하나씩 받거나 체크박스로 묶어서 받는다
- 마음에 안 드는 영상은 Skip으로 다음 큐레이션에서 제외한다

<!--
메모: 이 앱은 "내가 통제하는 추천 큐"에 가깝다.
Skip이 단순 삭제가 아니라 future recommendation memory라는 점을 강조한다.
-->

---

# 팟캐스트 앱이 믿는 것은 RSS다

다운로드 성공 시 `feed.xml`을 다시 만든다.

- `<enclosure>`: m4a 파일 URL, byte length, `audio/mp4`
- `itunes:duration`: 팟캐스트 앱 표시용 `HH:MM:SS`
- `description`: 영상 설명 첫 단락 + 원본 YouTube URL
- `cover.png`: iTunes 호환 정사각형 커버
- 정적 서버는 HTTP Range request 지원

**Range request가 없으면**  
일부 팟캐스트 앱에서 seek / resume / 스트리밍 재생이 불안정해진다.

<!--
메모: 여기서는 "RSS XML만 만들면 끝"이 아니라 오디오 클라이언트가 기대하는
세부 규약이 있다는 점을 이야기한다. 특히 Range request는 발표 포인트로 좋다.
-->

---

# 운영에서 배운 것

로컬 앱이어도 운영 이슈는 있다.

- LaunchAgent는 PATH가 빈약해서 `yt-dlp`와 `ffmpeg` 위치를 직접 resolve
- `RunAtLoad` + `KeepAlive`로 로그인 시 자동 실행, 죽으면 자동 재시작
- `BASE_URL`이 바뀌면 앱 부팅 시 feed를 다시 생성
- YouTube anti-bot은 cookies / proxy 환경변수로 우회 경로 제공
- 다운로드는 단일 워커로 직렬 처리해 yt-dlp 호출을 보수적으로 유지

작은 자동화가 매일 쓰는 도구의 신뢰도를 만든다.

<!--
메모: "개인 프로젝트인데 왜 launchd까지?"라는 질문에 답한다.
매일 쓰는 도구는 실행 명령을 기억하지 않아도 살아 있어야 한다.
-->

---

# 테스트가 잡는 부분

중요한 실패 모드는 51개 테스트로 고정했다.

- 오래된 영상 / 이미 받은 영상 / skip 영상 제외
- 채널 하나가 실패해도 다른 채널 큐레이션 계속 진행
- `state.json` atomic save, 깨진 JSON은 `.bak`로 격리
- 다운로드 실패 시 후보 유지 + `last_errors` 기록
- RSS enclosure, guid, iTunes duration, 원본 URL 검증
- 정적 서버 Range request는 `206 Partial Content`로 검증
- Flask route는 test client와 mock worker로 smoke test

<!--
메모: 테스트를 "몇 개 있다"가 아니라 어떤 리스크를 잠갔는지로 설명한다.
이 프로젝트의 핵심 리스크는 외부 네트워크와 파일 상태라서 그 주변을 테스트한다.
-->

---

# 데모 시나리오

1. Watchlist에서 채널 3개 확인
2. Candidates에서 후보가 채널별로 묶여 보이는 것 확인
3. `Download Selected`로 후보를 큐에 넣는 흐름 설명
4. Episodes에서 생성된 m4a와 용량 확인
5. `feed.xml`의 enclosure URL을 보여주고 팟캐스트 앱 구독으로 연결

말로 요약하면:

> "YouTube가 콘텐츠 소스고, 내 맥이 작은 팟캐스트 호스팅 서버가 된다."

<!--
메모: 실제 다운로드는 시간이 걸릴 수 있으니 이미 받은 episode와 feed.xml을 보여주는 쪽이 안전하다.
Refresh Candidates도 네트워크 상태에 따라 오래 걸릴 수 있다.
-->

---

# 다음에 붙이면 재미있는 것

- 자막 기반 요약: 영상 설명 대신 내 요약을 RSS description에 넣기
- 채널별 retention: 오래된 m4a 자동 정리
- 토큰 인증: LAN 밖으로 노출할 가능성 대비
- 키워드 모드: 채널 구독이 아니라 주제 기반 후보 수집
- 모바일 Shortcut: "공유하기 -> pocket-pod 후보 추가"

오늘의 결론:

**개인 자동화는 거창한 플랫폼보다, 내 생활 동선에 정확히 붙을 때 오래 간다.**

<!--
메모: 끝은 교훈으로 닫는다. 이 프로젝트의 재미는 기술 스택보다
"실제로 매일 쓸 수 있게 범위를 줄인 설계"에 있다.
-->
