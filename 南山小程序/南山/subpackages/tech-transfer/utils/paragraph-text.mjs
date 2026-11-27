export function splitParagraphs(text) {
  return String(text ?? '')
    .replace(/\r\n?/g, '\n')
    .split(/\n+/)
    .map((line) => line.replace(/^[\s\u3000]+|[\s\u3000]+$/g, ''))
    .filter(Boolean)
}

export function formatPreviewText(text) {
  return String(text ?? '')
    .replace(/[\s\u3000]+/g, ' ')
    .trim()
}
