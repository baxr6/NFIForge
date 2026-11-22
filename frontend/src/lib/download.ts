// tables as files: csv, or excel (.xlsx, one sheet per table) from a small built-in writer. times are Date cells:
// written in the zone the settings show (utc or this browser's), with the zone in the header
export type Cell = string | number | boolean | Date | null | undefined
export type Col<T> = [header: string, value: (row: T) => Cell]
export type Sheet<T = any> = { name: string; rows: T[]; cols: Col<T>[] }

export const zoneName = (utc: boolean) => (utc ? "UTC" : Intl.DateTimeFormat().resolvedOptions().timeZone || "local")

// every scalar field the rows carry, minus the keys already given their own column: "every column" without naming each
export function restCols<T extends Record<string, any>>(rows: T[], skip: string[]): Col<T>[] {
  const keys = new Set<string>()
  for (const row of rows) for (const [key, value] of Object.entries(row)) if (!key.startsWith("_") && (value === null || typeof value !== "object")) keys.add(key)
  return [...keys].filter((key) => !skip.includes(key)).sort().map((key) => [key, (row: T) => row[key]])
}

const pad = (value: number, width = 2) => String(value).padStart(width, "0")
// the clock time in the zone as if it were utc: what a spreadsheet should show
const shift = (date: Date, utc: boolean) => date.getTime() - (utc ? 0 : date.getTimezoneOffset() * 60000)
function stamp(date: Date, utc: boolean) {
  const shifted = new Date(shift(date, utc))
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())} ${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`
}
const isTime = (value: Cell): value is Date => value instanceof Date && !Number.isNaN(value.getTime())

// headers of time columns get the zone
function headers(sheet: Sheet, utc: boolean) {
  return sheet.cols.map(([header, value]) => (sheet.rows.some((row) => isTime(value(row))) ? `${header} (${zoneName(utc)})` : header))
}

// ===========================================================================
// CSV
// ===========================================================================
function csvCell(value: Cell, utc: boolean): string {
  if (value == null || (typeof value === "number" && !Number.isFinite(value))) return ""
  if (isTime(value)) return stamp(value, utc)
  if (typeof value === "object") return ""  // an invalid date
  let text = String(value)
  // text that a spreadsheet would run as a formula
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function toCsv(sheet: Sheet, utc: boolean): Blob {
  const lines = [headers(sheet, utc).map((header) => csvCell(header, utc)).join(",")]
  for (const row of sheet.rows) lines.push(sheet.cols.map(([, value]) => csvCell(value(row), utc)).join(","))
  return new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" })  // bom: excel reads utf-8
}

// ===========================================================================
// XLSX: the minimum office open xml a spreadsheet opens, in a zip without compression
// ===========================================================================
const esc = (text: string) =>
  text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")

function colName(i: number) {
  let name = ""
  for (i += 1; i > 0; i = Math.floor((i - 1) / 26)) name = String.fromCharCode(65 + ((i - 1) % 26)) + name
  return name
}

// style 0 plain, 1 date-time, 2 bold header
function xCell(value: Cell, ref: string, utc: boolean, head = false): string {
  if (value == null || (typeof value === "number" && !Number.isFinite(value))) return ""
  if (isTime(value)) return `<c r="${ref}" s="1"><v>${shift(value, utc) / 86400000 + 25569}</v></c>`
  if (typeof value === "number") return `<c r="${ref}"><v>${value}</v></c>`
  if (typeof value === "boolean") return `<c r="${ref}" t="b"><v>${value ? 1 : 0}</v></c>`
  if (typeof value === "object") return ""  // an invalid date
  return `<c r="${ref}" t="inlineStr"${head ? ' s="2"' : ""}><is><t xml:space="preserve">${esc(String(value))}</t></is></c>`
}

function sheetXml(sheet: Sheet, utc: boolean): string {
  const rows = [headers(sheet, utc).map((header, i) => xCell(header, `${colName(i)}1`, utc, true)).join("")]
  sheet.rows.forEach((row, rowIndex) => rows.push(sheet.cols.map(([, value], i) => xCell(value(row), `${colName(i)}${rowIndex + 2}`, utc)).join("")))
  const widths = sheet.cols.map((_, i) => `<col min="${i + 1}" max="${i + 1}" width="${i === 0 ? 14 : 16}" customWidth="1"/>`).join("")
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' +
    (widths ? `<cols>${widths}</cols>` : "") +
    `<sheetData>${rows.map((cells, i) => `<row r="${i + 1}">${cells}</row>`).join("")}</sheetData></worksheet>`
}

// sheet names: 31 characters, none of []:*?/\ , unique
function sheetNames(sheets: Sheet[]) {
  const used = new Set<string>()
  return sheets.map((sheet) => {
    const base = (sheet.name.replace(/[[\]:*?/\\]/g, " ").trim() || "sheet").slice(0, 28)
    let name = base, suffix = 2
    while (used.has(name.toLowerCase())) name = `${base} ${suffix++}`
    used.add(name.toLowerCase())
    return name
  })
}

export function toXlsx(sheets: Sheet[], utc: boolean): Blob {
  const names = sheetNames(sheets)
  const schema = "http://schemas.openxmlformats.org"
  const files: [string, string][] = [
    ["[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      `<Types xmlns="${schema}/package/2006/content-types">` +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
      names.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("") +
      "</Types>"],
    ["_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      `<Relationships xmlns="${schema}/package/2006/relationships"><Relationship Id="rId1" Type="${schema}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
    ["xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      `<workbook xmlns="${schema}/spreadsheetml/2006/main" xmlns:r="${schema}/officeDocument/2006/relationships"><sheets>` +
      names.map((name, i) => `<sheet name="${esc(name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("") + "</sheets></workbook>"],
    ["xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      `<Relationships xmlns="${schema}/package/2006/relationships">` +
      names.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${schema}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("") +
      `<Relationship Id="rId${names.length + 1}" Type="${schema}/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`],
    ["xl/styles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      `<styleSheet xmlns="${schema}/spreadsheetml/2006/main">` +
      '<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm:ss"/></numFmts>' +
      '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>' +
      '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>' +
      '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>' +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
      '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>' +
      '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>' +
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'],
    ...sheets.map((sheet, i): [string, string] => [`xl/worksheets/sheet${i + 1}.xml`, sheetXml(sheet, utc)]),
  ]
  return new Blob([zip(files)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" })
}

// ===========================================================================
// ZIP (stored, no compression): local headers, then the central directory
// ===========================================================================
const CRC = (() => {
  const table = new Uint32Array(256)
  for (let byte = 0; byte < 256; byte++) {
    let value = byte
    for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
    table[byte] = value >>> 0
  }
  return table
})()
function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff
  for (let i = 0; i < bytes.length; i++) crc = CRC[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

function zip(files: [string, string][]): Uint8Array<ArrayBuffer> {
  const enc = new TextEncoder()
  const parts: Uint8Array[] = [], central: Uint8Array[] = []
  let offset = 0
  for (const [name, text] of files) {
    const nameBytes = enc.encode(name), data = enc.encode(text), crc = crc32(data)
    // version 20, utf-8 names (flag 0x800), stored, 1980-01-01 00:00
    const head = (sig: number, extra: number) => {
      const view = new DataView(new ArrayBuffer(extra))
      view.setUint32(0, sig, true)
      return view
    }
    const local = head(0x04034b50, 30 + nameBytes.length)
    local.setUint16(4, 20, true); local.setUint16(6, 0x800, true); local.setUint16(8, 0, true); local.setUint16(10, 0, true); local.setUint16(12, 0x21, true)
    local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true); local.setUint16(26, nameBytes.length, true)
    new Uint8Array(local.buffer).set(nameBytes, 30)
    const entry = head(0x02014b50, 46 + nameBytes.length)
    entry.setUint16(4, 20, true); entry.setUint16(6, 20, true); entry.setUint16(8, 0x800, true); entry.setUint16(14, 0x21, true)
    entry.setUint32(16, crc, true); entry.setUint32(20, data.length, true); entry.setUint32(24, data.length, true); entry.setUint16(28, nameBytes.length, true)
    entry.setUint32(42, offset, true)
    new Uint8Array(entry.buffer).set(nameBytes, 46)
    parts.push(new Uint8Array(local.buffer), data)
    central.push(new Uint8Array(entry.buffer))
    offset += 30 + nameBytes.length + data.length
  }
  const size = central.reduce((sum, entry) => sum + entry.length, 0)
  const end = new DataView(new ArrayBuffer(22))
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true)
  end.setUint32(12, size, true); end.setUint32(16, offset, true)
  const all = [...parts, ...central, new Uint8Array(end.buffer)]
  const out = new Uint8Array(all.reduce((sum, part) => sum + part.length, 0))
  let position = 0
  for (const part of all) { out.set(part, position); position += part.length }
  return out
}

// ===========================================================================
// SAVE
// ===========================================================================
export function save(blob: Blob, name: string) {
  const link = document.createElement("a")
  link.href = URL.createObjectURL(blob)
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(link.href), 10000)
}

// "trades-2026-10-23.csv"
export function fileName(base: string, ext: string) {
  const date = new Date()
  return `${base.replace(/[^\w.-]+/g, "-")}-${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}.${ext}`
}

// csv saves the first sheet (the table on screen); excel saves them all
export function download(base: string, format: "csv" | "xlsx", sheets: Sheet[], utc: boolean) {
  save(format === "csv" ? toCsv(sheets[0], utc) : toXlsx(sheets, utc), fileName(base, format))
}
