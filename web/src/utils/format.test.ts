import { describe, expect, test } from 'vitest'
import { escapeHtml, fmt } from './format'

describe('fmt', () => {
  test('groups thousands', () => { expect(fmt(362733)).toBe('362,733') })
  test('renders an em dash for null', () => { expect(fmt(null)).toBe('—') })
  test('renders an em dash for undefined', () => { expect(fmt(undefined)).toBe('—') })
  test('renders zero as zero, not a dash', () => { expect(fmt(0)).toBe('0') })
})

describe('escapeHtml', () => {
  test('escapes the four dangerous characters', () => {
    expect(escapeHtml('<a href="x">&</a>'))
      .toBe('&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;')
  })
  test('escapes the ampersand first so entities are not doubled', () => {
    expect(escapeHtml('&lt;')).toBe('&amp;lt;')
  })
  test('escapes the apostrophe so single-quoted attributes stay safe', () => {
    expect(escapeHtml("it's")).toBe('it&#39;s')
  })
  test('passes Thai text through unchanged', () => {
    expect(escapeHtml('ไม่นับ')).toBe('ไม่นับ')
  })
  test('stringifies numbers', () => { expect(escapeHtml(42)).toBe('42') })
})
