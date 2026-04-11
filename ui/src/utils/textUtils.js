export function truncateText(text, maxLen) {
  if (!text) return "";
  const s = String(text);
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen - 1) + "…";
}
