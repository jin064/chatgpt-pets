# ChatGPT Pets — 우사기 & 시나모롤

우사기와 시나모롤을 바탕으로 제작한 팬메이드 애니메이션 펫 파일 모음입니다.
두 펫 모두 9가지 동작과 16방향 시선, 총 73프레임을 포함합니다.

| 먼작귀 우사기 | 시나모롤 |
| --- | --- |
| ![우사기](pets/usagi/previews/all-states.gif) | ![시나모롤](pets/cinnamoroll/previews/all-states.gif) |
| [파일·미리보기](pets/usagi) | [파일·미리보기](pets/cinnamoroll) |

## 다운로드와 사용

각 폴더의 `spritesheet.png`가 검증된 투명 배경 스프라이트입니다.
파일을 다운로드한 뒤 Pets 플러그인이 연결된 채팅에 첨부해 새 펫으로 등록해 달라고 요청할 수 있습니다.
이 저장소에는 계정별 펫 ID나 로그인 정보가 포함되어 있지 않습니다.

- [우사기 PNG](pets/usagi/spritesheet.png)
- [시나모롤 PNG](pets/cinnamoroll/spritesheet.png)
- [우사기 “우나!” 알림음](pets/usagi/audio/chiikawa-usagi-una.mp3)

## 스프라이트 규격

| 항목 | 값 |
| --- | --- |
| 형식 | 투명 PNG, v2 |
| 전체 크기 | 1536 × 2288 px |
| 셀 크기 | 192 × 208 px |
| 배열 | 8열 × 11행 |
| 사용 프레임 | 73개 |
| 동작 | idle, running-right, running-left, waving, jumping, failed, waiting, running, review |
| 시선 | 위에서 시작하여 시계 방향으로 16방향 |

`running`은 작업·생각 중인 상태이며, 이동은 `running-right`와 `running-left`입니다.
`previews/`에는 동작별 GIF, 전체 동작 GIF/MP4, 점프 전환과 시선 루프가 있습니다.
각 `validation.json`에 구조·동작 품질·방향 판독 검사 결과를 요약했습니다.
일부 중간 시선 변화와 대기·작업 동작의 차이는 부드러운 편입니다.

## 제작

사용자 참고 이미지와 내장 이미지 생성 도구로 제작했으며, 결정론적 추출·조립·검증을 거쳤습니다.
우사기는 Chiikawa, 시나모롤은 Sanrio의 캐릭터를 바탕으로 한 비공식 팬 제작물입니다.
