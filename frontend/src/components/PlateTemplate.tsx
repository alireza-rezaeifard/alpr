/**
 * PlateTemplate — Visual Iranian License Plate Component
 *
 * Renders a realistic-looking Iranian plate for all types:
 * - Standard (Private, Taxi, Government, Police, Military, etc.)
 * - Free Zone (5-digit and 7-digit numeric-only plates)
 *
 * Color schemes match official Iranian plate colors:
 * - white: black text on white (Private, Disabled, Transit)
 * - yellow: black text on yellow (Taxi, Public, Agricultural)
 * - red: white text on red (Government)
 * - green: white text on green (Police, IRGC)
 * - blue: white text on blue (Military Defence, General Staff)
 * - black: white text on black (Diplomatic)
 */
import type { PlateMetadata } from '../types'

// Persian digit conversion
const toPersianDigits = (s: string) =>
  s.replace(/[0-9]/g, d => '۰۱۲۳۴۵۶۷۸۹'[parseInt(d)])

// Latin letter → Persian letter
const LATIN_TO_PERSIAN: Record<string, string> = {
  b: 'ب', j: 'ج', d: 'د', s: 'س', l: 'ل', m: 'م', n: 'ن',
  v: 'و', o: 'و', u: 'و', w: 'و', h: 'ه', y: 'ی', i: 'ی',
  q: 'ق', r: 'ر', x: 'خ', t: 'ت', k: 'ک', a: 'ا', p: 'پ',
  c: 'ث', e: 'ه', z: 'ز', f: 'ف', g: 'گ',
}

// Color scheme → CSS styles
const COLOR_SCHEMES: Record<string, { bg: string; text: string; border: string }> = {
  white:  { bg: '#ffffff', text: '#1a1a1a', border: '#333333' },
  yellow: { bg: '#f5c518', text: '#1a1a1a', border: '#b8860b' },
  red:    { bg: '#c0392b', text: '#ffffff', border: '#922b21' },
  green:  { bg: '#1a5c2a', text: '#ffffff', border: '#0d3d1a' },
  blue:   { bg: '#2471a3', text: '#ffffff', border: '#1a5276' },
  black:  { bg: '#1a1a1a', text: '#ffffff', border: '#000000' },
}

interface PlateTemplateProps {
  /** Raw DTRB text (latin, e.g. "12b34511") or Persian formatted text */
  plateText: string
  /** Plate metadata from backend (optional - enables colored rendering) */
  metadata?: PlateMetadata | null
  /** Override color scheme manually */
  colorScheme?: string
  /** Size variant */
  size?: 'sm' | 'md' | 'lg'
}

/**
 * Parse a plate string into its visual segments.
 * Standard Iranian plate: [2 digits][1 letter][3 digits][2 digits region]
 * Free Zone: all-numeric, 5 or 7 digits
 */
function parsePlate(text: string, category?: string): {
  type: 'standard' | 'freezone'
  prefix?: string
  letter?: string
  number?: string
  region?: string
  freeText?: string
} {
  // Normalize: strip spaces, dashes
  const normalized = text.replace(/[\s\-_]/g, '')
    .replace(/[۰-۹]/g, d => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))

  // Free Zone: all-numeric, 5 or 7 digits
  if (category === 'FreeZone' || category === 'FreeZone_Arvand') {
    return { type: 'freezone', freeText: normalized }
  }

  // Check if all-numeric 5 or 7 digits (auto-detect Free Zone)
  if (/^\d{5}$/.test(normalized) || /^\d{7}$/.test(normalized)) {
    return { type: 'freezone', freeText: normalized }
  }

  // Standard 8-char plate
  if (normalized.length === 8) {
    const prefix = normalized.slice(0, 2)
    const letter = normalized[2]
    const number = normalized.slice(3, 6)
    const region = normalized.slice(6, 8)

    // Verify prefix, number, region are digits
    if (/^\d{2}$/.test(prefix) && /^\d{3}$/.test(number) && /^\d{2}$/.test(region)) {
      return { type: 'standard', prefix, letter, number, region }
    }
  }

  // Fallback: try to detect from Persian-formatted text (۱۲ ب ۳۴۵-۱۱)
  const persianMatch = text.match(/^([\d۰-۹]{2})\s*(.)\s*([\d۰-۹]{3})\s*[-–]?\s*([\d۰-۹]{2})$/)
  if (persianMatch) {
    return {
      type: 'standard',
      prefix: persianMatch[1],
      letter: persianMatch[2],
      number: persianMatch[3],
      region: persianMatch[4],
    }
  }

  // Cannot parse — show as free text
  return { type: 'freezone', freeText: text }
}

