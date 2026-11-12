// Builds MAEK_followup_report.md and .docx from content.js (single source).
//   node build_report.js <output dir containing fig/>
const fs = require("fs"), path = require("path");
const D = require("docx");
const blocks = require("./content.js");

const OUT = process.argv[2], FIG = path.join(OUT, "fig");
const FONT = "맑은 고딕", INK = "111111", BLUE = "1F7FA8", GREY = "5B6470", LINE = "C9D1D9", TINT = "EAF3F8";
const CONTENT_W = 9638; // A4 with 2 cm margins, in DXA

const runs = (text, base = {}) => text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((t) => new D.TextRun({
  text: t.replace(/^\*\*|\*\*$/g, ""), bold: /^\*\*/.test(t) || base.bold, font: FONT, size: base.size || 22, color: base.color || INK }));
const para = (text, o = {}) => new D.Paragraph({ children: runs(text, o), alignment: o.align, keepNext: o.keepNext,
  spacing: { before: o.before ?? 60, after: o.after ?? 100, line: 300 } });
const gap = (after) => new D.Paragraph({ spacing: { before: 0, after }, children: [] });

function imageSize(file) {
  const b = fs.readFileSync(file);
  if (b[0] === 0x89) return [b.readUInt32BE(16), b.readUInt32BE(20)]; // PNG IHDR
  for (let i = 2; i < b.length;) { // JPEG: find a start-of-frame marker
    const marker = b[i + 1], len = b.readUInt16BE(i + 2);
    if (marker >= 0xc0 && marker <= 0xc2) return [b.readUInt16BE(i + 7), b.readUInt16BE(i + 5)];
    i += 2 + len;
  }
  throw new Error("cannot read image size: " + file);
}

const line = { style: D.BorderStyle.SINGLE, size: 4, color: LINE };
const none = { style: D.BorderStyle.NONE, size: 0, color: "FFFFFF" };

function table(t) {
  const w = t.widths.map((p) => Math.round(CONTENT_W * p / 100));
  w[w.length - 1] += CONTENT_W - w.reduce((a, b) => a + b, 0);
  const cell = (text, i, head, keep) => new D.TableCell({
    width: { size: w[i], type: D.WidthType.DXA }, borders: { top: line, bottom: line, left: line, right: line },
    margins: { top: 70, bottom: 70, left: 110, right: 110 }, verticalAlign: D.VerticalAlign.CENTER,
    shading: head ? { type: D.ShadingType.CLEAR, fill: TINT, color: "auto" } : undefined,
    children: [new D.Paragraph({ children: runs(text, { size: 20, bold: head }), keepNext: keep, spacing: { before: 0, after: 0, line: 270 } })] });
  return new D.Table({ width: { size: CONTENT_W, type: D.WidthType.DXA }, columnWidths: w, rows: [
    new D.TableRow({ tableHeader: true, cantSplit: true, children: t.head.map((h, i) => cell(h, i, true, true)) }),
    ...t.rows.map((r, k) => new D.TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, i, false, t.rows.length <= 8 && k < t.rows.length - 1)) })),
  ] });
}

function callout(lines) {
  return new D.Table({ width: { size: CONTENT_W, type: D.WidthType.DXA }, columnWidths: [CONTENT_W], rows: [new D.TableRow({ children: [new D.TableCell({
    width: { size: CONTENT_W, type: D.WidthType.DXA }, shading: { type: D.ShadingType.CLEAR, fill: TINT, color: "auto" },
    borders: { top: none, bottom: none, right: none, left: { style: D.BorderStyle.SINGLE, size: 36, color: BLUE } },
    margins: { top: 130, bottom: 130, left: 220, right: 200 },
    children: lines.map((l, i) => new D.Paragraph({ children: runs(l, { size: i === 0 ? 24 : 21 }), spacing: { before: i ? 100 : 0, after: 0, line: 320 } })),
  })] })] });
}

function image(im) {
  const file = path.join(FIG, im.file), [pw, ph] = imageSize(file);
  return [
    new D.Paragraph({ alignment: D.AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 60 }, children: [new D.ImageRun({
      type: im.file.endsWith(".png") ? "png" : "jpg", data: fs.readFileSync(file),
      transformation: { width: im.width, height: Math.round(im.width * ph / pw) },
      altText: { title: im.caption, description: im.caption, name: im.file } })] }),
    para(im.caption, { size: 19, color: GREY, align: D.AlignmentType.CENTER, before: 0, after: 160 }),
  ];
}

