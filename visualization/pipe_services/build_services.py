"""Add purpose metadata and isolated N2 / instrument-air demonstration circuits.

Preserves every existing pipe centreline and existing process-medium assignment.
Service colours and equipment dimensions are fictional demonstration conventions.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIS = ROOT.parent
UNITY = VIS.parent/"unity/MAEKInspection/Assets/MAEK"


def catalog():
    rows = [
        ("BFG_RAW", "미정제 고로가스", "Raw blast-furnace gas", "BFG", "#A65B3B",
         "고로 상부에서 배출된 가스를 집진기로 이송", "고로 상부 → 집진기",
         "분진 포함; 온도·압력 미설정", "분진 마모·외면 부식·접합부 감육"),
        ("BFG_DEDUST", "1차 집진 고로가스", "Dedusted blast-furnace gas", "BFG", "#C9874C",
         "1차 집진 후 습식 세정기로 이송", "집진기 → 세정기",
         "습식 세정 전; 물성 미설정", "잔류 분진 마모·감육·접합부"),
        ("BFG_CLEAN", "정제 고로가스", "Clean blast-furnace gas", "BFG", "#C6A568",
         "세정된 가스의 압력에너지 회수와 연료 공급", "세정기 → TRT → 열풍로·보일러",
         "공급 분기별 밸브 상태가 다름", "응축 가능 구간 부식·저점부·접합부"),
        ("COLD_BLAST", "냉풍 공기", "Cold blast air", "AIR", "#52BAD1",
         "송풍기 공기를 열풍로로 공급", "송풍기 → 열풍로 냉풍 입구",
         "열풍로 ON_BLAST 분기만 열림", "접합부·진동 지지부·외면 부식"),
        ("HOT_BLAST", "열풍 공기", "Hot blast air", "AIR", "#F17439",
         "열풍로에서 가열한 공기를 고로 풍구로 공급", "열풍로 → 환상관 → 풍구",
         "고온 계통; 실제 온도·내화물 사양 미설정", "외피·팽창 이음·열영향 구간"),
        ("COMB_AIR", "연소용 공기", "Combustion air", "COMB_AIR", "#77D6C0",
         "열풍로 가열 단계의 연소 공기 공급", "연소공기 송풍기 → 열풍로 버너",
         "열풍로 ON_GAS 분기만 열림", "접합부·진동 지지부·부식"),
        ("FLUE", "연소 배기가스", "Flue gas", "FLUE", "#9F94AE",
         "연소 후 배기가스를 굴뚝으로 이송", "열풍로·보일러 → 굴뚝",
         "고로가스 연료 배관과 구분", "온도 영향·응축부 부식·감육"),
        ("CW_SUPPLY", "냉각수 공급", "Cooling water supply", "CW", "#328CDB",
         "냉각기·펌프에서 고로 냉각판으로 물 공급", "냉각기 → 펌프 → 냉각판",
         "폐회로의 공급측", "외면 부식·감육·밸브 및 지지부"),
        ("CW_RETURN", "냉각수 환수", "Cooling water return", "CW", "#9B6BC8",
         "냉각판에서 열을 받은 물을 냉각기로 회수", "냉각판 → 환수관 → 냉각기",
         "폐회로의 환수측", "공급측과 구분한 온도·부식·감육 확인"),
        ("WASH", "가스 세정수", "Gas-washing water", "WASH", "#3CBFA6",
         "가스 세정기에 순환수·보충수 공급", "침전조·보충수 → 펌프 → 세정기",
         "고로 냉각수와 독립 계통", "침전물·스케일·마모·감육"),
        ("SLURRY", "세정 슬러리", "Scrubber slurry", "SLURRY", "#96744D",
         "세정 배수와 포집 분진을 침전·슬러지 처리로 이송", "세정기 → 침전조 → 슬러지 수집",
         "고형물 포함 유체", "곡관·저점부의 마모·침적·감육"),
        ("TRAIN_CW", "검사 훈련용 물 순환", "Inspection training water", "CW", "#7FA4BD",
         "건물 내부 MAEK 검사 훈련용 독립 물 순환", "훈련 펌프 → 시험 코일 → 펌프",
         "실제 고로 냉각회로와 연결하지 않음", "합성 결함·측정 위치 시연"),
        ("N2", "질소 불활성화 시험", "Nitrogen inerting demo", "N2", "#D9B9F0",
         "정비용 시험 챔버의 질소 공급과 회수", "질소 공급 → 감압 → 차단밸브 → 챔버 → 회수 용기",
         "새 가상 시험 계통; 기본 차단; 가스 농도 해석 없음", "접합부·지지부·외면 부식·감육"),
        ("INSTR_AIR", "계장용 압축공기", "Instrument air", "INSTR_AIR", "#F2D765",
         "공압 액추에이터 구동용 공기 공급", "압축공기 공급 → 건조기 → 조압기 → N2 밸브 액추에이터",
         "열풍·연소공기와 독립; 공압 제어동작 미해석", "소구경 관·접속부·지지부 점검"),
    ]
    result = []
    for code, ko, en, medium, color, purpose, route, condition, inspection in rows:
        result.append(dict(code=code, labelKo=ko, labelEn=en, medium=medium,
                           color=[int(color[i:i+2], 16)/255 for i in (1, 3, 5)],
                           purpose=purpose, route=route, condition=condition,
                           inspection=inspection))
    return result


def classify(line):
    lid, medium = line["id"], line["medium"]
    suffix = lid.split("-")[-1]
    if ".TRAIN-" in lid:
        return "TRAIN_CW"
    if medium == "BFG":
        if suffix in ("G001", "G002", "G003"):
            return "BFG_RAW"
        return "BFG_DEDUST" if suffix == "G004" else "BFG_CLEAN"
    if medium == "AIR":
        return "COLD_BLAST" if suffix.startswith("C") else "HOT_BLAST"
    if medium == "CW":
        return "CW_RETURN" if suffix.startswith("WR") or suffix == "W003" else "CW_SUPPLY"
    return {"COMB_AIR": "COMB_AIR", "FLUE": "FLUE", "WASH": "WASH",
            "SLURRY": "SLURRY", "N2": "N2", "INSTR_AIR": "INSTR_AIR"}[medium]


def place_skid(manifest):
    # Find clear outdoor space for an explicitly separate utility test module.
    for x, y in [(-124, -55), (-128, 65), (115, -55), (128, 65), (-155, -50)]:
        lo, hi = [x-1.8, .21, y-4], [x+8.3, 4, y+2.3]
        blocked = []
        for a in manifest["assets"]:
            if a["id"] in ("Process yard", "Distant ground", "Site road"):
                continue
            p, s = a["position"], a["size"]
            if all(p[k]+s[k]/2 > lo[k] and p[k]-s[k]/2 < hi[k] for k in range(3)):
                blocked.append(a["id"])
        if not blocked:
            return [x, y, 0]
    raise ValueError("No clear utility-skid candidate; inspect geometry before placing")


def add_utilities(net, origin):
    shapes = []

    def pos(x, y, z):
        return [x+origin[0], y+origin[1], z]

    def device(key, label, shape, xyz, size, color, mount=""):
        ident = "UTIL."+key
        net["devices"][ident] = {"kind": label, "center": pos(*xyz), "dimensions": size,
                                  "source": "MAEK fictional utility test skid"}
        shapes.append(dict(id=ident, label=label, shape=shape, position=pos(*xyz),
                           size=size, color=color, mountOn=mount))
        return ident

    def port(key, xyz, medium, owner):
        ident = "UTIL."+key
        net["nodes"][ident] = dict(position=pos(*xyz), medium=medium,
                                    device="UTIL."+owner, kind="port")
        return ident

    def line(key, a, b, medium, via=(), state="standby"):
        a, b = "UTIL."+a, "UTIL."+b
        net["lines"].append(dict(id="UTIL-"+key, **{"from": a, "to": b}, medium=medium,
            radius_m=.035 if medium == "N2" else .025, state=state,
            source="MAEK fictional utility test skid", exact_polyline=True,
            points=[net["nodes"][a]["position"]]+[pos(*p) for p in via]+
                   [net["nodes"][b]["position"]],
            dimensions_basis="illustrative outside radius, not DN or a pressure rating"))

    metal, purple, yellow = [.38, .43, .46], [.58, .45, .70], [.65, .57, .30]
    device("PAD", "Utility demonstration plinth", "box", (3.2, -.8, .1), [8.5, 4.6, .2], metal)
    for key, name, xyz, size, col in [
        ("N2.SOURCE", "N2 supply vessel", (0, 0, 1.2), [.6, .6, 2], purple),
        ("N2.CHAMBER", "Isolated maintenance test chamber", (4.8, 0, 1.2), [1.1, 1.1, 2], metal),
        ("N2.RECOVERY", "Closed demonstration gas receiver", (6.7, 0, 1.1), [.8, .8, 1.8], metal),
        ("IA.SOURCE", "Compressed instrument air boundary", (0, -2, 1.1), [.7, .7, 1.8], yellow),
    ]:
        device(key, name, "cylinder", xyz, size, col)
    for key, name, xyz, size, col in [
        ("N2.REG", "Nitrogen pressure regulator", (1.4, 0, 1.5), [.5, .35, .35], purple),
        ("N2.VALVE", "Normally closed nitrogen isolation valve", (2.8, 0, 1.5), [.5, .35, .35], purple),
        ("IA.DRYER", "Instrument air dryer", (1.4, -2, 1.3), [.5, .5, .9], yellow),
        ("IA.REG", "Instrument air regulator", (2.5, -2, 1.3), [.4, .35, .35], yellow),
    ]:
        owner = device(key, name, "box", xyz, size, col)
        top = xyz[2]-size[2]/2
        device(key+".SUPPORT", "Equipment support", "box",
               (xyz[0], xyz[1], (.2+top)/2), [.12, .12, top-.2], metal, owner)
    device("N2.ACT", "Air actuator; separate from process N2", "box", (2.8, 0, 1.9),
           [.32, .32, .45], yellow, "UTIL.N2.VALVE")
    ports = [
        ("N2.SOURCE.OUT", (.3, 0, 1.5), "N2", "N2.SOURCE"),
        ("N2.REG.IN", (1.15, 0, 1.5), "N2", "N2.REG"),
        ("N2.REG.OUT", (1.65, 0, 1.5), "N2", "N2.REG"),
        ("N2.VALVE.IN", (2.55, 0, 1.5), "N2", "N2.VALVE"),
        ("N2.VALVE.OUT", (3.05, 0, 1.5), "N2", "N2.VALVE"),
        ("N2.CHAMBER.IN", (4.25, 0, 1.5), "N2", "N2.CHAMBER"),
        ("N2.CHAMBER.OUT", (4.8, 0, 2.2), "N2", "N2.CHAMBER"),
        ("N2.RECOVERY.IN", (6.3, 0, 1.5), "N2", "N2.RECOVERY"),
        ("IA.SOURCE.OUT", (.35, -2, 1.3), "INSTR_AIR", "IA.SOURCE"),
        ("IA.DRYER.IN", (1.15, -2, 1.3), "INSTR_AIR", "IA.DRYER"),
        ("IA.DRYER.OUT", (1.65, -2, 1.3), "INSTR_AIR", "IA.DRYER"),
        ("IA.REG.IN", (2.3, -2, 1.3), "INSTR_AIR", "IA.REG"),
        ("IA.REG.OUT", (2.7, -2, 1.3), "INSTR_AIR", "IA.REG"),
        ("N2.ACT.AIR", (2.8, -.16, 1.95), "INSTR_AIR", "N2.ACT"),
    ]
    for entry in ports:
        port(*entry)
    line("N001", "N2.SOURCE.OUT", "N2.REG.IN", "N2")
    line("N002", "N2.REG.OUT", "N2.VALVE.IN", "N2", state="closed")
    line("N003", "N2.VALVE.OUT", "N2.CHAMBER.IN", "N2")
    line("N004", "N2.CHAMBER.OUT", "N2.RECOVERY.IN", "N2",
         [(4.8, 0, 2.65), (5.8, 0, 2.65), (5.8, 0, 1.5)])
    line("I001", "IA.SOURCE.OUT", "IA.DRYER.IN", "INSTR_AIR")
    line("I002", "IA.DRYER.OUT", "IA.REG.IN", "INSTR_AIR")
    line("I003", "IA.REG.OUT", "N2.ACT.AIR", "INSTR_AIR",
         [(3.5, -2, 1.3), (3.5, -2, 2.35), (3.5, -.7, 2.35),
          (2.8, -.7, 2.35), (2.8, -.7, 1.95)])
    for a, b, active in [("N2.REG.IN", "N2.REG.OUT", True),
                          ("N2.VALVE.IN", "N2.VALVE.OUT", False),
                          ("N2.CHAMBER.IN", "N2.CHAMBER.OUT", True),
                          ("IA.DRYER.IN", "IA.DRYER.OUT", True),
                          ("IA.REG.IN", "IA.REG.OUT", True)]:
        net["internal_connections"].append(dict(
            **{"from": "UTIL."+a, "to": "UTIL."+b}, active=active,
            kind="utility demonstration equipment passage"))
    net["control_relationships"] = [{"from": "UTIL.N2.ACT", "to": "UTIL.N2.VALVE",
                                    "kind": "pneumatic actuation, NOT a fluid connection",
                                    "implemented": "metadata only; normally closed"}]
    return shapes


def build():
    original = json.loads((VIS/"drone_verified_network.json").read_text())
    net = copy.deepcopy(original)
    manifest = json.loads((UNITY/"Source/maek_manifest.json").read_text())
    origin = place_skid(manifest)
    assets = add_utilities(net, origin)
    services = catalog()
    by_code = {s["code"]: s for s in services}
    flat = []
    for line in net["lines"]:
        code = classify(line)
        line["service"] = code
        ring = line["from"].split(".")[-2] in ("B", "WS", "WR") and (
            line["to"].split(".")[-2] == line["from"].split(".")[-2])
        # Closed stoves can leave open headers idle. Do not claim measured flow.
        flow = "환상관 분기·방향 미해석" if ring else "설계 연결 방향·실제 유량 미해석"
        if line["state"] == "closed":
            flow = "차단 상태; 흐름 표시 없음"
        line["flow_basis"] = flow
        a, b = net["nodes"][line["from"]], net["nodes"][line["to"]]
        flat.append(dict(id=line["id"], serviceCode=code, medium=line["medium"],
                         fromNode=line["from"], toNode=line["to"], state=line["state"],
                         fromEquipment=a["device"] or "분기점",
                         toEquipment=b["device"] or "분기점", flowBasis=flow,
                         directionResolved=False, radius=line["radius_m"],
                         length=sum(math.dist(a, b) for a, b in zip(line["points"],
                                                                  line["points"][1:])),
                         points=[dict(position=p) for p in line["points"]],
                         newGeometry=line["id"].startswith("UTIL-"),
                         pressureBasis="현장값 없음", materialBasis="재질·배관등급 미지정"))
        assert by_code[code]["medium"] == line["medium"]
        assert a["medium"] == b["medium"] == line["medium"]
    for old, new in zip(original["lines"], net["lines"]):
        assert all(new[key] == value for key, value in old.items()), old["id"]
    dataset = dict(version=1, basis="MAEK fictional service assignment, not POSCO as-built",
                   colorBasis="Demonstration palette; not an identification standard",
                   coordinateMap="Blender x,y,z => Unity x,z,y", services=services,
                   pipes=flat, utilityAssets=assets, utilityOrigin=origin)
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT/"services_network.json").write_text(json.dumps(net, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    text = json.dumps(dataset, ensure_ascii=False, indent=2)
    (ROOT/"pipe_services.json").write_text(text, encoding="utf-8")
    (UNITY/"Source/pipe_services.json").write_text(text, encoding="utf-8")
    with (ROOT/"line_service_list.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["line_id", "service", "용도", "from", "to", "state", "흐름근거"])
        for pipe in flat:
            writer.writerow([pipe["id"], pipe["serviceCode"],
                             by_code[pipe["serviceCode"]]["labelKo"], pipe["fromNode"],
                             pipe["toNode"], pipe["state"], pipe["flowBasis"]])
    summary = dict(status="PASS", original_pipes=240, total_pipes=len(flat),
                   service_counts=dict(Counter(p["serviceCode"] for p in flat)),
                   utility_origin=origin, source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                   original_geometry_preserved=True, service_colors_not_a_standard=True,
                   network_hydraulics_solved=False)
    (ROOT/"service_data_report.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    build()
