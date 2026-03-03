/**
 * File type display: icon (VSCode Material Icon Theme), label, and color.
 * Icons live in static/icons/vscode-material/{iconName}.svg.
 *
 * Convention: for any extension not listed here we use the extension as the
 * icon name (e.g. "pdf" → pdf.svg). Only add overrides when the theme uses
 * a different name (e.g. doc/docx → word, xls/xlsx/csv → table) or you want
 * a custom label/color.
 */

export interface FileTypeConfig {
  /** Tailwind text color class for labels or accents */
  color: string;
  /** Display label (e.g. "PDF", "Word") */
  label: string;
  /** VSCode Material Icon Theme icon name (file: static/icons/vscode-material/{iconName}.svg) */
  iconName: string;
}

const DEFAULT_COLOR = 'text-gray-500';
const DEFAULT_LABEL = 'Document';

/**
 * Overrides only when icon name ≠ extension or custom label/color is needed.
 * Theme has: pdf, word, powerpoint, table, markdown, document, etc. No excel.svg → use table.
 */
const OVERRIDES: Record<string, Partial<FileTypeConfig>> = {
  doc: { iconName: 'word', label: 'Word', color: 'text-blue-500' },
  docx: { iconName: 'word', label: 'Word', color: 'text-blue-500' },
  xls: { iconName: 'table', label: 'Excel', color: 'text-green-600' },
  xlsx: { iconName: 'table', label: 'Excel', color: 'text-green-600' },
  csv: { iconName: 'table', label: 'CSV', color: 'text-green-700' },
  ppt: { iconName: 'powerpoint', label: 'PowerPoint', color: 'text-orange-500' },
  pptx: { iconName: 'powerpoint', label: 'PowerPoint', color: 'text-orange-500' },
  txt: { iconName: 'document', label: 'Text', color: 'text-gray-600' },
  md: { iconName: 'markdown', label: 'Markdown', color: 'text-gray-600' },
};

/**
 * Normalize file type: lowercase, no leading dot.
 */
function normalizeKey(fileType: string | undefined | null): string {
  if (!fileType || typeof fileType !== 'string') return '';
  return fileType.toLowerCase().replace(/^\./, '');
}

/**
 * Resolve config for a file type. Unknown extensions use the extension as
 * icon name (so if the theme has that SVG, it works without adding to OVERRIDES).
 */
export function getFileTypeConfig(fileType: string | undefined | null): FileTypeConfig {
  const key = normalizeKey(fileType);
  if (!key) {
    return { iconName: 'document', label: DEFAULT_LABEL, color: DEFAULT_COLOR };
  }
  const override = OVERRIDES[key];
  if (override) {
    return {
      iconName: override.iconName ?? key,
      label: override.label ?? key.toUpperCase(),
      color: override.color ?? DEFAULT_COLOR,
    };
  }
  return {
    iconName: key,
    label: key.toUpperCase(),
    color: DEFAULT_COLOR,
  };
}
