# 보고서 만드는 법

보고서 본문은 `content.js` 하나에 있고, 여기서 Markdown과 Word 파일을 함께 만듭니다. PDF는 Word에서 내보냅니다.

```sh
# 1. 그림 (ultralytics, matplotlib 필요). 인자: 결과 폴더, 가중치·시험셋 폴더, 그림 출력 폴더, 시작 가중치 폴더
python figs.py ../../../experiments/real_adaptation/results <out> <fig-src> <w>
python prep_fig.py <fig-src> ../fig
# 2. 문서 (npm install docx)
node build_report.js ..
```

`<out>`에는 `maek_corrosion_real_v1.pt`, `maek_thermal_real_v1.pt`와 `testsets/`(실험의 시험셋)가, `<w>`에는 `e4.pt`, `sim_S.pt`가 있어야 합니다. 화면 캡처(`shot_*.jpg`)는 사이트를 띄워 따로 찍은 것입니다.
