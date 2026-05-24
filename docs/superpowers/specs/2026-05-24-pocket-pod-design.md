# pocket-pod 설계 문서

- 작성일: 2026-05-24
- 작성자: K (seonyoung.kim@navercorp.com)
- 상태: Draft (사용자 리뷰 대기)

## 1. 목적

매주 1-2회 자동으로 YouTube에서 관심 영상을 선별해 오디오만 추출하고, 개인 RSS 팟캐스트 피드로 발행한다. iPhone의 Apple Podcasts에서 구독하여 와이파이 없는 환경에서도 오프라인 재생한다.

## 2. 비기능 요구사항

| 항목 | 목표 |
|---|---|
| 비용 | 월 $0 (GitHub Actions 무료 한도, Gemini 무료 티어, YouTube Data API 무료 quota 내) |
| 인프라 의존 | GitHub만 사용. 로컬 Mac이 켜져 있을 필요 없음 |
| 보안 | Repo는 public, URL 추측 불가능성으로 비공개 유지 |
| 발행 주기 | 매주 월·목 06:00 KST |
| 1회 분량 | Top 5 에피소드, 영상당 5-90분 |
| 보관 | 14일 후 자동 삭제 (release + asset) |

## 3. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│        GitHub Repo: pocket-pod-7c3f9a (public)              │
│                                                             │
│  config/interests.yaml   (관심사 프로필)                    │
│  .github/workflows/curate.yml   (cron: 월·목 06:00 KST)     │
│                                                             │
│  scripts/                                                   │
│    ├─ curate.py   (YouTube search + Gemini 2-stage 평가)    │
│    ├─ download.py (yt-dlp로 오디오 추출)                    │
│    ├─ publish.py  (GitHub Release 업로드 + RSS 생성)        │
│    └─ cleanup.py  (14일 경과 release 삭제)                  │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
   GitHub Releases                    GitHub Pages
   (.m4a 오디오 assets)               feed.xml + index.html
   public asset URL          ◄────────── <enclosure url=...>
                                          ▲
                                          │ subscribe
                                          │
                                  Apple Podcasts (iPhone)
                                  → 자동 오프라인 다운로드
```

## 4. 데이터 흐름 (한 사이클)

1. **트리거**: GitHub Actions cron이 매주 월·목 06:00 KST에 `curate.yml` 실행
2. **관심사 로드**: `config/interests.yaml` 읽기
3. **후보 수집**: YouTube Data API `search.list`
   - 각 `keywords` 항목별로 `publishedAfter = now - 7일`, `videoDuration = medium|long`, `order = relevance`로 호출
   - 응답에서 5분 미만 / 90분 초과 영상 제거, 중복 제거
   - 결과 풀: 50-100개
4. **Stage 1 큐레이션 (Gemini 2.0 Flash)**:
   - 입력: 후보 전체의 메타데이터 (제목/설명/채널/길이/조회수/게시일)
   - 출력: JSON 배열 `[{video_id, score(0-10), reason}]`
   - Top 10 선정
5. **Stage 2 큐레이션 (Gemini 2.5 Pro)**:
   - 입력: Top 10의 YouTube URL을 `fileData`로 한 건씩 전달
   - 출력: 깊이 있는 평가 + 1-2 문장 요약 + 최종 점수
   - Top 5 선정
6. **오디오 추출 (yt-dlp)**:
   - `yt-dlp -f "bestaudio[ext=m4a]/bestaudio" --extract-audio --audio-format m4a`
   - 임시 디렉토리에 저장
   - 메타데이터(제목/채널/요약/길이) 별도 JSON 보관
7. **Release 업로드**:
   - tag: `weekly-YYYY-MM-DD`
   - assets: 5개 .m4a + `episodes.json` (메타데이터)
8. **RSS 재생성**:
   - 모든 활성 release 순회 → `<item>` 생성
   - `<enclosure url="https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}" type="audio/mp4">`
   - iTunes 태그 포함 (`itunes:duration`, `itunes:summary`, `itunes:author`, `itunes:image`)
9. **GitHub Pages 배포**:
   - `gh-pages` 브랜치에 `feed.xml` + 간단한 `index.html` push
10. **Cleanup**:
    - 14일 이상 경과한 release 및 asset 삭제 (idempotent)

## 5. 컴포넌트 상세

### 5.1 `config/interests.yaml`

```yaml
keywords:
  - 희야기   # 초기 샘플
excludes:    # 제목/설명에 들어가면 제외
  - 광고
  - 협찬
duration:
  min_minutes: 5
  max_minutes: 90
