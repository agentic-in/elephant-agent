"""JavaScript snippets injected by the browser backend."""

SNAPSHOT_JS = r"""
(arg) => {
  const refAttr = 'data-elephant-browser-ref';
  const maxElements = Math.max(1, Number(arg.maxElements || 120));
  const compactLimit = Math.max(500, Number(arg.compactLimit || 4000));
  const fullLimit = Math.max(compactLimit, Number(arg.fullLimit || 24000));
  const full = Boolean(arg.full);
  const selector = [
    'a[href]',
    'button',
    'input',
    'textarea',
    'select',
    'summary',
    '[role="button"]',
    '[role="link"]',
    '[role="checkbox"]',
    '[role="menuitem"]',
    '[onclick]',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const labelFor = (el) => {
    const parts = [
      el.getAttribute('aria-label'),
      el.getAttribute('placeholder'),
      el.getAttribute('title'),
      el.innerText,
      el.value,
      el.getAttribute('name')
    ].map(clean).filter(Boolean);
    return parts[0] || clean(el.tagName.toLowerCase());
  };
  const roleFor = (el) => {
    const explicit = clean(el.getAttribute('role'));
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'input') return clean(el.getAttribute('type')) || 'input';
    return tag;
  };
  document.querySelectorAll('[' + refAttr + ']').forEach((el) => el.removeAttribute(refAttr));
  const nodes = Array.from(document.querySelectorAll(selector)).filter(visible).slice(0, maxElements);
  const elements = nodes.map((el, index) => {
    const ref = `@e${index + 1}`;
    el.setAttribute(refAttr, ref);
    const rect = el.getBoundingClientRect();
    return {
      ref,
      tag: el.tagName.toLowerCase(),
      role: roleFor(el),
      label: labelFor(el).slice(0, 180),
      href: clean(el.getAttribute('href')),
      disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    };
  });
  const bodyText = clean(document.body ? document.body.innerText : '');
  const limit = full ? fullLimit : compactLimit;
  const truncatedText = bodyText.length > limit ? bodyText.slice(0, limit) + `\n[... ${bodyText.length - limit} chars truncated]` : bodyText;
  return {
    title: document.title || '',
    url: location.href,
    text: truncatedText,
    elementCount: elements.length,
    elements
  };
}
"""

IMAGES_JS = r"""
(arg) => Array.from(document.images).slice(0, Number(arg.maxImages || 80)).map((image, index) => ({
  index: index + 1,
  src: image.currentSrc || image.src || '',
  alt: image.alt || '',
  width: image.naturalWidth || image.width || 0,
  height: image.naturalHeight || image.height || 0
})).filter((image) => image.src && !image.src.startsWith('data:'))
"""

ANNOTATE_JS = r"""
() => {
  document.querySelectorAll('[data-elephant-browser-annotation]').forEach((node) => node.remove());
  const refs = Array.from(document.querySelectorAll('[data-elephant-browser-ref]'));
  refs.forEach((el) => {
    const ref = el.getAttribute('data-elephant-browser-ref') || '';
    const rect = el.getBoundingClientRect();
    const label = document.createElement('div');
    label.textContent = ref.replace('@e', '');
    label.setAttribute('data-elephant-browser-annotation', 'true');
    Object.assign(label.style, {
      position: 'fixed',
      left: `${Math.max(0, rect.left)}px`,
      top: `${Math.max(0, rect.top)}px`,
      zIndex: '2147483647',
      padding: '2px 5px',
      borderRadius: '4px',
      background: '#f43f5e',
      color: 'white',
      fontSize: '12px',
      fontFamily: 'system-ui, sans-serif',
      fontWeight: '700',
      pointerEvents: 'none'
    });
    document.body.appendChild(label);
  });
  return refs.length;
}
"""

CLEAR_ANNOTATIONS_JS = (
    "() => document.querySelectorAll('[data-elephant-browser-annotation]').forEach((node) => node.remove())"
)

__all__ = ["ANNOTATE_JS", "CLEAR_ANNOTATIONS_JS", "IMAGES_JS", "SNAPSHOT_JS"]