const children = [], md = [];
for (let n = 0; n < blocks.length; n++) {
  const b = blocks[n], next = blocks[n + 1], prev = blocks[n - 1];
  if (b.title) {
    children.push(new D.Paragraph({ children: [new D.TextRun({ text: b.title, font: FONT, size: 52, bold: true, color: INK })], spacing: { before: 0, after: 80 } }));
    md.push("# " + b.title, "");
  } else if (b.subtitle) {
    children.push(para(b.subtitle, { size: 28, color: BLUE, bold: true, before: 0, after: 60 }));
    md.push("**" + b.subtitle + "**", "");
  } else if (b.meta) {
    children.push(new D.Paragraph({ children: runs(b.meta, { size: 20, color: GREY }), spacing: { before: 0, after: 160 },
      border: { bottom: { style: D.BorderStyle.SINGLE, size: 8, color: LINE, space: 8 } } }));
    md.push(b.meta, "");
  } else if (b.h1) {
    children.push(new D.Paragraph({ heading: D.HeadingLevel.HEADING_1, pageBreakBefore: !!(prev && prev.pagebreak), children: [new D.TextRun({ text: b.h1, font: FONT })] }));
    md.push("## " + b.h1, "");
  } else if (b.h2) {
    children.push(new D.Paragraph({ heading: D.HeadingLevel.HEADING_2, children: [new D.TextRun({ text: b.h2, font: FONT })] }));
    md.push("### " + b.h2, "");
  } else if (b.p) {
    children.push(para(b.p, { keepNext: !!(next && (next.img || next.table || next.bullets)) }));
    md.push(b.p, "");
  } else if (b.note) {
    children.push(para(b.note, { size: 19, color: GREY, before: 60, after: 160 }));
    md.push("*" + b.note + "*", "");
  } else if (b.bullets) {
    for (const t of b.bullets) children.push(new D.Paragraph({ children: runs(t), numbering: { reference: "bul", level: 0 }, spacing: { before: 20, after: 40, line: 300 } }));
    md.push(...b.bullets.map((t) => "- " + t), "");
  } else if (b.table) {
    children.push(table(b.table), gap(80));
    md.push("| " + b.table.head.join(" | ") + " |", "|" + b.table.head.map(() => "---").join("|") + "|", ...b.table.rows.map((r) => "| " + r.join(" | ") + " |"), "");
  } else if (b.callout) {
    children.push(callout(b.callout), gap(120));
    md.push(b.callout.map((l) => "> " + l).join("\n>\n"), "");
  } else if (b.img) {
    children.push(...image(b.img));
    md.push("![" + b.img.caption + "](fig/" + b.img.file + ")", "", "*" + b.img.caption + "*", "");
  }  // pagebreak blocks are applied as page-break-before on the following heading
}

const heading = (size, before, color) => ({ run: { font: FONT, size, bold: true, color }, paragraph: { spacing: { before, after: 140 }, keepNext: true } });
const doc = new D.Document({
  creator: "MAEK 팀 최재영", title: "MAEK 후속 보고", description: "실제 사진으로 다시 학습한 배관 판정 AI와 직접 확인하는 방법",
  styles: { default: { document: { run: { font: FONT, size: 22 } }, heading1: heading(32, 300, INK), heading2: heading(26, 240, BLUE) } },
  numbering: { config: [{ reference: "bul", levels: [{ level: 0, format: D.LevelFormat.BULLET, text: "•", alignment: D.AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 400, hanging: 240 } } } }] }] },
  sections: [{
    properties: { page: { margin: { top: 1134, bottom: 1134, left: 1134, right: 1134 } } },
    footers: { default: new D.Footer({ children: [new D.Paragraph({ alignment: D.AlignmentType.CENTER, children: [
      new D.TextRun({ children: ["MAEK 후속 보고 · ", D.PageNumber.CURRENT, " / ", D.PageNumber.TOTAL_PAGES], font: FONT, size: 18, color: GREY })] })] }) },
    children,
  }],
});

D.Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(path.join(OUT, "MAEK_followup_report.docx"), buf);
  fs.writeFileSync(path.join(OUT, "MAEK_followup_report.md"), md.join("\n").replace(/\n{3,}/g, "\n\n") + "\n");
  console.log("docx bytes", buf.length);
});
