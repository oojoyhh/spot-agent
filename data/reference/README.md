# 지하철역 기준 데이터

`subway_stations.json`은 다음 두 자료를 역명과 호선으로 결합한 실행용 기준 파일이다.

- 역 코드: SK Open API `GET /puzzle/subway/meta/stations` 응답을 보관한
  [D3vle0/subway-congestion 스냅샷](https://github.com/D3vle0/subway-congestion/blob/c953bbc635b1563a6591439e79dda15b406475bb/data/subway_num.json)
- 좌표: 서울특별시 [서울시 역사마스터 정보](https://data.seoul.go.kr/bsp/wgs/dataView/data300View/10048.do),
  공공누리 제1유형

생성일은 2026-09-11이며 468개 SK 코드 모두에 좌표를 연결했다.
SK 코드 원본은 2022-09-01 스냅샷이므로 API 호출 한도가 복구되면 공식
`type=exit` 목록으로 갱신해야 한다. 역명 변경 보정과 기준일은 JSON의
`metadata`에 기록되어 있다.

## SK 코드 스냅샷 라이선스

MIT License

Copyright (c) 2022 D3vle0

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