export default function PlateTemplate({ plateText, metadata, colorScheme, size = 'md' }: PlateTemplateProps) {
  const scheme = colorScheme || metadata?.color_scheme || 'white'
  const colors = COLOR_SCHEMES[scheme] || COLOR_SCHEMES.white
  const category = metadata?.category

  const parsed = parsePlate(plateText, category)

  // Size config
  const sizes = {
    sm: { height: 28, fontSize: 13, regionFontSize: 10, padding: '2px 6px', gap: 2, flagWidth: 16 },
    md: { height: 36, fontSize: 16, regionFontSize: 12, padding: '3px 8px', gap: 3, flagWidth: 20 },
    lg: { height: 48, fontSize: 22, regionFontSize: 14, padding: '4px 12px', gap: 4, flagWidth: 26 },
  }
  const s = sizes[size]

  const containerStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    height: s.height,
    background: colors.bg,
    color: colors.text,
    border: `2px solid ${colors.border}`,
    borderRadius: 4,
    fontFamily: "'Vazirmatn', 'Vazir', 'B Nazanin', 'Tahoma', sans-serif",
    fontSize: s.fontSize,
    fontWeight: 700,
    direction: 'ltr',
    overflow: 'hidden',
    lineHeight: 1,
  }

  // Iran flag strip (left side)
  const flagStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    width: s.flagWidth,
    height: '100%',
    flexShrink: 0,
  }

  if (parsed.type === 'freezone') {
    // Free Zone plate: numbers only with "آ" prefix indicator
    const digits = parsed.freeText || plateText
    let displayText: string
    if (digits.replace(/\D/g, '').length === 7) {
      const nums = digits.replace(/\D/g, '')
      displayText = toPersianDigits(nums.slice(0, 5)) + '-' + toPersianDigits(nums.slice(5))
    } else if (digits.replace(/\D/g, '').length === 5) {
      displayText = toPersianDigits(digits.replace(/\D/g, ''))
    } else {
      displayText = toPersianDigits(digits)
    }

    return (
      <span style={containerStyle} title={metadata?.special_note || 'منطقه آزاد (Free Zone)'}>
        {/* Iran flag strip */}
        <span style={flagStyle}>
          <span style={{ flex: 1, background: '#239f40' }} />
          <span style={{ flex: 1, background: '#ffffff' }} />
          <span style={{ flex: 1, background: '#da0000' }} />
        </span>
        {/* Free Zone indicator */}
        <span style={{ padding: `0 ${s.gap}px`, fontSize: s.regionFontSize, opacity: 0.7, borderRight: `1px solid ${colors.border}40` }}>
          آ
        </span>
        {/* Plate number */}
        <span style={{ padding: s.padding, letterSpacing: 1 }}>
          {displayText}
        </span>
        {/* "منطقه آزاد" label */}
        <span style={{
          fontSize: s.regionFontSize - 2,
          padding: `0 ${s.gap + 2}px`,
          opacity: 0.6,
          borderLeft: `1px solid ${colors.border}40`,
          direction: 'rtl',
        }}>
          م.آ
        </span>
      </span>
    )
  }

  // Standard plate
  const { prefix, letter, number, region } = parsed
  const persianPrefix = toPersianDigits(prefix || '00')
  const persianNumber = toPersianDigits(number || '000')
  const persianRegion = toPersianDigits(region || '00')
  const persianLetter = letter
    ? (LATIN_TO_PERSIAN[letter.toLowerCase()] || letter)
    : '?'

  return (
    <span style={containerStyle} title={metadata?.category_display || metadata?.region_name || ''}>
      {/* Iran flag strip */}
      <span style={flagStyle}>
        <span style={{ flex: 1, background: '#239f40' }} />
        <span style={{ flex: 1, background: '#ffffff' }} />
        <span style={{ flex: 1, background: '#da0000' }} />
      </span>
      {/* Region code (right side on real plate, shown left here for LTR) */}
      <span style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: `0 ${s.gap + 1}px`,
        borderRight: `1px solid ${colors.border}60`,
        minWidth: s.flagWidth + 4,
      }}>
        <span style={{ fontSize: s.regionFontSize - 1, opacity: 0.6, lineHeight: 1 }}>ایران</span>
        <span style={{ fontSize: s.fontSize - 2, lineHeight: 1.2 }}>{persianRegion}</span>
      </span>
      {/* Main plate number section */}
      <span style={{ display: 'flex', alignItems: 'center', padding: s.padding, gap: s.gap + 2 }}>
        <span>{persianPrefix}</span>
        <span style={{
          color: scheme === 'white' || scheme === 'yellow' ? '#1a5c2a' : colors.text,
          fontSize: s.fontSize + 1,
        }}>{persianLetter}</span>
        <span>{persianNumber}</span>
      </span>
    </span>
  )
}
