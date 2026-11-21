/** Decode semicolon-terminated HTML character references in a plain-text field. */
export function decodeHtmlEntities(text) {
  if (!text.includes('&')) return text;
  const decoder = document.createElement('textarea');
  // Feed the parser only individual character references, never raw input markup.
  return text.replace(/&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g, reference => {
    decoder.innerHTML = reference;
    return decoder.value;
  });
}