recency_days: 7   # 며칠 이내 영상만 후보로
top_n: 5          # 최종 선정 개수
```

확장 후보: `channels_preferred` (가중치), `lang` (ko/en), `target_count` (Stage 1 결과 수).

### 5.2 `scripts/curate.py`

**역할**: YouTube 검색 → 2-stage Gemini 평가 → 선정 결과 JSON 저장

**환경변수**:
- `YOUTUBE_API_KEY`
- `GEMINI_API_KEY`

**출력**: `./out/selected.json` (video_id, title, channel, duration_sec, summary, url)

**LLM 호출 방식**:
- Stage 1: `gemini-2.0-flash`, 단일 호출에 후보 전체 JSON으로 압축 전달
- Stage 2: `gemini-2.5-pro`, 영상별 1회씩 `fileData` 입력 (YouTube URL 직접)

**rate limit 대응**: Stage 2 호출 사이 4초 sleep (분당 15회 안전 마진).

### 5.3 `scripts/download.py`

**역할**: `selected.json`의 video_id 목록을 받아 m4a 추출.

**도구**: `yt-dlp` (Actions runner에 `pip install`).

**파일명**: `{YYYY-MM-DD}_{video_id}_{slug}.m4a` (slug는 제목에서 안전 문자만).

**실패 처리**: 한 영상 다운로드 실패 시 다음 영상으로 진행, 실패 로그만 출력. 재시도하지 않음.

### 5.4 `scripts/publish.py`

**역할**: Release 생성 + asset 업로드 + RSS 재생성 + Pages push.

**의존**: `gh` CLI (Actions runner 기본 제공), `feedgen` 라이브러리.

**RSS 채널 메타**:
```xml
<title>pocket-pod</title>
<description>K's curated YouTube audio feed</description>
<itunes:author>K</itunes:author>
<itunes:explicit>false</itunes:explicit>
<itunes:category text="Education"/>
```

**episode 메타**:
- `<title>`: 영상 제목 + " — " + 채널명
- `<description>`: Gemini Pro 요약
- `<pubDate>`: release 생성 시각
- `<guid isPermaLink="false">`: `youtube:{video_id}`
- `<enclosure url="..." type="audio/mp4" length="{bytes}"/>`
- `<itunes:duration>HH:MM:SS</itunes:duration>`

### 5.5 `scripts/cleanup.py`

**역할**: 14일 이상 경과한 release 삭제.

**구현**: `gh release list --limit 100 --json tagName,publishedAt`로 가져와 cutoff 비교 후 `gh release delete --yes --cleanup-tag`.

### 5.6 `.github/workflows/curate.yml`

**스케줄**: `cron: '0 21 * * 0,3'` (UTC, 한국 시간 월·목 06:00)

**스텝**:
1. checkout
2. setup Python 3.11
3. `pip install -r requirements.txt` (yt-dlp, google-generativeai, feedgen, pyyaml, requests)
4. install ffmpeg (`sudo apt-get install -y ffmpeg`)
5. `python scripts/curate.py`
6. `python scripts/download.py`
7. `python scripts/publish.py`
8. `python scripts/cleanup.py`
9. (실패 시) GitHub Actions 기본 이메일 알림 사용

**Secrets**: `YOUTUBE_API_KEY`, `GEMINI_API_KEY`.

**Permissions**: `contents: write`, `pages: write`, `id-token: write`.

**수동 트리거**: `workflow_dispatch`로 즉시 실행 가능.

## 6. 보안 모델

- Repo는 public이지만 이름이 `pocket-pod-7c3f9a`로 추측 불가능
- RSS URL: `https://{owner}.github.io/pocket-pod-7c3f9a/feed.xml` (URL을 모르면 도달 불가)
- 누군가 URL을 알게 되면 무료로 들을 수 있음 → 민감한 콘텐츠 큐레이션 금지
- API 키는 모두 GitHub Secrets에 저장, 코드 hardcode 금지
- Stage 1/2 로그에 video_id 정도만 남기고 API 응답 raw는 저장하지 않음

## 7. 에러 처리

| 단계 | 실패 시 동작 |
|---|---|
| YouTube search 0건 | 사이클 중단, "no candidates" 로그 후 정상 종료 |
| Gemini Stage 1 실패 | 사이클 중단, Actions 실패로 표시 |
| Gemini Stage 2 일부 실패 | 성공한 영상으로만 진행 (Top 5 미만이어도 OK) |
| yt-dlp 다운로드 실패 | 해당 영상 skip, 나머지 진행 |
| Release 업로드 실패 | Actions 실패 → 이메일 알림 |
| RSS 생성 실패 | Actions 실패 → 이메일 알림 |
| Pages 배포 실패 | 재시도 1회, 그래도 실패 시 Actions 실패 |
| Cleanup 실패 | 다음 사이클에서 다시 정리 (idempotent) |

## 8. 테스트 전략

이 프로젝트는 외부 API 의존이 크고 1인 개인 용도이므로, 무거운 단위 테스트보다 **수동 검증 단계**를 명시한다:

1. **로컬 dry-run**: `curate.py`에 `--dry-run` 플래그를 두어 LLM 호출까지만 하고 다운로드/업로드는 skip
2. **Sample run**: 첫 실행은 `workflow_dispatch`로 수동 트리거하여 결과 확인
3. **Apple Podcasts 구독 검증**: feed.xml URL을 직접 입력해 첫 episode가 잘 보이고 다운로드 되는지 확인
4. 단위 테스트는 RSS XML 생성 함수와 cleanup 날짜 계산 함수에만 (pytest)

## 9. 초기 샘플 설정

```yaml
# config/interests.yaml (1차 배포 값)
keywords:
  - 희야기
excludes: []
duration:
  min_minutes: 5
  max_minutes: 90
recency_days: 14   # 첫 실행이라 풀 확보를 위해 길게
top_n: 5
```

운영하면서 키워드와 excludes를 추가/조정.

## 10. 향후 확장 (스코프 밖)

- 채널 가중치 (`channels_preferred`)
- 다국어 (영어 콘텐츠)
- AI 요약 음성을 인트로로 합성
- 듣기 완료 피드백 → 관심사 자동 학습
- 본인 인증 RSS (signed URL)

## 11. 미해결 가정

- GitHub Pages가 RSS 발행에 충분 (CDN 캐시 5-10분 지연 허용)
- YouTube Data API quota (10,000 units/day) 안에서 동작 — `search.list`는 호출당 100 units. 키워드 5개 × 주 2회 = 주 1,000 units, 하루 평균 143 units → 안전
- Gemini 무료 티어 변경 가능성 (Google 정책 변경 시 비용 발생 가능)
- yt-dlp가 YouTube의 anti-bot 정책 변화에 깨질 수 있음 → CI에서 매번 최신 버전 설치
