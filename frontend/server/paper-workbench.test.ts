import test from 'node:test'
import assert from 'node:assert/strict'
import { deletePaperSheet, paperAncestorChain, sanitizePaperSheets } from '../src/paper-workbench.ts'

test('paper sanitizer preserves nested learning files and source papers', () => {
  const sheets = sanitizePaperSheets([
    { id: 'quote', title: '追问', quote: 'Q', sourceMessageId: 'm1', parentSheetId: 'main', messages: [], createdAt: 1 },
    { id: 'lecture', title: '讲义', quote: '', sourceMessageId: '', parentSheetId: 'quote', messages: [], createdAt: 2, artifact: { kind: 'lecture', ref: '8', title: 'L' } },
    { id: 'source', title: '资料', quote: '', sourceMessageId: '', parentSheetId: 'lecture', messages: [], createdAt: 3, artifact: { kind: 'source', ref: '13', title: 'S', projectId: 2 } },
  ])
  assert.deepEqual(paperAncestorChain(sheets, 'source').map(sheet => sheet.id), ['quote', 'lecture', 'source'])
  assert.equal(sheets[2].artifact?.kind, 'source')
})

test('paper sanitizer repairs missing parents, duplicates and cycles', () => {
  const sheets = sanitizePaperSheets([
    { id: 'a', title: 'A', parentSheetId: 'b', messages: [] },
    { id: 'b', title: 'B', parentSheetId: 'a', messages: [] },
    { id: 'orphan', title: 'O', parentSheetId: 'missing', messages: [] },
    { id: 'a', title: 'duplicate', parentSheetId: 'main', messages: [] },
  ])
  assert.equal(sheets.length, 3)
  assert.equal(sheets.find(sheet => sheet.id === 'a')?.parentSheetId, 'main')
  assert.equal(sheets.find(sheet => sheet.id === 'orphan')?.parentSheetId, 'main')
})

test('deleting a paper keeps its descendants reachable', () => {
  const sheets = sanitizePaperSheets([
    { id: 'a', title: 'A', parentSheetId: 'main', messages: [] },
    { id: 'b', title: 'B', parentSheetId: 'a', messages: [] },
    { id: 'c', title: 'C', parentSheetId: 'b', messages: [] },
  ])
  const result = deletePaperSheet(sheets, 'b')
  assert.equal(result.parentSheetId, 'a')
  assert.equal(result.sheets.find(sheet => sheet.id === 'c')?.parentSheetId, 'a')
})
